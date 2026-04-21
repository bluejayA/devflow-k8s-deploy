"""Unit 12 — BuildRunner TDD 테스트.

테스트 범주:
  - detect_engine: skip/auto/명시 엔진 분기 (7건)
  - build: skip/성공/실패/degraded/타임아웃/검증 (8건)
  - _build_command: allowlist 7요소, push 금지, shell=False spy (3건)
  - 한국어 메시지: skip_reason_ko (4건)
  - F-102 timeout 주입 (3건)
  - BuildResult stdout/stderr/exit_code 캡처 (3건)
  - _build_command engine whitelist (2건)
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts._shared.errors import InvalidImageError
from scripts.pipeline.build_runner import (
    _BUILD_TIMEOUT_SECONDS,
    _MSG_AUTO_NOT_FOUND,
    _MSG_SKIP_MODE,
    BuildRunner,
    _msg_explicit_not_found,
)

# ─── 헬퍼 ───────────────────────────────────────────────────────────────


def _make_runner(engine: str) -> BuildRunner:
    return BuildRunner(build_engine=engine)  # type: ignore[arg-type]


def _fake_which(available: list[str]) -> Callable[[str], str | None]:
    """shutil.which 패치 팩토리 — available 목록에 있으면 경로 반환, 없으면 None."""

    def _which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in available else None

    return _which


# ─── detect_engine ──────────────────────────────────────────────────────


class TestDetectEngine:
    """BuildRunner.detect_engine() 분기 검증."""

    def test_skip_mode_returns_none(self) -> None:
        """TC-1: skip 모드이면 항상 None을 반환해야 한다."""
        runner = _make_runner("skip")
        with patch(
            "scripts.pipeline.build_runner.shutil.which",
            side_effect=_fake_which(["docker"]),
        ):
            assert runner.detect_engine() is None

    def test_auto_mode_docker_only_returns_docker(self) -> None:
        """TC-2: auto + docker만 설치 → 'docker' 반환."""
        runner = _make_runner("auto")
        with patch(
            "scripts.pipeline.build_runner.shutil.which",
            side_effect=_fake_which(["docker"]),
        ):
            assert runner.detect_engine() == "docker"

    def test_auto_mode_docker_and_podman_returns_docker(self) -> None:
        """TC-3: auto + docker/podman 모두 설치 → 우선순위 'docker' 반환."""
        runner = _make_runner("auto")
        with patch(
            "scripts.pipeline.build_runner.shutil.which",
            side_effect=_fake_which(["docker", "podman"]),
        ):
            assert runner.detect_engine() == "docker"

    def test_auto_mode_nerdctl_only_returns_nerdctl(self) -> None:
        """TC-4: auto + nerdctl만 설치 → 'nerdctl' 반환."""
        runner = _make_runner("auto")
        with patch(
            "scripts.pipeline.build_runner.shutil.which",
            side_effect=_fake_which(["nerdctl"]),
        ):
            assert runner.detect_engine() == "nerdctl"

    def test_auto_mode_none_installed_returns_none(self) -> None:
        """TC-5: auto + 전부 미설치 → None 반환."""
        runner = _make_runner("auto")
        with patch("scripts.pipeline.build_runner.shutil.which", return_value=None):
            assert runner.detect_engine() is None

    def test_explicit_docker_installed_returns_docker(self) -> None:
        """TC-6: 명시 docker + docker 설치됨 → 'docker' 반환."""
        runner = _make_runner("docker")
        with patch(
            "scripts.pipeline.build_runner.shutil.which",
            side_effect=_fake_which(["docker"]),
        ):
            assert runner.detect_engine() == "docker"

    def test_explicit_podman_docker_only_returns_none(self) -> None:
        """TC-7: 명시 podman + docker만 설치됨 → None 반환 (명시 엔진 고정)."""
        runner = _make_runner("podman")
        with patch(
            "scripts.pipeline.build_runner.shutil.which",
            side_effect=_fake_which(["docker"]),
        ):
            assert runner.detect_engine() is None


# ─── build ──────────────────────────────────────────────────────────────


class TestBuild:
    """BuildRunner.build() 실행 분기 검증."""

    @pytest.fixture()
    def tmp_ctx(self, tmp_path: Path) -> Path:
        """빌드 컨텍스트 디렉토리 픽스처 (Dockerfile 포함)."""
        (tmp_path / "Dockerfile").write_text("FROM scratch\n")
        return tmp_path

    def test_skip_mode_returns_skipped_true_no_subprocess(self, tmp_ctx: Path) -> None:
        """TC-8: skip 모드 → skipped=True, success=True, subprocess 미호출."""
        runner = _make_runner("skip")
        with patch("scripts.pipeline.build_runner.subprocess.run") as mock_run:
            result = runner.build(tmp_ctx, "myapp:1.0.0")
        assert result.skipped is True
        assert result.success is True
        assert result.engine is None
        mock_run.assert_not_called()

    def test_auto_docker_build_success(self, tmp_ctx: Path) -> None:
        """TC-9: auto + docker 감지 → 빌드 성공, success=True, exit_code=0."""
        runner = _make_runner("auto")
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "Successfully built abc123\n"
        fake_proc.stderr = ""

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch(
                "scripts.pipeline.build_runner.subprocess.run",
                return_value=fake_proc,
            ) as mock_run,
        ):
            result = runner.build(tmp_ctx, "myapp:1.0.0")

        assert result.success is True
        assert result.skipped is False
        assert result.engine == "docker"
        assert result.image_ref == "myapp:1.0.0"
        mock_run.assert_called_once()

    def test_build_failure_returncode_nonzero(self, tmp_ctx: Path) -> None:
        """TC-10: 빌드 실패 (returncode != 0) → success=False."""
        runner = _make_runner("docker")
        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.stdout = ""
        fake_proc.stderr = "Error: no such file"

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch("scripts.pipeline.build_runner.subprocess.run", return_value=fake_proc),
        ):
            result = runner.build(tmp_ctx, "myapp:1.0.0")

        assert result.success is False
        assert result.skipped is False
        assert result.image_ref is None

    def test_auto_engine_not_found_degraded(self, tmp_ctx: Path) -> None:
        """TC-11: auto + 전부 미감지 → skipped=True, skip_reason_ko 한국어, success=True."""
        runner = _make_runner("auto")
        with patch("scripts.pipeline.build_runner.shutil.which", return_value=None):
            result = runner.build(tmp_ctx, "myapp:1.0.0")

        assert result.skipped is True
        assert result.success is True
        assert result.skip_reason_ko is not None
        assert "docker" in result.skip_reason_ko or "엔진" in result.skip_reason_ko

    def test_explicit_engine_not_found_degraded(self, tmp_ctx: Path) -> None:
        """TC-12: 명시 엔진 미감지 → skipped=True."""
        runner = _make_runner("podman")
        with patch("scripts.pipeline.build_runner.shutil.which", return_value=None):
            result = runner.build(tmp_ctx, "myapp:1.0.0")

        assert result.skipped is True
        assert result.success is True
        assert result.skip_reason_ko is not None

    def test_timeout_returns_failure_not_exception(self, tmp_ctx: Path) -> None:
        """TC-13: 타임아웃 → success=False, skip_reason_ko에 '타임아웃' 포함."""
        runner = _make_runner("docker")

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch(
                "scripts.pipeline.build_runner.subprocess.run",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["docker", "build"], timeout=600
                ),
            ),
        ):
            result = runner.build(tmp_ctx, "myapp:1.0.0")

        assert result.success is False
        assert result.skipped is False
        assert result.skip_reason_ko is not None
        assert "타임아웃" in result.skip_reason_ko

    def test_image_tag_latest_raises_invalid_image_error(self, tmp_ctx: Path) -> None:
        """TC-14: image_tag='latest' → InvalidImageError (F-23)."""
        runner = _make_runner("docker")
        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            pytest.raises(InvalidImageError),
        ):
            runner.build(tmp_ctx, "myapp:latest")

    def test_context_dir_not_exists_raises_value_error(self, tmp_path: Path) -> None:
        """TC-15: context_dir 존재하지 않음 → ValueError."""
        runner = _make_runner("docker")
        nonexistent = tmp_path / "nonexistent_dir"

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            pytest.raises(ValueError, match="context_dir"),
        ):
            runner.build(nonexistent, "myapp:1.0.0")


# ─── _build_command (allowlist) ─────────────────────────────────────────


class TestBuildCommand:
    """BuildRunner._build_command() allowlist 검증."""

    @pytest.fixture()
    def runner(self) -> BuildRunner:
        return _make_runner("docker")

    @pytest.fixture()
    def tmp_ctx(self, tmp_path: Path) -> Path:
        (tmp_path / "Dockerfile").write_text("FROM scratch\n")
        return tmp_path

    def test_cmd_exactly_seven_elements(
        self, runner: BuildRunner, tmp_ctx: Path
    ) -> None:
        """TC-16: cmd 정확히 7개 요소: [engine, 'build', '-t', tag, '-f', dockerfile, context]."""
        dockerfile = tmp_ctx / "Dockerfile"
        cmd = runner._build_command("docker", tmp_ctx, "myapp:1.0.0", dockerfile)
        assert len(cmd) == 7
        assert cmd[0] == "docker"
        assert cmd[1] == "build"
        assert cmd[2] == "-t"
        assert cmd[3] == "myapp:1.0.0"
        assert cmd[4] == "-f"
        assert cmd[5] == str(dockerfile)
        assert cmd[6] == str(tmp_ctx)

    def test_push_related_tokens_absent(
        self, runner: BuildRunner, tmp_ctx: Path
    ) -> None:
        """TC-17: push/pull 관련 토큰이 cmd에 절대 없어야 함."""
        dockerfile = tmp_ctx / "Dockerfile"
        cmd = runner._build_command("docker", tmp_ctx, "myapp:1.0.0", dockerfile)
        forbidden_tokens = {"push", "pull", "--push", "--pull"}
        for token in cmd:
            assert token not in forbidden_tokens, f"금지 토큰 발견: {token!r}"

    def test_subprocess_run_called_with_shell_false(self, tmp_ctx: Path) -> None:
        """TC-18: subprocess.run이 shell=False로 호출되는지 검증."""
        runner = _make_runner("docker")
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch(
                "scripts.pipeline.build_runner.subprocess.run",
                return_value=fake_proc,
            ) as mock_run,
        ):
            runner.build(tmp_ctx, "myapp:1.0.0")

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("shell") is False


# ─── 한국어 메시지 ───────────────────────────────────────────────────────


class TestKoreanMessages:
    """skip_reason_ko 한국어 메시지 검증."""

    def test_skip_reason_ko_contains_korean(self) -> None:
        """TC-19: 모든 skip_reason_ko는 한국어(가-힣 포함)를 포함해야 한다."""
        import re

        ko_pattern = re.compile(r"[가-힣]")

        messages = [
            _MSG_SKIP_MODE,
            _MSG_AUTO_NOT_FOUND,
            _msg_explicit_not_found("podman"),
        ]
        for msg in messages:
            assert ko_pattern.search(msg), f"한국어 없음: {msg!r}"

    def test_skip_mode_message_mentions_engine_skip(self) -> None:
        """TC-19b: skip 모드 메시지에 'build.engine=skip' 언급 필수."""
        assert "build.engine=skip" in _MSG_SKIP_MODE

    def test_explicit_not_found_message_contains_engine_name(self) -> None:
        """TC-19c: 명시 엔진 미감지 메시지에 엔진 이름 포함."""
        msg = _msg_explicit_not_found("nerdctl")
        assert "nerdctl" in msg

    def test_timeout_message_contains_seconds(self) -> None:
        """TC-19d: 타임아웃 시 BuildResult.skip_reason_ko에 초 단위 언급."""
        runner = _make_runner("docker")

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch(
                "scripts.pipeline.build_runner.subprocess.run",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["docker", "build"], timeout=600
                ),
            ),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "resolve", return_value=Path("/tmp")),
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "relative_to", return_value=Path("Dockerfile")),
        ):
            result = runner.build(Path("/tmp"), "myapp:1.0.0")

        assert result.skip_reason_ko is not None
        assert str(_BUILD_TIMEOUT_SECONDS) in result.skip_reason_ko


# ─── F-102 timeout 주입 ──────────────────────────────────────────────────


class TestTimeoutInjection:
    """BuildRunner.__init__ build_timeout_seconds 파라미터 검증."""

    @pytest.fixture()
    def tmp_ctx(self, tmp_path: Path) -> Path:
        (tmp_path / "Dockerfile").write_text("FROM scratch\n")
        return tmp_path

    def test_timeout_custom_value(self, tmp_ctx: Path) -> None:
        """TC-20: build_timeout_seconds=30 → subprocess.run에 timeout=30 전달."""
        runner = BuildRunner(build_engine="docker", build_timeout_seconds=30)
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch(
                "scripts.pipeline.build_runner.subprocess.run",
                return_value=fake_proc,
            ) as mock_run,
        ):
            runner.build(tmp_ctx, "myapp:1.0.0")

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("timeout") == 30

    def test_timeout_zero_means_unlimited(self, tmp_ctx: Path) -> None:
        """TC-21: build_timeout_seconds=0 → subprocess.run에 timeout=None 전달."""
        runner = BuildRunner(build_engine="docker", build_timeout_seconds=0)
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch(
                "scripts.pipeline.build_runner.subprocess.run",
                return_value=fake_proc,
            ) as mock_run,
        ):
            runner.build(tmp_ctx, "myapp:1.0.0")

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("timeout") is None

    def test_timeout_negative_raises_value_error(self) -> None:
        """TC-22: build_timeout_seconds=-1 → ValueError."""
        with pytest.raises(ValueError, match="build_timeout_seconds"):
            BuildRunner(build_engine="docker", build_timeout_seconds=-1)


# ─── BuildResult stdout/stderr/exit_code 캡처 ──────────────────────────


class TestBuildResultCapture:
    """BuildResult stdout/stderr/exit_code 신규 필드 검증."""

    @pytest.fixture()
    def tmp_ctx(self, tmp_path: Path) -> Path:
        (tmp_path / "Dockerfile").write_text("FROM scratch\n")
        return tmp_path

    def test_build_success_captures_stdout_stderr_exit_code(
        self, tmp_ctx: Path
    ) -> None:
        """TC-23: 성공 시 stdout/stderr/exit_code 필드가 채워져야 한다."""
        runner = _make_runner("docker")
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "Successfully built abc123\n"
        fake_proc.stderr = ""

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch(
                "scripts.pipeline.build_runner.subprocess.run",
                return_value=fake_proc,
            ),
        ):
            result = runner.build(tmp_ctx, "myapp:1.0.0")

        assert result.stdout == "Successfully built abc123\n"
        assert result.stderr == ""
        assert result.exit_code == 0

    def test_build_failure_captures_stderr(self, tmp_ctx: Path) -> None:
        """TC-24: 실패 시 stderr/exit_code가 채워져야 한다."""
        runner = _make_runner("docker")
        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.stdout = ""
        fake_proc.stderr = "Error: no such file"

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch(
                "scripts.pipeline.build_runner.subprocess.run",
                return_value=fake_proc,
            ),
        ):
            result = runner.build(tmp_ctx, "myapp:1.0.0")

        assert result.success is False
        assert result.stderr == "Error: no such file"
        assert result.exit_code == 1

    def test_timeout_captures_partial_output(self, tmp_ctx: Path) -> None:
        """TC-25: TimeoutExpired에 stdout/stderr 있으면 BuildResult에 채워져야 한다."""
        runner = _make_runner("docker")

        exc = subprocess.TimeoutExpired(cmd=["docker", "build"], timeout=600)
        exc.stdout = b"partial output"
        exc.stderr = b"some error"

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch(
                "scripts.pipeline.build_runner.subprocess.run",
                side_effect=exc,
            ),
        ):
            result = runner.build(tmp_ctx, "myapp:1.0.0")

        assert result.success is False
        assert result.stdout == "partial output"
        assert result.stderr == "some error"
        assert result.exit_code is None


# ─── TimeoutExpired str output (text=True) 방어 ─────────────────────────


class TestTimeoutStrOutput:
    """TC-28: subprocess.run(text=True) 시 TimeoutExpired.stdout/stderr가 str인 경우 방어."""

    @pytest.fixture()
    def tmp_ctx(self, tmp_path: Path) -> Path:
        (tmp_path / "Dockerfile").write_text("FROM scratch\n")
        return tmp_path

    def test_timeout_with_str_output_handles_gracefully(self, tmp_ctx: Path) -> None:
        """TC-28: text=True → TimeoutExpired.stdout/stderr가 str일 때 AttributeError 없이 처리."""
        runner = _make_runner("docker")

        exc = subprocess.TimeoutExpired(cmd=["docker", "build"], timeout=600)
        # text=True 모드에서는 stdout/stderr가 str로 제공됨
        exc.stdout = "partial output str"
        exc.stderr = "partial err str"

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch(
                "scripts.pipeline.build_runner.subprocess.run",
                side_effect=exc,
            ),
        ):
            result = runner.build(tmp_ctx, "myapp:1.0.0")

        assert result.success is False
        assert result.stdout == "partial output str"
        assert result.stderr == "partial err str"
        assert result.exit_code is None

    def test_timeout_with_none_output_returns_none_fields(self, tmp_ctx: Path) -> None:
        """TC-29: TimeoutExpired.stdout/stderr=None → BuildResult에 None."""
        runner = _make_runner("docker")

        exc = subprocess.TimeoutExpired(cmd=["docker", "build"], timeout=600)
        exc.stdout = None
        exc.stderr = None

        with (
            patch(
                "scripts.pipeline.build_runner.shutil.which",
                side_effect=_fake_which(["docker"]),
            ),
            patch(
                "scripts.pipeline.build_runner.subprocess.run",
                side_effect=exc,
            ),
        ):
            result = runner.build(tmp_ctx, "myapp:1.0.0")

        assert result.success is False
        assert result.stdout is None
        assert result.stderr is None


# ─── _build_command engine whitelist ────────────────────────────────────


class TestBuildCommandWhitelist:
    """_build_command engine whitelist assert 검증."""

    @pytest.fixture()
    def runner(self) -> BuildRunner:
        return _make_runner("docker")

    @pytest.fixture()
    def tmp_ctx(self, tmp_path: Path) -> Path:
        (tmp_path / "Dockerfile").write_text("FROM scratch\n")
        return tmp_path

    def test_build_command_rejects_unknown_engine(
        self, runner: BuildRunner, tmp_ctx: Path
    ) -> None:
        """TC-26: 허용되지 않은 엔진으로 _build_command 호출 시 ValueError."""
        with pytest.raises(ValueError, match="허용되지 않은 엔진"):
            runner._build_command("evil-engine", tmp_ctx, "myapp:1.0.0", tmp_ctx / "Dockerfile")  # type: ignore[arg-type]

    def test_build_command_length_invariant(
        self, runner: BuildRunner, tmp_ctx: Path
    ) -> None:
        """TC-27: _build_command 결과는 정확히 7 요소."""
        dockerfile = tmp_ctx / "Dockerfile"
        cmd = runner._build_command("docker", tmp_ctx, "myapp:1.0.0", dockerfile)
        assert len(cmd) == 7
