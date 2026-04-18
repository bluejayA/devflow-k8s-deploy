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
- 7일 고아 GC: ``.tmp-*`` glob → ``stat().st_mtime`` 7일 이상 → shutil.rmtree
- signal handler: SIGINT/SIGTERM 등록 → cleanup + sys.exit(130) → 이전 핸들러로 복구
- suffix 타임스탬프: UTC ISO 8601 분단위 ``"%Y-%m-%dT%H-%M"``
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from scripts._shared.errors import OutputExistsAbort
from scripts._shared.types import PromptCallback, PromptRequest

# 7일을 초 단위로
_ORPHAN_MAX_AGE_SECONDS = 7 * 24 * 3600


class AtomicWriter:
    """임시 디렉토리(.tmp-{uuid}/)에 쓰고 원자적으로 output_dir로 이름 변경.

    Args:
        output_dir: 최종 출력 디렉토리 경로.
        on_exists: output_dir가 이미 존재할 때 동작.
            - ``"prompt"``: prompt_callback 호출 → 사용자 선택
            - ``"overwrite"``: 기존 삭제 후 rename
            - ``"suffix"``: ``output_dir-YYYY-MM-DDTHH-MM/`` 형태로 rename
        prompt_callback: ``on_exists="prompt"``일 때 호출되는 콜백.
            ``None``이면 output_dir 존재 시 ``OutputExistsAbort`` raise.
    """

    def __init__(
        self,
        output_dir: Path,
        on_exists: Literal["prompt", "overwrite", "suffix"],
        prompt_callback: PromptCallback | None = None,
    ) -> None:
        self._output_dir = output_dir
        self._on_exists = on_exists
        self._prompt_callback = prompt_callback

        # staging_dir: output_dir.parent / ".tmp-{uuid4().hex}"
        self._staging_dir: Path = output_dir.parent / f".tmp-{uuid4().hex}"

        # signal handler 이전 핸들러 저장용
        # signal.signal() 반환 타입이 _HANDLER (Callable | int | None)이므로 Any 사용
        self._prev_sigint: signal._HANDLER = None
        self._prev_sigterm: signal._HANDLER = None

        # commit 호출 여부 플래그
        self._committed: bool = False

    # ─── context manager ──────────────────────────────────────────────────────

    def __enter__(self) -> AtomicWriter:
        """1) signal handler 등록 (SIGINT, SIGTERM)
        2) 7일 이상 고아 .tmp-* 자동 회수
        3) 새 .tmp-{uuid}/ 생성
        """
        # signal handler 등록 (이전 핸들러 저장)
        self._prev_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        self._prev_sigterm = signal.signal(signal.SIGTERM, self._signal_handler)

        # 고아 GC
        self._gc_orphans()

        # staging_dir 생성
        self._staging_dir.mkdir(parents=True, exist_ok=False)

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """예외 없이 정상 종료: commit 미호출이면 cleanup.
        예외 발생: cleanup (output_dir 이전 상태 유지).
        signal handler 이전 핸들러로 복구.
        """
        try:
            if exc_type is None:
                # 정상 종료
                if not self._committed:
                    self.cleanup()
            else:
                # 예외 발생 — staging_dir 정리
                self.cleanup()
        finally:
            # signal handler 원복 (이전 핸들러로 복구)
            if self._prev_sigint is not None:
                signal.signal(signal.SIGINT, self._prev_sigint)
                self._prev_sigint = None
            if self._prev_sigterm is not None:
                signal.signal(signal.SIGTERM, self._prev_sigterm)
                self._prev_sigterm = None

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

    def cleanup(self) -> None:
        """staging_dir 삭제. 실패해도 raise 안 함 (best effort)."""
        try:
            if self._staging_dir.exists():
                shutil.rmtree(self._staging_dir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

    # ─── internal ─────────────────────────────────────────────────────────────

    def _signal_handler(self, signum: int, frame: types.FrameType | None) -> None:
        """SIGINT/SIGTERM 수신 시 cleanup → sys.exit(130)."""
        self.cleanup()
        sys.exit(130)

    def _gc_orphans(self) -> None:
        """output_dir.parent / .tmp-* 중 mtime 7일 이상 경과한 디렉토리 삭제."""
        parent = self._output_dir.parent
        if not parent.exists():
            return

        now = datetime.now(tz=UTC).timestamp()
        for candidate in parent.glob(".tmp-*"):
            if not candidate.is_dir():
                continue
            try:
                mtime = candidate.stat().st_mtime
                age_seconds = now - mtime
                if age_seconds >= _ORPHAN_MAX_AGE_SECONDS:
                    shutil.rmtree(candidate, ignore_errors=True)
            except OSError:
                # stat() 실패 (race condition 등) — 무시
                pass

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
        """output_dir-YYYY-MM-DDTHH-MM/ 형태의 신규 경로 반환."""
        ts = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H-%M")
        suffix_path = output_dir.parent / f"{output_dir.name}-{ts}"
        return suffix_path

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
