"""BL-001 Phase 7 — Go Dockerfile 골든 스냅샷 (NFR-04 (d)).

GoStackModule + DockerfileGenerator로 렌더링한 결과를 byte-identical 고정.
변경 시 UPDATE_SNAPSHOTS=1로 재생성.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts._shared.types import (
    BuildPlan,
    ResourceDefaults,
    StackDetectResult,
    UserInputs,
)
from scripts.dockerfile_generator import DockerfileGenerator
from scripts.stacks.go import GoStackModule
from scripts.template_renderer import TemplateRenderer

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture()
def generator() -> DockerfileGenerator:
    return DockerfileGenerator(TemplateRenderer(PROJECT_ROOT / "templates"))


@pytest.fixture()
def inputs() -> UserInputs:
    return UserInputs(
        app_name="myapp",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/go-output"),
        resource_hint="medium",
    )


@pytest.fixture()
def go_defaults() -> ResourceDefaults:
    return GoStackModule().defaults("medium")


@pytest.fixture()
def go_module() -> GoStackModule:
    return GoStackModule()


@pytest.fixture()
def go_detect_root() -> StackDetectResult:
    return StackDetectResult(
        port=None,
        entrypoint=".",
        framework="go-generic",
        version="1.22",
        cmd_candidates=[],
    )


@pytest.fixture()
def go_detect_cmd_subpath() -> StackDetectResult:
    return StackDetectResult(
        port=None,
        entrypoint="",
        framework="go-generic",
        version="1.22",
        cmd_candidates=["myapp", "worker"],
    )


@pytest.fixture()
def go_build_plan_root(
    go_module: GoStackModule,
    go_detect_root: StackDetectResult,
    inputs: UserInputs,
) -> BuildPlan:
    return go_module.build_plan(go_detect_root, inputs=inputs)


@pytest.fixture()
def go_build_plan_cmd(
    go_module: GoStackModule,
    go_detect_cmd_subpath: StackDetectResult,
    inputs: UserInputs,
) -> BuildPlan:
    return go_module.build_plan(go_detect_cmd_subpath, inputs=inputs)


def _snapshot_dir() -> Path:
    d = Path(__file__).parent / "snapshots" / "go"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _assert_golden(name: str, content: str) -> None:
    path = _snapshot_dir() / name
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not path.exists():
        path.write_text(content, encoding="utf-8")
        return
    expected = path.read_text(encoding="utf-8")
    assert content == expected, (
        f"Go Dockerfile 출력이 골든 스냅샷과 다릅니다 ({name}). "
        f"의도적이면 UPDATE_SNAPSHOTS=1로 재생성하세요.\n"
        f"--- expected ---\n{expected}\n--- actual ---\n{content}"
    )


def test_golden_go_root_main(
    generator: DockerfileGenerator,
    go_build_plan_root: BuildPlan,
    inputs: UserInputs,
    go_defaults: ResourceDefaults,
    go_module: GoStackModule,
    go_detect_root: StackDetectResult,
    tmp_path: Path,
) -> None:
    result = generator.generate(
        go_build_plan_root,
        inputs,
        go_defaults,
        stack_module=go_module,
        detect_result=go_detect_root,
        project_dir=tmp_path,
    )
    _assert_golden("go_root_main.Dockerfile", result)


def test_golden_go_cmd_subpath(
    generator: DockerfileGenerator,
    go_build_plan_cmd: BuildPlan,
    inputs: UserInputs,
    go_defaults: ResourceDefaults,
    go_module: GoStackModule,
    go_detect_cmd_subpath: StackDetectResult,
    tmp_path: Path,
) -> None:
    result = generator.generate(
        go_build_plan_cmd,
        inputs,
        go_defaults,
        stack_module=go_module,
        detect_result=go_detect_cmd_subpath,
        project_dir=tmp_path,
    )
    _assert_golden("go_cmd_subpath.Dockerfile", result)


def test_required_security_directives(
    generator: DockerfileGenerator,
    go_build_plan_root: BuildPlan,
    inputs: UserInputs,
    go_defaults: ResourceDefaults,
    go_module: GoStackModule,
    go_detect_root: StackDetectResult,
    tmp_path: Path,
) -> None:
    """보안 필수 지시어 — distroless nonroot, USER nonroot, EXPOSE."""
    result = generator.generate(
        go_build_plan_root,
        inputs,
        go_defaults,
        stack_module=go_module,
        detect_result=go_detect_root,
        project_dir=tmp_path,
    )
    assert "gcr.io/distroless/static-debian12:nonroot" in result
    assert "USER nonroot" in result
    assert "EXPOSE 8080" in result
    assert 'ENTRYPOINT ["/app/myapp"]' in result
    # latest 태그 부재
    assert ":latest" not in result
