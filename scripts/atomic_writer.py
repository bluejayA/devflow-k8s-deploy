"""AtomicWriter — 임시 디렉토리 기반 atomic rename 유틸리티.

사용 패턴::

    with AtomicWriter(output_dir, on_exists="overwrite") as aw:
        # aw.staging_dir 에 파일 생성/복사
        (aw.staging_dir / "Dockerfile").write_text(...)
        final_path = aw.commit()          # output_dir 으로 atomic rename
    # 예외 발생 또는 commit 미호출 → staging_dir 자동 정리

설계 결정:
- 임시 디렉토리: ``output_dir.parent / ".tmp-{uuid4().hex}"``
- atomic rename: ``os.replace(staging_dir, final_path)`` (POSIX atomic)
- 7일 고아 GC: ``.tmp-*`` glob → ``lstat().st_mtime`` 7일 이상 → shutil.rmtree
  (symlink는 타겟 경로를 따라가지 않고 symlink 자체만 unlink)
- signal handler: SIGINT/SIGTERM 등록 → cleanup + sys.exit(130) → 이전 핸들러로 복구
  (__enter__ 실패 시에도 원복 보장)
- suffix 타임스탬프: UTC ISO 8601 분단위 ``"%Y-%m-%dT%H-%M"``
  동일 분 내 충돌 시 ``-2``, ``-3`` ... 카운터 추가 (상한 100)

**Precondition — 단일 활성 인스턴스**: 동일 프로세스에서 두 개의 AtomicWriter가
동시에 ``__enter__`` 상태로 공존하면 signal handler 체인이 꼬여, 먼저
``__exit__``한 쪽이 다른 쪽의 "이전 핸들러"를 덮어쓴다. v0.1.0은 단일 스레드·순차
사용 전제. 중첩/동시 사용 시 결과는 정의되지 않음. 멀티스레드 환경에서는
``signal.signal()``이 메인 스레드에서만 동작하므로 추가 제약이 있다.
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import time
import types as _types
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from scripts._shared.errors import OutputExistsAbort
from scripts._shared.types import PromptCallback, PromptRequest

# 7일을 초 단위로
_ORPHAN_MAX_AGE_SECONDS = 7 * 24 * 3600

_VALID_ON_EXISTS = ("prompt", "overwrite", "suffix")

# signal.signal() 반환 타입: Callable | int | None
# private `signal._HANDLER` 참조 대신 커스텀 alias 사용
_SignalHandler = Callable[[int, _types.FrameType | None], Any] | int | None


class AtomicWriter:
    """임시 디렉토리(.tmp-{uuid}/)에 쓰고 원자적으로 output_dir로 이름 변경.

    **Precondition — 단일 활성 인스턴스**: 동일 프로세스에서 두 개의 AtomicWriter가
    동시에 ``__enter__`` 상태로 공존하면 signal handler 체인이 꼬여, 먼저
    ``__exit__``한 쪽이 다른 쪽의 "이전 핸들러"를 덮어쓴다. v0.1.0은 단일
    스레드·순차 사용 전제. 중첩/동시 사용 시 결과는 정의되지 않음. 멀티스레드
    환경에서는 ``signal.signal()``이 메인 스레드에서만 동작하므로 추가 제약이 있다.

    Args:
        output_dir: 최종 출력 디렉토리 경로.
        on_exists: output_dir가 이미 존재할 때 동작.
            - ``"prompt"``: prompt_callback 호출 → 사용자 선택
            - ``"overwrite"``: 기존 삭제 후 rename
            - ``"suffix"``: ``output_dir-YYYY-MM-DDTHH-MM/`` 형태로 rename
              (동일 분 충돌 시 ``-2``, ``-3`` ... 카운터 추가)
        prompt_callback: ``on_exists="prompt"``일 때 호출되는 콜백.
            ``None``이면 output_dir 존재 시 ``OutputExistsAbort`` raise.
    """

    def __init__(
        self,
        output_dir: Path,
        on_exists: Literal["prompt", "overwrite", "suffix"],
        prompt_callback: PromptCallback | None = None,
    ) -> None:
        if on_exists not in _VALID_ON_EXISTS:
            raise ValueError(
                f"on_exists는 {_VALID_ON_EXISTS} 중 하나여야 합니다: {on_exists!r}"
            )
        self._output_dir = output_dir
        self._on_exists = on_exists
        self._prompt_callback = prompt_callback

        # staging_dir: output_dir.parent / ".tmp-{uuid4().hex}"
        self._staging_dir: Path = output_dir.parent / f".tmp-{uuid4().hex}"

        # signal handler 이전 핸들러 저장용
        self._prev_sigint: _SignalHandler = None
        self._prev_sigterm: _SignalHandler = None

        # commit 호출 여부 플래그
        self._committed: bool = False

        # bailout_commit 호출 여부 플래그 — True이면 __exit__ cleanup 스킵
        self._bailed_out: bool = False

    # ─── context manager ──────────────────────────────────────────────────────

    def __enter__(self) -> AtomicWriter:
        """1) signal handler 등록 (SIGINT, SIGTERM)
        2) 7일 이상 고아 .tmp-* 자동 회수
        3) 새 .tmp-{uuid}/ 생성

        signal 등록 이후 실패(GC 또는 mkdir 오류) 시 handler를 원복한 뒤 재전파.
        """
        self._prev_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        self._prev_sigterm = signal.signal(signal.SIGTERM, self._signal_handler)
        try:
            self._gc_orphans()
            self._staging_dir.mkdir(parents=True, exist_ok=False)
        except BaseException:
            # handler 원복 후 재전파
            self._restore_signal_handlers()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: _types.TracebackType | None,
    ) -> None:
        """예외 없이 정상 종료: commit 미호출이면 cleanup.
        예외 발생: cleanup (output_dir 이전 상태 유지).
        bailout_commit 호출됨: cleanup 스킵 (staging이 이미 rename됨).
        signal handler 이전 핸들러로 복구.
        """
        try:
            if exc_type is None:
                # 정상 종료
                if not self._committed and not self._bailed_out:
                    self.cleanup()
            else:
                # 예외 발생 — bailout_commit이 이미 호출됐으면 cleanup 스킵
                if not self._bailed_out:
                    self.cleanup()
        finally:
            self._restore_signal_handlers()

    # ─── public API ───────────────────────────────────────────────────────────

    @property
    def staging_dir(self) -> Path:
        """현재 .tmp-{uuid}/ 경로. 호출자의 모든 쓰기는 여기로."""
        return self._staging_dir

    def commit(self) -> Path:
        """검증 통과 후 호출.

        on_exists 분기:
          - ``"prompt"``: prompt_callback 호출 → 사용자 선택에 따라
            overwrite/suffix/OutputExistsAbort
          - ``"overwrite"``: 기존 output_dir 삭제 후 atomic rename
          - ``"suffix"``: ``output_dir-YYYY-MM-DDTHH-MM/`` 형태로 suffix 후 rename

        Returns:
            최종 디렉토리 경로.

        Raises:
            OutputExistsAbort: prompt 모드에서 사용자가 "취소" 선택 또는 callback=None.
        """
        final_path = self._resolve_final_path()
        os.replace(self._staging_dir, final_path)
        self._committed = True
        return final_path

    def bailout_commit(self) -> Path:
        """BailOut 시 staging_dir 내용 보존 — ``{output_dir}-failed-{timestamp}/``로 이동.

        호출 후 ``__exit__``는 cleanup을 스킵한다 (staging이 이미 rename됨).
        timestamp 형식: ``"%Y-%m-%dT%H-%M"`` UTC.

        동일 분 내 충돌 시 ``-2``, ``-3`` ... 카운터를 붙여 중복을 피한다.
        100회 초과 충돌 시 ``OutputExistsAbort`` raise.

        Returns:
            실패 결과가 보존된 디렉토리 경로.

        Raises:
            OutputExistsAbort: 100회 초과 경로 충돌.
        """
        timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H-%M")
        base = self._output_dir.parent / f"{self._output_dir.name}-failed-{timestamp}"
        candidate = base
        counter = 2
        while candidate.exists():
            candidate = (
                self._output_dir.parent
                / f"{self._output_dir.name}-failed-{timestamp}-{counter}"
            )
            counter += 1
            if counter > 100:
                raise OutputExistsAbort(
                    f"bailout suffix 경로 충돌 과다 (100회 초과): {base}"
                )
        os.replace(self._staging_dir, candidate)
        self._bailed_out = True
        return candidate

    def cleanup(self) -> None:
        """staging_dir 삭제. 실패해도 raise 안 함 (best effort)."""
        try:
            if self._staging_dir.exists():
                shutil.rmtree(self._staging_dir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

    # ─── internal ─────────────────────────────────────────────────────────────

    def _restore_signal_handlers(self) -> None:
        """이전 SIGINT/SIGTERM 핸들러를 복구한다."""
        if self._prev_sigint is not None:
            signal.signal(signal.SIGINT, self._prev_sigint)
            self._prev_sigint = None
        if self._prev_sigterm is not None:
            signal.signal(signal.SIGTERM, self._prev_sigterm)
            self._prev_sigterm = None

    def _signal_handler(self, signum: int, frame: _types.FrameType | None) -> None:
        """SIGINT/SIGTERM 수신 시 cleanup → sys.exit(130)."""
        self.cleanup()
        sys.exit(130)

    def _gc_orphans(self) -> None:
        """output_dir.parent / .tmp-* 중 mtime 7일 이상 경과한 항목 삭제.

        보안:
        - symlink는 타겟 경로를 따라가지 않고 symlink 자체만 unlink.
          (공격자가 ``.tmp-evil → /important/path`` symlink를 심어도 임의 경로 삭제
          방지)
        - 실제 디렉토리에 대해서만 shutil.rmtree 사용.
        - mtime은 lstat() (follow_symlinks=False) 기준.
        """
        parent = self._output_dir.parent
        if not parent.exists():
            return

        now = time.time()
        for candidate in parent.glob(".tmp-*"):
            # symlink는 타겟을 따라가지 않고 자체만 제거
            if candidate.is_symlink():
                try:
                    candidate.unlink()
                except OSError:
                    pass
                continue
            try:
                st = candidate.lstat()  # follow_symlinks=False
            except OSError:
                # stat() 실패 (race condition 등) — 무시
                continue
            # 실제 디렉토리만 대상
            if not candidate.is_dir():
                continue
            age_seconds = now - st.st_mtime
            if age_seconds >= _ORPHAN_MAX_AGE_SECONDS:
                shutil.rmtree(candidate, ignore_errors=True)

    def _resolve_final_path(self) -> Path:
        """on_exists 설정에 따라 최종 경로를 결정한다.

        Raises:
            OutputExistsAbort: prompt 모드 취소 또는 callback=None.
        """
        output_dir = self._output_dir

        if not output_dir.exists():
            # output_dir이 없으면 on_exists 관계없이 그냥 rename
            return output_dir

        # output_dir가 이미 존재하는 경우
        mode = self._on_exists

        if mode == "overwrite":
            return self._do_overwrite(output_dir)

        if mode == "suffix":
            return self._do_suffix(output_dir)

        # mode == "prompt"
        return self._do_prompt(output_dir)

    def _do_overwrite(self, output_dir: Path) -> Path:
        """기존 output_dir 삭제 후 final_path 반환 (staging이 그 자리로 들어감)."""
        shutil.rmtree(output_dir)
        return output_dir

    def _do_suffix(self, output_dir: Path) -> Path:
        """output_dir-YYYY-MM-DDTHH-MM/ 형태의 신규 경로 반환.

        동일 분 내 충돌 시 ``-2``, ``-3`` ... 카운터를 붙여 중복을 피한다.
        100회 초과 충돌 시 ``OutputExistsAbort`` raise.
        """
        timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H-%M")
        base = output_dir.parent / f"{output_dir.name}-{timestamp}"
        candidate = base
        counter = 2
        while candidate.exists():
            candidate = output_dir.parent / f"{output_dir.name}-{timestamp}-{counter}"
            counter += 1
            if counter > 100:  # 현실적 상한 방어
                raise OutputExistsAbort(
                    f"suffix 경로 충돌이 너무 많음 (100회 초과): {base}"
                )
        return candidate

    def _do_prompt(self, output_dir: Path) -> Path:
        """prompt_callback 호출 후 사용자 선택에 따라 분기.

        Raises:
            OutputExistsAbort: callback=None 또는 "취소" 선택.
        """
        if self._prompt_callback is None:
            raise OutputExistsAbort(
                f"'{output_dir}'이 이미 존재합니다. "
                "on_exists='prompt'이지만 prompt_callback이 None입니다."
            )

        req = PromptRequest(
            kind="confirm",
            ko_text=f"'{output_dir}'에 이미 파일이 있어요. 덮어쓸까요?",
            options=["덮어쓰기", "취소", "suffix로 새 디렉토리 만들기"],
            help_term_id="output_dir",
        )
        choice = self._prompt_callback(req)

        if choice == "덮어쓰기":
            return self._do_overwrite(output_dir)
        if choice == "suffix로 새 디렉토리 만들기":
            return self._do_suffix(output_dir)
        # "취소" 또는 기타 모든 값
        raise OutputExistsAbort(
            f"사용자가 '{output_dir}' 출력을 취소했습니다."
        )
