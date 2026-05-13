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
import re
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
    _ECHO_RE,
    _FIBER_RE,
    _GIN_RE,
    GoStackModule,
    _build_multi_cmd_error_message,
    _collect_cmd_candidates,
    _detect_go_framework,
    _parse_go_mod,
    _parse_go_mod_require,
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


# ──────────────────────────────────────────────────────────────────────────────
# BL-017 — Go 프레임워크 probe 자동 감지 (gin/echo/fiber)
# F-01~F-14, F-06a, NFR-1~NFR-7, A-01~A-07
# ──────────────────────────────────────────────────────────────────────────────


class TestFrameworkRegex:
    """F-03: word boundary + non-capturing major version 정규식."""

    @pytest.mark.parametrize(
        "regex,line",
        [
            (_GIN_RE, "github.com/gin-gonic/gin v1.9.1"),
            (_ECHO_RE, "github.com/labstack/echo v3.3.10"),
            (_FIBER_RE, "github.com/gofiber/fiber v1.14.6"),
        ],
    )
    def test_framework_regex_matches_root_module(
        self, regex: re.Pattern[str], line: str
    ) -> None:
        assert regex.search(line) is not None

    @pytest.mark.parametrize(
        "regex,line",
        [
            (_ECHO_RE, "github.com/labstack/echo/v4 v4.11.4"),
            (_FIBER_RE, "github.com/gofiber/fiber/v2 v2.52.0"),
        ],
    )
    def test_framework_regex_matches_major_versions(
        self, regex: re.Pattern[str], line: str
    ) -> None:
        assert regex.search(line) is not None

    def test_framework_regex_no_false_positive_partial_word(self) -> None:
        # `gin-gonic/ginX` 같은 길어진 모듈명에 대해 false-positive 방어 (\b 경계)
        assert _GIN_RE.search("github.com/gin-gonic/ginX v1.0.0") is None
        # echo-fork 패턴
        assert _ECHO_RE.search("github.com/labstack/echox v1.0.0") is None
        # fiber-fork 패턴
        assert _FIBER_RE.search("github.com/gofiber/fiberx v1.0.0") is None


class TestParseGoModRequire:
    """F-06a: go.mod `require` 블록 텍스트 파서.

    - `require ( ... )` 블록 + 단일 라인 `require <module> <ver>` 두 형식 지원
    - `//` 주석 제거
    - 파싱 실패 라인은 silent skip (감지는 hint, NFR-3)
    """

    def test_parse_go_mod_block_form(self) -> None:
        content = """module example.com/foo

go 1.22

require (
    github.com/gin-gonic/gin v1.9.1
    github.com/labstack/echo/v4 v4.11.4
    github.com/stretchr/testify v1.8.4
)
"""
        deps = _parse_go_mod_require(content)
        assert "github.com/gin-gonic/gin" in deps
        assert "github.com/labstack/echo/v4" in deps
        assert "github.com/stretchr/testify" in deps

    def test_parse_go_mod_single_line_form(self) -> None:
        content = """module example.com/bar

go 1.22

require github.com/gofiber/fiber/v2 v2.52.0
"""
        deps = _parse_go_mod_require(content)
        assert "github.com/gofiber/fiber/v2" in deps

    def test_parse_go_mod_strips_inline_comments(self) -> None:
        content = """module example.com/baz

go 1.22

require (
    github.com/gin-gonic/gin v1.9.1 // direct
    github.com/davecgh/go-spew v1.1.1 // indirect
)
"""
        deps = _parse_go_mod_require(content)
        assert "github.com/gin-gonic/gin" in deps
        assert "github.com/davecgh/go-spew" in deps

    def test_parse_go_mod_skips_malformed_lines(self) -> None:
        # 잘못된 라인 (모듈 경로 누락, 빈 라인, 마구잡이 문자열)은 skip
        # 정상 라인은 정상 파싱되어야 함
        content = """module example.com/qux

go 1.22

require (
    github.com/gin-gonic/gin v1.9.1
    @@@bad-line@@@

    onlymodulepath
)
"""
        deps = _parse_go_mod_require(content)
        assert "github.com/gin-gonic/gin" in deps
        # malformed 라인은 결과에 포함되지 않음
        assert "@@@bad-line@@@" not in deps


