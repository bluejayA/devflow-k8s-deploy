"""BuildRunner — opt-in 컨테이너 빌드 인라인 (F-53~F-58, F-102, NFR-SEC-05).

보안 기준 (NFR-SEC-05):
  - subprocess.run은 반드시 shell=False
  - cmd는 list[str] 형태 argv (문자열 금지)
  - allowlist: [engine, "build", "-t", image_tag, "-f", dockerfile, context_dir]
    정확히 7개 요소. push/pull 관련 인자 절대 추가 금지.

기능 기준:
  - F-53: build.engine=skip(기본)이면 즉시 skipped=True 반환
  - F-57: auto 모드 — docker → podman → nerdctl 순으로 shutil.which 감지
  - F-57: 명시 엔진 — 해당 엔진만 사용, 미설치 시 degraded
  - F-58: 미감지 시 경고 후 degraded (skipped=True, 한국어 사유)
  - F-102: 빌드 타임아웃 600초 기본. 초과 시 실패(success=False)로 변환
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Literal

from scripts._shared.fileio import is_within
from scripts._shared.image_ref import validate_image_reference
from scripts._shared.types import BuildResult

# 빌드 엔진 자동 감지 우선순위 (F-57)
RealEngine = Literal["docker", "podman", "nerdctl"]
_AUTO_ENGINE_ORDER: tuple[RealEngine, ...] = ("docker", "podman", "nerdctl")

# 빌드 타임아웃 기본값 (F-102) — 참조/문서용 상수; __init__ 기본값 출처
_BUILD_TIMEOUT_SECONDS = 600

# 한국어 skip 메시지 (F-58)
_MSG_SKIP_MODE = "컨테이너 빌드가 skip 모드로 설정되어 있음 (build.engine=skip)"
_MSG_AUTO_NOT_FOUND = (
    "컨테이너 빌드 엔진(docker/podman/nerdctl) 중 어느 것도 설치되지 않음 — 빌드 건너뜀"
)


def _msg_explicit_not_found(engine: str) -> str:
    return f"지정된 컨테이너 엔진 '{engine}'이(가) 설치되어 있지 않음 — 빌드 건너뜀"


BuildEngineMode = Literal["skip", "auto", "docker", "podman", "nerdctl"]


class BuildRunner:
    """opt-in 컨테이너 빌드 인라인.

    build.engine:
      - skip (default): run()이 즉시 skipped=True 반환
      - auto: docker → podman → nerdctl 순으로 first available 감지
      - docker / podman / nerdctl: 해당 엔진만 사용 (미설치 시 degraded)

    경계 (NFR-SEC-05):
      - shell=False, argv list
      - build/image tag 외 인자 허용 안 함
      - push 금지 (docker push / podman push 등 절대 호출 안 함)
    """

    def __init__(
        self,
        build_engine: BuildEngineMode,
        *,
        build_timeout_seconds: int = _BUILD_TIMEOUT_SECONDS,
    ) -> None:
        """BuildRunner 초기화.

        Args:
            build_engine: 빌드 엔진 모드.
                'skip' — 빌드 비활성화 (기본값).
                'auto' — docker → podman → nerdctl 순 자동 감지.
                'docker' / 'podman' / 'nerdctl' — 해당 엔진만 사용.
            build_timeout_seconds: subprocess 타임아웃 (초). 기본 600 (F-102).
                0 이면 무제한. 음수 불가.
        """
        if build_timeout_seconds < 0:
            raise ValueError(
                f"build_timeout_seconds는 0 이상이어야 함: {build_timeout_seconds}"
            )
        self._build_engine: BuildEngineMode = build_engine
        self._build_timeout_seconds = build_timeout_seconds

    def detect_engine(self) -> RealEngine | None:
        """빌드 엔진 감지.

        build_engine=skip이면 None.
        build_engine=auto이면 docker → podman → nerdctl 순으로 shutil.which 확인.
        build_engine=명시 엔진이면 해당 엔진 (미설치 시 None → degraded).

        Returns:
            감지된 엔진 이름 ('docker'/'podman'/'nerdctl') 또는 None.
        """
        if self._build_engine == "skip":
            return None

        if self._build_engine == "auto":
            for candidate in _AUTO_ENGINE_ORDER:
                if shutil.which(candidate) is not None:
                    return candidate
            return None

        # 명시 엔진 (BuildEngineMode에서 skip/auto 제외 = RealEngine으로 좁혀짐)
        explicit: RealEngine = self._build_engine
        return explicit if shutil.which(explicit) is not None else None

    def build(
        self,
        context_dir: Path,
        image_tag: str,
        *,
        dockerfile: Path | None = None,
    ) -> BuildResult:
        """컨테이너 이미지 빌드.

        build_engine=skip이면 skipped=True, success=True 반환 (즉시).
        엔진 감지 실패 → skipped=True, skip_reason_ko 한국어 사유.
        엔진 실행 시:
          - cmd: [engine, "build", "-t", image_tag, "-f", str(dockerfile or "Dockerfile"),
                 str(context_dir)]
          - shell=False, argv list
          - timeout: build_timeout_seconds 초 (F-102, 0=무제한)

        Args:
            context_dir: 컨테이너 빌드 컨텍스트 디렉토리. 존재해야 함.
            image_tag: OCI 이미지 참조 (validate_image_reference 통과 필수).
            dockerfile: Dockerfile 경로 (None이면 context_dir/Dockerfile 사용).

        Returns:
            BuildResult(
                success=bool,
                engine=str|None,
                image_ref=str|None,
                skipped=bool,
                skip_reason_ko=str|None,
                stdout=str|None,
                stderr=str|None,
                exit_code=int|None,
            )

        Raises:
            InvalidImageError: image_tag가 유효하지 않거나 'latest' 태그인 경우.
            ValueError: context_dir이 존재하지 않거나, dockerfile이 context_dir 밖에 있는 경우.
        """
        # skip 모드 — 즉시 반환 (validate도 건너뜀)
        if self._build_engine == "skip":
            return BuildResult(
                success=True,
                engine=None,
                image_ref=None,
                skipped=True,
                skip_reason_ko=_MSG_SKIP_MODE,
            )

        # 입력 검증
        validate_image_reference(image_tag)
        context_dir = context_dir.resolve()
        if not context_dir.is_dir():
            raise ValueError(f"context_dir이 유효한 디렉토리가 아님: {context_dir}")

        if dockerfile is not None:
            if not dockerfile.resolve().is_file():
                raise ValueError(f"dockerfile이 유효한 파일이 아님: {dockerfile.resolve()}")
            # context_dir 내부 확인 (symlink escape 방어 포함)
            if not is_within(context_dir, dockerfile):
                raise ValueError(
                    f"dockerfile이 context_dir 밖을 가리킴: {dockerfile.name}"
                )
            dockerfile = dockerfile.resolve()
        else:
            dockerfile = context_dir / "Dockerfile"

        # 엔진 감지
        engine = self.detect_engine()

        if engine is None:
            # degraded — 엔진 미감지
            if self._build_engine == "auto":
                reason = _MSG_AUTO_NOT_FOUND
            else:
                reason = _msg_explicit_not_found(self._build_engine)
            return BuildResult(
                success=True,
                engine=None,
                image_ref=None,
                skipped=True,
                skip_reason_ko=reason,
            )

        # 빌드 실행
        cmd = self._build_command(engine, context_dir, image_tag, dockerfile)
        timeout_arg = None if self._build_timeout_seconds == 0 else self._build_timeout_seconds
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="replace",
                shell=False,
                timeout=timeout_arg,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return BuildResult(
                success=False,
                engine=engine,
                image_ref=None,
                skipped=False,
                skip_reason_ko=f"빌드 타임아웃 ({self._build_timeout_seconds}초 초과)",
                stdout=exc.stdout.decode("utf-8", errors="replace") if exc.stdout else None,
                stderr=exc.stderr.decode("utf-8", errors="replace") if exc.stderr else None,
                exit_code=None,
            )

        return BuildResult(
            success=(proc.returncode == 0),
            engine=engine,
            image_ref=image_tag if proc.returncode == 0 else None,
            skipped=False,
            skip_reason_ko=None,
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )

    def _build_command(
        self,
        engine: RealEngine,
        context_dir: Path,
        image_tag: str,
        dockerfile: Path,
    ) -> list[str]:
        """allowlist cmd 구성.

        반드시 이 정확한 7개 요소만:
            [engine, "build", "-t", image_tag, "-f", str(dockerfile), str(context_dir)]

        push/pull 관련 인자 절대 추가 금지 (NFR-SEC-05).
        """
        # Defense-in-depth: 호출자가 Literal 타입을 우회해도 런타임에서 차단
        if engine not in _AUTO_ENGINE_ORDER:
            raise ValueError(f"허용되지 않은 엔진: {engine!r}")
        cmd: list[str] = [
            engine,
            "build",
            "-t",
            image_tag,
            "-f",
            str(dockerfile),
            str(context_dir),
        ]
        assert len(cmd) == 7, f"cmd는 정확히 7 요소여야 함: {cmd}"
        return cmd
