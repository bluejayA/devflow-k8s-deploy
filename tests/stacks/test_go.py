"""GoStackModule 단위 테스트 (TDD, BL-001 Phase 6).

시나리오:
- _parse_go_mod 헬퍼 (F-21): module path / go version 추출 / 실패 시 GoDetectionError
- _collect_cmd_candidates 헬퍼 (F-22): cmd/*/main.go 후보 수집 / 정렬 / symlink escape 방어
- _build_multi_cmd_error_message 헬퍼 (F-28): 한국어 에러 메시지 + 상위 10개 + 생략 요약
- detect (F-02~F-05): go.mod 기반 감지, cmd_candidates 채움
- defaults (F-08, F-30): tier별 리소스 + run_as_user=65532 + writable_paths=["/tmp"]
- build_plan (F-06, F-29): entrypoint resolve + shell 주입 방어
- probe_plan (F-07): http /healthz
- artifact_locator (F-09): 빈 list
- dockerfile_context (F-10): 템플릿 렌더 키
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts._shared.errors import GoBuildPlanError, GoDetectionError
from scripts._shared.types import (
    ProbeConfig,
    ProbeSpec,
    StackDetectResult,
    UserInputs,
)
from scripts.stacks.go import (
    GoStackModule,
    _build_multi_cmd_error_message,
    _collect_cmd_candidates,
    _parse_go_mod,
)

# ──────────────────────────────────────────────────────────────────────────────
# 헬퍼: 픽스처 생성
# ──────────────────────────────────────────────────────────────────────────────


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_root_main_go(tmp_path: Path, *, go_version: str = "1.22") -> Path:
    """루트에 main.go + go.mod이 있는 단순 Go 프로젝트."""
    _write(
        tmp_path / "go.mod",
        f"module github.com/example/myapp\n\ngo {go_version}\n",
    )
    _write(
        tmp_path / "main.go",
        'package main\n\nimport "fmt"\n\nfunc main() { fmt.Println("hi") }\n',
    )
    return tmp_path


def _make_cmd_only(tmp_path: Path, names: list[str]) -> Path:
    """cmd/<name>/main.go 만 있는 multi-binary 프로젝트."""
    _write(tmp_path / "go.mod", "module github.com/example/multi\n\ngo 1.22\n")
    for name in names:
        _write(
            tmp_path / "cmd" / name / "main.go",
            "package main\n\nfunc main() {}\n",
        )
    return tmp_path


def _make_user_inputs(app_name: str = "myapp") -> UserInputs:
    return UserInputs(
        app_name=app_name,
        port=8080,
        exposure="ClusterIP",
        namespace="default",
        output_dir=Path("/tmp/out"),
        resource_hint="medium",
    )


# ──────────────────────────────────────────────────────────────────────────────
# _parse_go_mod (F-21)
# ──────────────────────────────────────────────────────────────────────────────


class TestParseGoMod:
    def test_parses_module_path_and_version(self, tmp_path: Path) -> None:
        go_mod = tmp_path / "go.mod"
        _write(go_mod, "module github.com/example/foo\n\ngo 1.22\n")
        module_path, version = _parse_go_mod(go_mod)
        assert module_path == "github.com/example/foo"
        assert version == "1.22"

    def test_handles_minor_patch_version(self, tmp_path: Path) -> None:
        go_mod = tmp_path / "go.mod"
        _write(go_mod, "module example.com/x\n\ngo 1.22.4\n")
        module_path, version = _parse_go_mod(go_mod)
        assert module_path == "example.com/x"
        assert version == "1.22.4"

    def test_no_go_directive_returns_none_version(self, tmp_path: Path) -> None:
        go_mod = tmp_path / "go.mod"
        _write(go_mod, "module example.com/x\n")
        module_path, version = _parse_go_mod(go_mod)
        assert module_path == "example.com/x"
        assert version is None

    def test_missing_module_directive_raises(self, tmp_path: Path) -> None:
        go_mod = tmp_path / "go.mod"
        _write(go_mod, "go 1.22\n")
        with pytest.raises(GoDetectionError, match="module"):
            _parse_go_mod(go_mod)

    def test_file_too_large_raises(self, tmp_path: Path) -> None:
        go_mod = tmp_path / "go.mod"
        # read_text_limited 5MB 한도 초과
        _write(go_mod, "module example.com/x\n" + "// pad\n" * (1024 * 1024))
        with pytest.raises(GoDetectionError):
            _parse_go_mod(go_mod)

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(GoDetectionError):
            _parse_go_mod(tmp_path / "missing.mod")


# ──────────────────────────────────────────────────────────────────────────────
# _collect_cmd_candidates (F-22)
# ──────────────────────────────────────────────────────────────────────────────


class TestCollectCmdCandidates:
    def test_no_cmd_dir(self, tmp_path: Path) -> None:
        assert _collect_cmd_candidates(tmp_path) == []

    def test_single_candidate(self, tmp_path: Path) -> None:
        _write(tmp_path / "cmd" / "myapp" / "main.go", "package main\n")
        assert _collect_cmd_candidates(tmp_path) == ["myapp"]

    def test_multiple_sorted(self, tmp_path: Path) -> None:
        for name in ("zservice", "api", "kube-controller"):
            _write(tmp_path / "cmd" / name / "main.go", "package main\n")
        assert _collect_cmd_candidates(tmp_path) == [
            "api",
            "kube-controller",
            "zservice",
        ]

    def test_skips_dirs_without_main_go(self, tmp_path: Path) -> None:
        # cmd/foo/main.go 있음, cmd/bar/server.go (main.go 아님)
        _write(tmp_path / "cmd" / "foo" / "main.go", "package main\n")
        _write(tmp_path / "cmd" / "bar" / "server.go", "package main\n")
        assert _collect_cmd_candidates(tmp_path) == ["foo"]

    def test_symlink_escape_rejected(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside"
        outside.mkdir(exist_ok=True)
        _write(outside / "main.go", "package main\n")
        cmd_dir = tmp_path / "cmd"
        cmd_dir.mkdir()
        try:
            os.symlink(outside, cmd_dir / "evil")
        except OSError:
            pytest.skip("symlink unsupported on this platform")
        # outside 디렉토리의 main.go 가 외부에 있어 is_within 차단되어야 함.
        assert _collect_cmd_candidates(tmp_path) == []


# ──────────────────────────────────────────────────────────────────────────────
# _build_multi_cmd_error_message (F-28)
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildMultiCmdErrorMessage:
    def test_short_list_no_ellipsis(self) -> None:
        msg = _build_multi_cmd_error_message(["api", "controller"], "myapp")
        assert "api" in msg
        assert "controller" in msg
        assert "myapp" in msg
        assert "외" not in msg  # 생략 요약 없음
        assert "stack.go.entrypoint" in msg

    def test_truncates_above_10(self) -> None:
        candidates = [f"svc{i:02d}" for i in range(15)]
        msg = _build_multi_cmd_error_message(candidates, "missing")
        # 정렬된 상위 10개 (svc00..svc09)
        assert "svc00" in msg
        assert "svc09" in msg
        # 11번째 이후는 미포함
        assert "svc10" not in msg
        assert "외 5개" in msg

    def test_korean_message_format(self) -> None:
        msg = _build_multi_cmd_error_message(["a", "b"], "myapp")
        assert "복수 cmd 엔트리포인트" in msg
        assert "app_name=myapp" in msg


# ──────────────────────────────────────────────────────────────────────────────
# GoStackModule.detect (F-02 ~ F-05)
# ──────────────────────────────────────────────────────────────────────────────


class TestGoDetect:
    def test_no_go_mod_returns_none(self, tmp_path: Path) -> None:
        assert GoStackModule().detect(tmp_path) is None

    def test_root_main_go(self, tmp_path: Path) -> None:
        _make_root_main_go(tmp_path)
        result = GoStackModule().detect(tmp_path)
        assert result is not None
        assert result.framework == "go-generic"
        assert result.entrypoint == "."
        assert result.cmd_candidates == []
        assert result.version == "1.22"
        assert result.port is None
        assert result.build_system is None
        assert result.actuator_enabled is False

    def test_cmd_only_undecided(self, tmp_path: Path) -> None:
        _make_cmd_only(tmp_path, ["api", "worker"])
        result = GoStackModule().detect(tmp_path)
        assert result is not None
        assert result.entrypoint == ""  # 미결정 sentinel
        assert result.cmd_candidates == ["api", "worker"]

    def test_root_takes_priority_over_cmd(self, tmp_path: Path) -> None:
        # 루트 main.go + cmd/foo/main.go 공존 시 루트 우선 (A-08)
        _make_root_main_go(tmp_path)
        _write(tmp_path / "cmd" / "foo" / "main.go", "package main\n")
        result = GoStackModule().detect(tmp_path)
        assert result is not None
        assert result.entrypoint == "."
        assert result.cmd_candidates == []

    def test_no_go_directive_falls_back_to_default(self, tmp_path: Path) -> None:
        _write(tmp_path / "go.mod", "module example.com/x\n")
        _write(tmp_path / "main.go", "package main\nfunc main() {}\n")
        result = GoStackModule().detect(tmp_path)
        assert result is not None
        assert result.version == "1.22"  # _DEFAULT_GO_VERSION

    def test_invalid_go_mod_raises(self, tmp_path: Path) -> None:
        # module 지시어 누락
        _write(tmp_path / "go.mod", "go 1.22\n")
        with pytest.raises(GoDetectionError):
            GoStackModule().detect(tmp_path)


# ──────────────────────────────────────────────────────────────────────────────
# GoStackModule.defaults (F-08, F-30)
# ──────────────────────────────────────────────────────────────────────────────


class TestGoDefaults:
    def test_small_tier(self) -> None:
        d = GoStackModule().defaults("small")
        assert d.cpu_request == "50m"
        assert d.memory_request == "64Mi"
        assert d.cpu_limit == "250m"
        assert d.memory_limit == "128Mi"
        assert d.run_as_user == 65532
        assert d.writable_paths == ["/tmp"]

    def test_medium_tier(self) -> None:
        d = GoStackModule().defaults("medium")
        assert d.cpu_request == "100m"
        assert d.memory_request == "128Mi"
        assert d.cpu_limit == "500m"
        assert d.memory_limit == "256Mi"
        assert d.run_as_user == 65532

    def test_large_tier(self) -> None:
        d = GoStackModule().defaults("large")
        assert d.cpu_request == "250m"
        assert d.memory_request == "256Mi"
        assert d.cpu_limit == "1000m"
        assert d.memory_limit == "512Mi"


# ──────────────────────────────────────────────────────────────────────────────
# GoStackModule.build_plan (F-06, F-29)
# ──────────────────────────────────────────────────────────────────────────────


class TestGoBuildPlan:
    def test_root_entrypoint(self) -> None:
        detect = StackDetectResult(
            port=None,
            entrypoint=".",
            framework="go-generic",
            version="1.22",
            cmd_candidates=[],
        )
        plan = GoStackModule().build_plan(detect, inputs=_make_user_inputs("myapp"))
        assert plan.builder_image == "golang:1.22-alpine"
        assert plan.runner_image == "gcr.io/distroless/static-debian12:nonroot"
        assert plan.artifact_path == "myapp"
        assert "go build" in plan.build_cmd
        assert "-o myapp" in plan.build_cmd
        assert plan.build_cmd.endswith(" .")

    def test_app_name_matches_cmd_candidate(self) -> None:
        detect = StackDetectResult(
            port=None,
            entrypoint="",
            framework="go-generic",
            version="1.22",
            cmd_candidates=["api", "kube-api", "worker"],
        )
        plan = GoStackModule().build_plan(
            detect, inputs=_make_user_inputs("kube-api")
        )
        assert plan.build_cmd.endswith(" ./cmd/kube-api")
        assert "-o kube-api" in plan.build_cmd

    def test_single_candidate_no_match(self) -> None:
        detect = StackDetectResult(
            port=None,
            entrypoint="",
            framework="go-generic",
            version="1.22",
            cmd_candidates=["server"],
        )
        plan = GoStackModule().build_plan(detect, inputs=_make_user_inputs("myapp"))
        # 매칭 실패 + 단일 후보 → 그 후보 사용 (F-06 2-b)
        assert plan.build_cmd.endswith(" ./cmd/server")

    def test_multi_candidate_no_match_raises(self) -> None:
        detect = StackDetectResult(
            port=None,
            entrypoint="",
            framework="go-generic",
            version="1.22",
            cmd_candidates=["api", "controller", "scheduler"],
        )
        with pytest.raises(GoBuildPlanError, match="복수 cmd"):
            GoStackModule().build_plan(detect, inputs=_make_user_inputs("missing"))

    def test_zero_candidates_falls_back_to_dot(self) -> None:
        detect = StackDetectResult(
            port=None,
            entrypoint="",
            framework="go-generic",
            version="1.22",
            cmd_candidates=[],
        )
        plan = GoStackModule().build_plan(detect, inputs=_make_user_inputs("myapp"))
        assert plan.build_cmd.endswith(" .")

    def test_no_inputs_raises(self) -> None:
        detect = StackDetectResult(
            port=None, entrypoint=".", framework="go-generic", version="1.22"
        )
        with pytest.raises(GoBuildPlanError):
            GoStackModule().build_plan(detect, inputs=None)

    def test_invalid_app_name_raises(self) -> None:
        detect = StackDetectResult(
            port=None, entrypoint=".", framework="go-generic", version="1.22"
        )
        # Invalid: shell 메타문자 — DNS-1123 재검증에서 거부
        with pytest.raises(GoBuildPlanError):
            GoStackModule().build_plan(
                detect, inputs=_make_user_inputs("evil; rm -rf /")
            )

    def test_invalid_entrypoint_raises(self) -> None:
        detect = StackDetectResult(
            port=None,
            entrypoint="../etc/passwd",
            framework="go-generic",
            version="1.22",
        )
        with pytest.raises(GoBuildPlanError):
            GoStackModule().build_plan(detect, inputs=_make_user_inputs("myapp"))

    def test_falls_back_to_default_go_version(self) -> None:
        detect = StackDetectResult(
            port=None, entrypoint=".", framework="go-generic", version=None
        )
        plan = GoStackModule().build_plan(detect, inputs=_make_user_inputs("myapp"))
        assert plan.builder_image == "golang:1.22-alpine"


# ──────────────────────────────────────────────────────────────────────────────
# GoStackModule.probe_plan (F-07)
# ──────────────────────────────────────────────────────────────────────────────


class TestGoProbePlan:
    def test_http_healthz_default_port(self) -> None:
        detect = StackDetectResult(
            port=None, entrypoint=".", framework="go-generic", version="1.22"
        )
        cfg = GoStackModule().probe_plan(detect)
        assert isinstance(cfg, ProbeConfig)
        assert cfg.liveness == ProbeSpec(kind="http", path="/healthz", port=8080)
        assert cfg.readiness == ProbeSpec(kind="http", path="/healthz", port=8080)

    def test_http_healthz_explicit_port(self) -> None:
        detect = StackDetectResult(
            port=9000, entrypoint=".", framework="go-generic", version="1.22"
        )
        cfg = GoStackModule().probe_plan(detect)
        assert cfg.liveness.port == 9000


# ──────────────────────────────────────────────────────────────────────────────
# GoStackModule.artifact_locator (F-09) + dockerfile_context (F-10)
# ──────────────────────────────────────────────────────────────────────────────


class TestArtifactLocatorAndContext:
    def test_artifact_locator_returns_empty(self, tmp_path: Path) -> None:
        detect = StackDetectResult(
            port=None, entrypoint=".", framework="go-generic", version="1.22"
        )
        assert GoStackModule().artifact_locator(detect, tmp_path) == []

    def test_dockerfile_context_keys(self) -> None:
        detect = StackDetectResult(
            port=8080, entrypoint=".", framework="go-generic", version="1.22"
        )
        inputs = _make_user_inputs("myapp")
        plan = GoStackModule().build_plan(detect, inputs=inputs)
        ctx = GoStackModule().dockerfile_context(
            build_plan=plan,
            detect_result=detect,
            inputs=inputs,
            project_dir=None,
        )
        assert ctx["builder_image"] == plan.builder_image
        assert ctx["runner_image"] == plan.runner_image
        assert ctx["build_cmd"] == plan.build_cmd
        assert ctx["artifact_path"] == "myapp"
        assert ctx["port"] == 8080
        assert ctx["app_name"] == "myapp"


# ──────────────────────────────────────────────────────────────────────────────
# Protocol 런타임 체크 (NFR-04 (n))
# ──────────────────────────────────────────────────────────────────────────────


class TestProtocolCompliance:
    def test_isinstance_stack_module(self) -> None:
        from scripts.stacks.base import StackModule

        assert isinstance(GoStackModule(), StackModule)

    def test_class_vars(self) -> None:
        assert GoStackModule.name == "go"
        assert GoStackModule.template_name == "go"