# ──────────────────────────────────────────────────────────────────────────────
# BL-017 — _detect_go_framework (F-02 "Direct dependency wins" 4단계)
# ──────────────────────────────────────────────────────────────────────────────


def _write_go_files(
    project_dir: Path,
    *,
    go_mod: str | None = None,
    go_sum: str | None = None,
) -> None:
    """테스트 픽스처: go.mod / go.sum 텍스트를 project_dir에 작성 (A-06)."""
    if go_mod is not None:
        (project_dir / "go.mod").write_text(go_mod)
    if go_sum is not None:
        (project_dir / "go.sum").write_text(go_sum)


_BASE_GO_MOD = """module example.com/app

go 1.22

require (
{deps}
)
"""


class TestDetectFrameworkDirectSingle:
    """F-02 단계 1·2: go.mod direct 단일 매치 → 해당 framework 채택."""

    def test_detect_framework_direct_gin_single(self, tmp_path: Path) -> None:
        _write_go_files(
            tmp_path,
            go_mod=_BASE_GO_MOD.format(deps="    github.com/gin-gonic/gin v1.9.1"),
            go_sum="",
        )
        assert _detect_go_framework(tmp_path) == "gin"

    def test_detect_framework_direct_echo_single(self, tmp_path: Path) -> None:
        _write_go_files(
            tmp_path,
            go_mod=_BASE_GO_MOD.format(
                deps="    github.com/labstack/echo/v4 v4.11.4"
            ),
            go_sum="",
        )
        assert _detect_go_framework(tmp_path) == "echo"

    def test_detect_framework_direct_fiber_single(self, tmp_path: Path) -> None:
        _write_go_files(
            tmp_path,
            go_mod=_BASE_GO_MOD.format(
                deps="    github.com/gofiber/fiber/v2 v2.52.0"
            ),
            go_sum="",
        )
        assert _detect_go_framework(tmp_path) == "fiber"


class TestDetectFrameworkFallback:
    """F-02 단계 3·4: direct 복수 또는 sum 단일/복수 폴백."""

    def test_detect_framework_direct_multiple_falls_back_to_generic(
        self, tmp_path: Path
    ) -> None:
        # gin + echo 동시 direct → 고정 순서 억지 선택 금지 → go-generic
        deps = (
            "    github.com/gin-gonic/gin v1.9.1\n"
            "    github.com/labstack/echo/v4 v4.11.4"
        )
        _write_go_files(tmp_path, go_mod=_BASE_GO_MOD.format(deps=deps), go_sum="")
        assert _detect_go_framework(tmp_path) == "go-generic"

    def test_detect_framework_sum_only_single_match(self, tmp_path: Path) -> None:
        # direct에 framework 없음 + go.sum에 gin만 transitive → 약한 evidence로 채택
        go_mod = _BASE_GO_MOD.format(
            deps="    github.com/stretchr/testify v1.8.4"
        )
        go_sum = (
            "github.com/gin-gonic/gin v1.9.1 h1:abcdef\n"
            "github.com/gin-gonic/gin v1.9.1/go.mod h1:fedcba\n"
            "github.com/stretchr/testify v1.8.4 h1:xyz\n"
        )
        _write_go_files(tmp_path, go_mod=go_mod, go_sum=go_sum)
        assert _detect_go_framework(tmp_path) == "gin"

    def test_detect_framework_sum_multiple_falls_back_to_generic(
        self, tmp_path: Path
    ) -> None:
        # direct 없음 + go.sum에 gin + echo 동시 → go-generic
        go_mod = _BASE_GO_MOD.format(
            deps="    github.com/stretchr/testify v1.8.4"
        )
        go_sum = (
            "github.com/gin-gonic/gin v1.9.1 h1:abc\n"
            "github.com/labstack/echo/v4 v4.11.4 h1:def\n"
        )
        _write_go_files(tmp_path, go_mod=go_mod, go_sum=go_sum)
        assert _detect_go_framework(tmp_path) == "go-generic"


