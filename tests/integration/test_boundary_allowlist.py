"""NFR-SEC-05 경계 allowlist CI 감지 테스트.

이 테스트는 `subprocess.run`을 monkeypatch하여
kubectl_dry_runner / build_runner의 실행 argv를 기록하고 다음을 검증:

1. shell=True 금지
2. argv는 list (str/tuple 아님)
3. 인젝션 토큰 부재 (;, &&, ||, |, `, $(, ${, >, <, >>, <<, \\n, \\r, \\x00)
4. 정확한 토큰 위치 (argv[0]은 실행 파일명, 나머지 인자는 고정 순서)

실패 조건:
- kubectl에 `--dry-run=client`, `--validate=false` 외 위험 인자 추가
  (kubectl apply --force, --server-side 등)
- docker/podman/nerdctl에 push/pull/--push/--pull 등 추가
- shell=True 전환
- argv를 str로 바꿈

kubectl allowlist (6-tuple):
    ["kubectl", "apply", "--dry-run=client", "--validate=false", "-f", <manifest_dir>]
--validate=false: cluster-less 동작 — K8sValidator가 규칙 검증 담당.

픽스처 자체 검증 테스트도 포함 (픽스처가 실제로 금지 케이스를 잡는지).

subprocess_spy 픽스처는 tests/integration/conftest.py에서 autouse로 주입됨.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.kubectl_dry_runner import KubectlDryRunner
from scripts.pipeline.build_runner import BuildRunner
from tests.integration.conftest import SubprocessSpy

# 인젝션 토큰 블랙리스트
_INJECTION_TOKENS = (
    ";",
    "&&",
    "||",
    "|",
    "`",
    "$(",
    "${",  # command/variable substitution
    ">",
    "<",
    ">>",
    "<<",  # redirection
    "\n",
    "\r",
    "\x00",  # 개행/NUL 인젝션
)


def _assert_safe_cmd(cmd: object, shell: bool) -> None:
    """보안 검증:
    1. shell=False
    2. cmd가 list[str]
    3. 각 인자에 인젝션 토큰 없음
    """
    assert shell is False, f"shell=True 금지: {cmd}"
    assert isinstance(cmd, list), f"cmd는 list여야 함: type={type(cmd)}"
    assert all(isinstance(arg, str) for arg in cmd), f"cmd 원소는 str이어야 함: {cmd}"

    # 인젝션 토큰 위치 매칭 (arg 전체 포함 여부)
    for arg in cmd:
        for token in _INJECTION_TOKENS:
            assert token not in arg, (
                f"인젝션 토큰 '{token}' 포함: {arg!r} in cmd={cmd}"
            )


# ============================================================
# KubectlDryRunner 테스트
# ============================================================


class TestKubectlDryRunnerAllowlist:
    def test_dry_run_uses_list_argv(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """subprocess.run에 list argv가 전달됨 (NFR-SEC-05)."""
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        (manifest_dir / "deploy.yaml").write_text("apiVersion: v1\n")

        monkeypatch.setattr(
            "scripts.kubectl_dry_runner.shutil.which",
            lambda _x: "/usr/bin/kubectl",
        )

        runner = KubectlDryRunner()
        runner.dry_run(manifest_dir)

        assert len(subprocess_spy.calls) == 1
        call = subprocess_spy.calls[0]
        _assert_safe_cmd(call["cmd"], call["shell"])

    def test_dry_run_argv_exactly_six_elements(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """정확히 6개: [kubectl, apply, --dry-run=client, --validate=false, -f, path]."""
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()

        monkeypatch.setattr(
            "scripts.kubectl_dry_runner.shutil.which",
            lambda _x: "/usr/bin/kubectl",
        )

        runner = KubectlDryRunner()
        runner.dry_run(manifest_dir)

        cmd = subprocess_spy.calls[0]["cmd"]
        assert len(cmd) == 6, f"argv는 정확히 6개여야 함, got {len(cmd)}: {cmd}"

    def test_dry_run_includes_validate_false(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """argv에 `--validate=false` 포함 (cluster-less dry-run 허용).

        --validate=false: cluster 없이 client-side 파싱만 수행.
        K8sValidator가 규칙 검증 담당 (중복 방지).
        """
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()

        monkeypatch.setattr(
            "scripts.kubectl_dry_runner.shutil.which",
            lambda _x: "/usr/bin/kubectl",
        )

        runner = KubectlDryRunner()
        runner.dry_run(manifest_dir)

        cmd = subprocess_spy.calls[0]["cmd"]
        assert "--validate=false" in cmd, f"--validate=false 누락: {cmd}"

    def test_dry_run_includes_dry_run_client(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """argv에 `--dry-run=client` 포함 (allowlist 핵심)."""
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()

        monkeypatch.setattr(
            "scripts.kubectl_dry_runner.shutil.which",
            lambda _x: "/usr/bin/kubectl",
        )

        runner = KubectlDryRunner()
        runner.dry_run(manifest_dir)

        cmd = subprocess_spy.calls[0]["cmd"]
        assert "--dry-run=client" in cmd, f"--dry-run=client 누락: {cmd}"

    def test_dry_run_argv_position_kubectl_is_first(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """argv[0]은 반드시 kubectl (실행 파일명 위치 고정)."""
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()

        monkeypatch.setattr(
            "scripts.kubectl_dry_runner.shutil.which",
            lambda _x: "/usr/bin/kubectl",
        )

        runner = KubectlDryRunner()
        runner.dry_run(manifest_dir)

        cmd = subprocess_spy.calls[0]["cmd"]
        assert cmd[0] == "kubectl", f"argv[0]은 kubectl이어야 함, got {cmd[0]}"

    def test_dry_run_excludes_force_flag(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`--force` 플래그가 argv에 없음 (allowlist 위반 방지)."""
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()

        monkeypatch.setattr(
            "scripts.kubectl_dry_runner.shutil.which",
            lambda _x: "/usr/bin/kubectl",
        )

        runner = KubectlDryRunner()
        runner.dry_run(manifest_dir)

        cmd = subprocess_spy.calls[0]["cmd"]
        assert "--force" not in cmd
        assert "-f" in cmd  # -f는 파일 지정용으로 정상 포함

    def test_dry_run_excludes_server_side_flag(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`--server-side` 플래그가 argv에 없음."""
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()

        monkeypatch.setattr(
            "scripts.kubectl_dry_runner.shutil.which",
            lambda _x: "/usr/bin/kubectl",
        )

        runner = KubectlDryRunner()
        runner.dry_run(manifest_dir)

        cmd = subprocess_spy.calls[0]["cmd"]
        assert "--server-side" not in cmd

    def test_dry_run_excludes_delete_and_create_verbs(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`delete`/`create` 서브커맨드가 없음 (apply only)."""
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()

        monkeypatch.setattr(
            "scripts.kubectl_dry_runner.shutil.which",
            lambda _x: "/usr/bin/kubectl",
        )

        runner = KubectlDryRunner()
        runner.dry_run(manifest_dir)

        cmd = subprocess_spy.calls[0]["cmd"]
        assert "delete" not in cmd
        assert "create" not in cmd
        assert "apply" in cmd

    def test_dry_run_excludes_dangerous_verbs(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """kubectl apply 외 금지 verb(replace/rollout/scale/edit/patch/delete/create)가 argv에 없음.

        NFR-SEC-05 원문 금지 verb 7종 전수 검증 (allowlist의 스펙 준수도).
        """
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()

        monkeypatch.setattr(
            "scripts.kubectl_dry_runner.shutil.which",
            lambda _x: "/usr/bin/kubectl",
        )

        runner = KubectlDryRunner()
        runner.dry_run(manifest_dir)

        cmd = subprocess_spy.calls[0]["cmd"]
        forbidden_verbs = {"replace", "rollout", "scale", "edit", "patch", "delete", "create"}
        for verb in forbidden_verbs:
            assert verb not in cmd, f"금지 verb '{verb}' 포함: {cmd}"
        # allowlist 확인: cmd[1]은 "apply"만
        assert cmd[1] == "apply"


# ============================================================
# BuildRunner 테스트
# ============================================================


class TestBuildRunnerAllowlist:
    def test_build_uses_list_argv_docker(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """docker 엔진 — subprocess.run에 list argv가 전달됨."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch\n")

        monkeypatch.setattr(
            "scripts.pipeline.build_runner.shutil.which",
            lambda _x: "/usr/bin/docker",
        )

        runner = BuildRunner("docker")
        runner.build(tmp_path, "myapp:1.0", dockerfile=dockerfile)

        assert len(subprocess_spy.calls) == 1
        call = subprocess_spy.calls[0]
        _assert_safe_cmd(call["cmd"], call["shell"])

    def test_build_argv_exactly_seven_elements(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """[engine, build, -t, tag, -f, dockerfile, context] — 정확히 7개."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch\n")

        monkeypatch.setattr(
            "scripts.pipeline.build_runner.shutil.which",
            lambda _x: "/usr/bin/docker",
        )

        runner = BuildRunner("docker")
        runner.build(tmp_path, "myapp:1.0", dockerfile=dockerfile)

        cmd = subprocess_spy.calls[0]["cmd"]
        assert len(cmd) == 7, f"argv는 정확히 7개여야 함, got {len(cmd)}: {cmd}"

    def test_build_excludes_push(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`push` 서브커맨드/--push 플래그가 argv에 없음 (generate-only 경계).

        경로 인자에 "push" 문자열이 우연히 포함될 수 있으므로
        정확히 "push" 토큰 또는 "--push" 플래그 존재 여부만 검사.
        """
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch\n")

        monkeypatch.setattr(
            "scripts.pipeline.build_runner.shutil.which",
            lambda _x: "/usr/bin/docker",
        )

        runner = BuildRunner("docker")
        runner.build(tmp_path, "myapp:1.0", dockerfile=dockerfile)

        cmd = subprocess_spy.calls[0]["cmd"]
        # 정확한 "push" 서브커맨드 또는 "--push" 플래그 금지
        assert "push" not in cmd, f"push 서브커맨드 발견: {cmd}"
        assert "--push" not in cmd, f"--push 플래그 발견: {cmd}"

    def test_build_excludes_pull(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`pull` 관련 인자가 argv에 없음."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch\n")

        monkeypatch.setattr(
            "scripts.pipeline.build_runner.shutil.which",
            lambda _x: "/usr/bin/docker",
        )

        runner = BuildRunner("docker")
        runner.build(tmp_path, "myapp:1.0", dockerfile=dockerfile)

        cmd = subprocess_spy.calls[0]["cmd"]
        for arg in cmd:
            assert "--pull" not in arg, f"--pull 관련 인자 발견: {arg!r}"

    def test_build_argv_position_engine_is_first(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """argv[0]은 엔진명 (docker), argv[1]은 build."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch\n")

        monkeypatch.setattr(
            "scripts.pipeline.build_runner.shutil.which",
            lambda _x: "/usr/bin/docker",
        )

        runner = BuildRunner("docker")
        runner.build(tmp_path, "myapp:1.0", dockerfile=dockerfile)

        cmd = subprocess_spy.calls[0]["cmd"]
        assert cmd[0] == "docker", f"argv[0]은 엔진명이어야 함, got {cmd[0]}"
        assert cmd[1] == "build", f"argv[1]은 'build'여야 함, got {cmd[1]}"

    def test_build_podman_uses_list_argv(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """podman 엔진 — 동일 allowlist 보장."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch\n")

        monkeypatch.setattr(
            "scripts.pipeline.build_runner.shutil.which",
            lambda _x: "/usr/bin/podman",
        )

        runner = BuildRunner("podman")
        runner.build(tmp_path, "myapp:1.0", dockerfile=dockerfile)

        assert len(subprocess_spy.calls) == 1
        call = subprocess_spy.calls[0]
        _assert_safe_cmd(call["cmd"], call["shell"])
        assert call["cmd"][0] == "podman"

    def test_build_nerdctl_uses_list_argv(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """nerdctl 엔진 — 동일 allowlist 보장."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch\n")

        monkeypatch.setattr(
            "scripts.pipeline.build_runner.shutil.which",
            lambda _x: "/usr/bin/nerdctl",
        )

        runner = BuildRunner("nerdctl")
        runner.build(tmp_path, "myapp:1.0", dockerfile=dockerfile)

        assert len(subprocess_spy.calls) == 1
        call = subprocess_spy.calls[0]
        _assert_safe_cmd(call["cmd"], call["shell"])
        assert call["cmd"][0] == "nerdctl"

    def test_build_skip_mode_does_not_call_subprocess(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
    ) -> None:
        """skip 모드에서는 subprocess.run을 전혀 호출하지 않음."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch\n")

        runner = BuildRunner("skip")
        result = runner.build(tmp_path, "myapp:1.0", dockerfile=dockerfile)

        assert len(subprocess_spy.calls) == 0, "skip 모드에서 subprocess 호출 금지"
        assert result.skipped is True

    def test_build_auto_engine_all_seven_elements(
        self,
        subprocess_spy: SubprocessSpy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """auto 엔진 감지(docker 선택) — argv 7개 allowlist 동일."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch\n")

        monkeypatch.setattr(
            "scripts.pipeline.build_runner.shutil.which",
            lambda x: "/usr/bin/docker" if x == "docker" else None,
        )

        runner = BuildRunner("auto")
        runner.build(tmp_path, "myapp:1.0", dockerfile=dockerfile)

        assert len(subprocess_spy.calls) == 1
        cmd = subprocess_spy.calls[0]["cmd"]
        assert len(cmd) == 7
        assert cmd[0] == "docker"
        _assert_safe_cmd(cmd, subprocess_spy.calls[0]["shell"])


# ============================================================
# 픽스처 자체 검증 (§C 요구: "픽스처 자체 검증 테스트 의무")
# ============================================================


class TestFixtureSelfCheck:
    def test_assert_safe_cmd_rejects_shell_true(self) -> None:
        """shell=True이면 assertion 실패."""
        with pytest.raises(AssertionError, match="shell=True"):
            _assert_safe_cmd(["echo"], shell=True)

    def test_assert_safe_cmd_rejects_string_cmd(self) -> None:
        """cmd가 str이면 실패."""
        with pytest.raises(AssertionError, match="list"):
            _assert_safe_cmd("echo hi", shell=False)

    def test_assert_safe_cmd_rejects_injection_semicolon(self) -> None:
        """세미콜론(;) 인젝션 토큰 거부."""
        with pytest.raises(AssertionError, match=";"):
            _assert_safe_cmd(["echo", "a;rm -rf /"], shell=False)

    def test_assert_safe_cmd_rejects_command_substitution(self) -> None:
        """$( 커맨드 서브스티튜션 토큰 거부."""
        with pytest.raises(AssertionError, match=r"\$\("):
            _assert_safe_cmd(["echo", "$(whoami)"], shell=False)

    def test_assert_safe_cmd_rejects_variable_substitution(self) -> None:
        """${ 변수 서브스티튜션 토큰 거부."""
        with pytest.raises(AssertionError, match=r"\$\{"):
            _assert_safe_cmd(["echo", "${PATH}"], shell=False)

    def test_assert_safe_cmd_rejects_backtick(self) -> None:
        """백틱(`) 토큰 거부."""
        with pytest.raises(AssertionError, match="`"):
            _assert_safe_cmd(["echo", "`whoami`"], shell=False)

    def test_assert_safe_cmd_rejects_pipe(self) -> None:
        """파이프(|) 토큰 거부."""
        with pytest.raises(AssertionError, match=r"\|"):
            _assert_safe_cmd(["echo", "a|cat"], shell=False)

    def test_assert_safe_cmd_rejects_and_operator(self) -> None:
        """AND 연산자(&&) 토큰 거부."""
        with pytest.raises(AssertionError, match="&&"):
            _assert_safe_cmd(["echo", "a&&b"], shell=False)

    def test_assert_safe_cmd_rejects_or_operator(self) -> None:
        """OR 연산자(||) 토큰 거부."""
        with pytest.raises(AssertionError, match=r"\|\|"):
            _assert_safe_cmd(["echo", "a||b"], shell=False)

    def test_assert_safe_cmd_rejects_redirect_out(self) -> None:
        """리다이렉션(>) 토큰 거부."""
        with pytest.raises(AssertionError, match=">"):
            _assert_safe_cmd(["echo", "a>/tmp/x"], shell=False)

    def test_assert_safe_cmd_rejects_redirect_in(self) -> None:
        """리다이렉션(<) 토큰 거부."""
        with pytest.raises(AssertionError, match="<"):
            _assert_safe_cmd(["echo", "a</tmp/x"], shell=False)

    def test_assert_safe_cmd_accepts_safe_kubectl_cmd(self) -> None:
        """정상 kubectl argv (6-tuple)는 통과."""
        _assert_safe_cmd(
            [
                "kubectl",
                "apply",
                "--dry-run=client",
                "--validate=false",
                "-f",
                "/tmp/manifests",
            ],
            shell=False,
        )

    def test_assert_safe_cmd_accepts_safe_docker_cmd(self) -> None:
        """정상 docker build argv는 통과."""
        _assert_safe_cmd(
            ["docker", "build", "-t", "myapp:1.0", "-f", "/tmp/Dockerfile", "/tmp/ctx"],
            shell=False,
        )

    def test_assert_safe_cmd_rejects_newline(self) -> None:
        """개행(\\n) 인젝션 토큰 거부."""
        with pytest.raises(AssertionError):
            _assert_safe_cmd(["echo", "a\nrm -rf /"], shell=False)

    def test_assert_safe_cmd_rejects_carriage_return(self) -> None:
        """캐리지 리턴(\\r) 인젝션 토큰 거부."""
        with pytest.raises(AssertionError):
            _assert_safe_cmd(["echo", "a\revil"], shell=False)

    def test_assert_safe_cmd_rejects_null_byte(self) -> None:
        """NUL 바이트(\\x00) 인젝션 토큰 거부."""
        with pytest.raises(AssertionError):
            _assert_safe_cmd(["echo", "a\x00evil"], shell=False)
