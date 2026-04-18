"""KubectlDryRunner — kubectl --dry-run=client 어댑터.

보안 기준 (NFR-SEC-05):
  - subprocess.run은 반드시 shell=False
  - cmd는 list[str] 형태 argv (문자열 금지)
  - allowlist: ["kubectl", "apply", "--dry-run=client", "-f", <manifest_dir>]
    이 외에 어떤 인자도 추가하지 않음

기능 기준:
  - F-05: kubectl apply --dry-run=client 실행
  - F-56: kubectl 미설치 시 degraded skip (예외가 아닌 정상 흐름)
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from scripts._shared.errors import KubectlExecutionError
from scripts._shared.types import DryRunResult

_KUBECTL_NOT_INSTALLED_KO = (
    "쿠버네티스 CLI(kubectl)가 설치되어 있지 않아 dry-run 검증을 건너뜀"
)

_TIMEOUT_SECONDS = 10


class KubectlDryRunner:
    """kubectl apply --dry-run=client 어댑터.

    NFR-SEC-05 allowlist:
        ["kubectl", "apply", "--dry-run=client", "-f", <manifest_dir>]
    이 외에 어떤 인자도 추가하지 않는다.
    """

    def __init__(self, kubectl_path: str = "kubectl") -> None:
        """kubectl 실행 파일 경로. 기본 PATH 검색.

        Warning:
            ⚠️ `kubectl_path`는 호출자가 신뢰하는 절대경로 또는 `'kubectl'` 리터럴만
            전달. 사용자 입력을 직접 매핑하지 말 것 — 임의 바이너리 실행 위험.
        """
        self._kubectl_path = kubectl_path

    def is_available(self) -> bool:
        """`shutil.which`로 kubectl 존재 여부 확인. 없으면 False.

        Note:
            버전 확인(>=1.25 권장)은 v0.2+ 백로그 — 현재는 `shutil.which`만 수행.
        """
        return shutil.which(self._kubectl_path) is not None

    def dry_run(self, manifest_dir: Path) -> DryRunResult:
        """kubectl apply --dry-run=client -f {manifest_dir} 실행.

        반드시 --dry-run=client 인자 포함 (NFR-SEC-05).

        타임아웃 10초 — kubectl dry-run은 API 서버 왕복 없이 클라이언트 파싱만
        수행하므로 수 초 내 완료 예상.

        Returns:
            DryRunResult:
              - 미설치 시: skipped=True, success=True (degraded),
                           stdout/stderr/exit_code = None,
                           skip_reason_ko = 한국어 메시지
              - 실행 성공 (exit 0): success=True, skipped=False, 필드 채움
              - 실행 실패 (exit != 0): success=False, skipped=False, 필드 채움

        Raises:
            KubectlExecutionError: manifest_dir이 유효하지 않거나, kubectl은 있으나
                실행 자체 실패 (OSError, TimeoutExpired 등).
                미설치는 예외가 아닌 skipped=True 정상 흐름.
        """
        if not manifest_dir.is_dir():
            raise KubectlExecutionError(
                f"manifest_dir이 유효한 디렉토리가 아님: {manifest_dir.name}"
            )
        # resolve()로 절대경로화 → '-'로 시작하는 경로가 kubectl flag로 재해석되는 것 방지
        manifest_dir = manifest_dir.resolve()

        if not self.is_available():
            return DryRunResult(
                success=True,
                stdout=None,
                stderr=None,
                exit_code=None,
                skipped=True,
                skip_reason_ko=_KUBECTL_NOT_INSTALLED_KO,
            )

        cmd = self._build_command(manifest_dir)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="replace",
                shell=False,
                timeout=_TIMEOUT_SECONDS,
            )
        except OSError as exc:
            raise KubectlExecutionError(
                f"kubectl 실행 중 오류 발생: {exc}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise KubectlExecutionError(
                f"kubectl 실행 시간 초과 ({_TIMEOUT_SECONDS}초)"
            ) from exc

        return DryRunResult(
            success=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
            skipped=False,
            skip_reason_ko=None,
        )

    def _build_command(self, manifest_dir: Path) -> list[str]:
        """allowlist 준수 커맨드 빌드.

        반드시 이 정확한 인자만:
            [kubectl_path, "apply", "--dry-run=client", "-f", str(manifest_dir)]

        --server-side / --force / -o yaml 등 추가 인자 금지 (NFR-SEC-05).
        """
        return [
            self._kubectl_path,
            "apply",
            "--dry-run=client",
            "-f",
            str(manifest_dir),
        ]