class TestDetectFrameworkSafeFallback:
    """F-04/F-06: 파일 없음, symlink escape 등 모든 실패는 안전 폴백."""

    def test_detect_framework_no_go_mod_returns_generic(self, tmp_path: Path) -> None:
        # go.mod 자체가 없어도 raise 없이 go-generic 반환 (NFR-3)
        assert _detect_go_framework(tmp_path) == "go-generic"

    def test_detect_framework_no_go_sum_uses_direct_or_generic(
        self, tmp_path: Path
    ) -> None:
        # go.sum 부재 → direct만 사용. direct에 gin → "gin"
        _write_go_files(
            tmp_path,
            go_mod=_BASE_GO_MOD.format(deps="    github.com/gin-gonic/gin v1.9.1"),
            go_sum=None,  # 파일 자체 생성 안 함
        )
        assert _detect_go_framework(tmp_path) == "gin"

    def test_detect_framework_symlink_escape_ignored(self, tmp_path: Path) -> None:
        # tmp_path 밖의 외부 go.mod를 symlink로 가리키면 is_within 가드로 무시 → "go-generic"
        outside = tmp_path.parent / "outside_go_mod_target.mod"
        outside.write_text(
            _BASE_GO_MOD.format(deps="    github.com/gin-gonic/gin v1.9.1")
        )
        try:
            try:
                os.symlink(outside, tmp_path / "go.mod")
            except OSError:
                pytest.skip("symlink unsupported on this platform")
            assert _detect_go_framework(tmp_path) == "go-generic"
        finally:
            outside.unlink(missing_ok=True)


# ──────────────────────────────────────────────────────────────────────────────
# BL-017 — GoStackModule.detect() / probe_plan() framework 통합
# ──────────────────────────────────────────────────────────────────────────────


class TestGoStackModuleDetectFramework:
    """F-05: detect()가 _detect_go_framework 결과를 framework 필드에 반영."""

    def test_detect_returns_detected_framework_gin(self, tmp_path: Path) -> None:
        _write_go_files(
            tmp_path,
            go_mod=_BASE_GO_MOD.format(deps="    github.com/gin-gonic/gin v1.9.1"),
            go_sum="",
        )
        # 루트 main.go도 함께 (BL-001 detect 정상 동작 위해)
        (tmp_path / "main.go").write_text("package main\n")

        result = GoStackModule().detect(tmp_path)
        assert result is not None
        assert result.framework == "gin"

    def test_detect_returns_go_generic_when_no_framework(self, tmp_path: Path) -> None:
        # framework 의존성 없는 일반 Go 프로젝트 — BL-001 기본 동작 byte-identical
        _write_go_files(
            tmp_path,
            go_mod=_BASE_GO_MOD.format(deps="    github.com/stretchr/testify v1.8.4"),
            go_sum="",
        )
        (tmp_path / "main.go").write_text("package main\n")

        result = GoStackModule().detect(tmp_path)
        assert result is not None
        assert result.framework == "go-generic"


class TestProbePlanFrameworkBranching:
    """F-07: probe_plan은 framework별 헬스 경로 분기.

    - gin/echo/fiber → /health (관용)
    - go-generic / 기타 → /healthz (BL-001 baseline 불변)
    """

    @pytest.mark.parametrize("framework", ["gin", "echo", "fiber"])
    def test_probe_plan_framework_returns_health(self, framework: str) -> None:
        detect = StackDetectResult(
            port=8080, entrypoint=".", framework=framework, version="1.22"
        )
        cfg = GoStackModule().probe_plan(detect)
        assert cfg.liveness.path == "/health"
        assert cfg.readiness.path == "/health"
        assert cfg.liveness.port == 8080

    def test_probe_plan_generic_returns_healthz_unchanged(self) -> None:
        # BL-001 baseline byte-identical (NFR-5)
        detect = StackDetectResult(
            port=8080, entrypoint=".", framework="go-generic", version="1.22"
        )
        cfg = GoStackModule().probe_plan(detect)
        assert cfg.liveness.path == "/healthz"
        assert cfg.readiness.path == "/healthz"
