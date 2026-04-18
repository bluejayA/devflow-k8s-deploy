"""KubectlDryRunner (kubectl_dry_runner.py) 단위 테스트.

TDD: 이 파일의 모든 테스트가 먼저 실패한 뒤 구현으로 통과시킨다.

보안 기준 (NFR-SEC-05):
  - subprocess.run은 반드시 shell=False
  - cmd는 list[str] 형태 (문자열 금지)
  - allowlist: ["kubectl", "apply", "--dry-run=client", "-f", <manifest_dir>] 정확히 이것만
  - 추가 인자 주입 불가

기능 기준:
  - F-05: kubectl apply --dry-run=client 실행
  - F-56: kubectl 미설치 시 degraded skip (예외 아님)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts._shared.errors import KubectlExecutionError
from scripts._shared.types import DryRunResult
from scripts.kubectl_dry_runner import KubectlDryRunner

# ─── 픽스처 ────────────────────────────────────────────────────────────────


@pytest.fixture
def runner() -> KubectlDryRunner:
    """기본 KubectlDryRunner 인스턴스."""
    return KubectlDryRunner()


@pytest.fixture
def manifest_dir(tmp_path: Path) -> Path:
    """임시 매니페스트 디렉토리."""
    return tmp_path / "manifests"


# ─── is_available ──────────────────────────────────────────────────────────


class TestIsAvailable:
    def test_returns_true_when_kubectl_found(self, runner: KubectlDryRunner) -> None:
        """shutil.which가 경로를 반환하면 True."""
        with patch("shutil.which", return_value="/usr/local/bin/kubectl"):
            assert runner.is_available() is True

    def test_returns_false_when_kubectl_not_found(
        self, runner: KubectlDryRunner
    ) -> None:
        """shutil.which가 None을 반환하면 False."""
        with patch("shutil.which", return_value=None):
            assert runner.is_available() is False


# ─── dry_run — degraded skip ──────────────────────────────────────────────


class TestDryRunDegraded:
    def test_skipped_true_when_kubectl_not_installed(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """kubectl 미설치 시 skipped=True, success=True (degraded 정상 흐름)."""
        with patch.object(runner, "is_available", return_value=False):
            result = runner.dry_run(manifest_dir)

        assert result.skipped is True
        assert result.success is True

    def test_none_fields_when_skipped(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """degraded 시 stdout/stderr/exit_code는 모두 None."""
        with patch.object(runner, "is_available", return_value=False):
            result = runner.dry_run(manifest_dir)

        assert result.stdout is None
        assert result.stderr is None
        assert result.exit_code is None

    def test_skip_reason_ko_contains_kubectl_term(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """skip_reason_ko가 'kubectl' 또는 '쿠버네티스'를 포함하는 한국어 메시지."""
        with patch.object(runner, "is_available", return_value=False):
            result = runner.dry_run(manifest_dir)

        assert result.skip_reason_ko is not None
        # 'kubectl' 또는 '쿠버네티스' 중 하나 이상 포함
        lower = result.skip_reason_ko.lower()
        assert "kubectl" in lower or "쿠버네티스" in lower, (
            f"skip_reason_ko must mention kubectl or 쿠버네티스, got: {result.skip_reason_ko}"
        )

    def test_skip_reason_ko_returns_dryrundresult_type(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """반환값은 DryRunResult 타입."""
        with patch.object(runner, "is_available", return_value=False):
            result = runner.dry_run(manifest_dir)

        assert isinstance(result, DryRunResult)


# ─── dry_run — 실행 성공 ──────────────────────────────────────────────────


class TestDryRunSuccess:
    def test_success_true_on_exit_0(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """exit code 0 → success=True, skipped=False."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "deployment.apps/app dry-run'ed"
        mock_proc.stderr = ""

        with patch.object(runner, "is_available", return_value=True):
            with patch("subprocess.run", return_value=mock_proc):
                result = runner.dry_run(manifest_dir)

        assert result.success is True
        assert result.skipped is False

    def test_stdout_populated_on_success(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """성공 시 stdout이 채워짐."""
        expected_stdout = "deployment.apps/app dry-run'ed"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = expected_stdout
        mock_proc.stderr = ""

        with patch.object(runner, "is_available", return_value=True):
            with patch("subprocess.run", return_value=mock_proc):
                result = runner.dry_run(manifest_dir)

        assert result.stdout == expected_stdout
        assert result.exit_code == 0

    def test_skip_reason_ko_is_none_on_success(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """성공 시 skip_reason_ko는 None."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "ok"
        mock_proc.stderr = ""

        with patch.object(runner, "is_available", return_value=True):
            with patch("subprocess.run", return_value=mock_proc):
                result = runner.dry_run(manifest_dir)

        assert result.skip_reason_ko is None


# ─── dry_run — 실행 실패 ──────────────────────────────────────────────────


class TestDryRunFailure:
    def test_success_false_on_nonzero_exit(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """exit code 1 → success=False."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "error: the server could not find the requested resource"

        with patch.object(runner, "is_available", return_value=True):
            with patch("subprocess.run", return_value=mock_proc):
                result = runner.dry_run(manifest_dir)

        assert result.success is False
        assert result.skipped is False

    def test_stderr_populated_on_failure(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """실패 시 stderr/exit_code가 채워짐."""
        expected_stderr = "error: the server could not find the requested resource"
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = expected_stderr

        with patch.object(runner, "is_available", return_value=True):
            with patch("subprocess.run", return_value=mock_proc):
                result = runner.dry_run(manifest_dir)

        assert result.stderr == expected_stderr
        assert result.exit_code == 1


# ─── dry_run — 예외 처리 ──────────────────────────────────────────────────


class TestDryRunExceptions:
    def test_permission_error_raises_kubectl_execution_error(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """kubectl은 있으나 PermissionError → KubectlExecutionError."""
        with patch.object(runner, "is_available", return_value=True):
            with patch("subprocess.run", side_effect=PermissionError("permission denied")):
                with pytest.raises(KubectlExecutionError):
                    runner.dry_run(manifest_dir)

    def test_timeout_raises_kubectl_execution_error(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """subprocess.TimeoutExpired → KubectlExecutionError."""
        with patch.object(runner, "is_available", return_value=True):
            with patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["kubectl"], timeout=60),
            ):
                with pytest.raises(KubectlExecutionError):
                    runner.dry_run(manifest_dir)


# ─── _build_command — allowlist ──────────────────────────────────────────


class TestBuildCommand:
    def test_build_command_exact_allowlist(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """_build_command 결과가 정확히 allowlist와 일치."""
        cmd = runner._build_command(manifest_dir)
        expected = ["kubectl", "apply", "--dry-run=client", "-f", str(manifest_dir)]
        assert cmd == expected

    def test_build_command_with_custom_kubectl_path(
        self, manifest_dir: Path
    ) -> None:
        """custom kubectl_path 사용 시 첫 인자가 custom 경로."""
        custom_runner = KubectlDryRunner("/custom/kubectl")
        cmd = custom_runner._build_command(manifest_dir)
        expected = [
            "/custom/kubectl",
            "apply",
            "--dry-run=client",
            "-f",
            str(manifest_dir),
        ]
        assert cmd == expected

    def test_build_command_length_is_five(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """추가 인자 없이 정확히 5개 인자만 존재 (allowlist 외 인자 금지)."""
        cmd = runner._build_command(manifest_dir)
        assert len(cmd) == 5

    def test_build_command_no_server_side_flag(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """--server-side 플래그가 포함되지 않음."""
        cmd = runner._build_command(manifest_dir)
        assert "--server-side" not in cmd

    def test_build_command_no_force_flag(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """--force 플래그가 포함되지 않음."""
        cmd = runner._build_command(manifest_dir)
        assert "--force" not in cmd

    def test_build_command_dry_run_client_present(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """--dry-run=client 인자가 반드시 포함됨 (NFR-SEC-05)."""
        cmd = runner._build_command(manifest_dir)
        assert "--dry-run=client" in cmd


# ─── 보안: subprocess 호출 방식 ──────────────────────────────────────────


class TestSecurityConstraints:
    def test_subprocess_called_with_shell_false(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """subprocess.run은 반드시 shell=False로 호출됨 (NFR-SEC-05)."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with patch.object(runner, "is_available", return_value=True):
            with patch("subprocess.run", return_value=mock_proc) as mock_run:
                runner.dry_run(manifest_dir)

        call_kwargs = mock_run.call_args.kwargs
        # shell이 전달되지 않거나 False여야 함
        shell_value = call_kwargs.get("shell", False)
        assert shell_value is False, f"shell must be False, got {shell_value}"

    def test_subprocess_first_arg_is_list(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """subprocess.run의 첫 번째 positional 인자는 list (문자열 금지)."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with patch.object(runner, "is_available", return_value=True):
            with patch("subprocess.run", return_value=mock_proc) as mock_run:
                runner.dry_run(manifest_dir)

        first_arg = mock_run.call_args.args[0]
        assert isinstance(first_arg, list), (
            f"First arg to subprocess.run must be list, got {type(first_arg)}"
        )

    def test_subprocess_env_not_manipulated(
        self, runner: KubectlDryRunner, manifest_dir: Path
    ) -> None:
        """기본 흐름에서 env 인자를 별도 주입하지 않음 (os.environ 기본값 사용)."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        with patch.object(runner, "is_available", return_value=True):
            with patch("subprocess.run", return_value=mock_proc) as mock_run:
                runner.dry_run(manifest_dir)

        call_kwargs = mock_run.call_args.kwargs
        # env 인자가 없거나 None이어야 함 (os.environ 기본값 활용)
        assert "env" not in call_kwargs or call_kwargs["env"] is None, (
            "env must not be explicitly set in default flow"
        )
