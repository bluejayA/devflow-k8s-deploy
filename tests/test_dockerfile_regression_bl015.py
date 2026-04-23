"""BL-015 regression — 리팩토링 전후 JVM Dockerfile byte-identical 보장.

StackModule Protocol 확장 전 현재 출력을 snapshot으로 고정한다.
리팩토링 중 이 테스트가 깨지면 렌더링 결과가 변한 것.

Gradle/Maven × (with/without gradle dir) 4가지 조합 전부 고정.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts._shared.types import BuildPlan, ResourceDefaults, StackDetectResult, UserInputs
from scripts.dockerfile_generator import DockerfileGenerator
from scripts.stacks.jvm import JvmStackModule
from scripts.template_renderer import TemplateRenderer

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture()
def generator() -> DockerfileGenerator:
    return DockerfileGenerator(TemplateRenderer(PROJECT_ROOT / "templates"))


@pytest.fixture()
def inputs() -> UserInputs:
    return UserInputs(
        app_name="bl015-app",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/bl015-output"),
        resource_hint="medium",
    )


@pytest.fixture()
def defaults() -> ResourceDefaults:
    return ResourceDefaults(
        cpu_request="250m",
        memory_request="256Mi",
        cpu_limit="500m",
        memory_limit="512Mi",
        writable_paths=["/tmp", "/var/log"],
    )


@pytest.fixture()
def gradle_plan() -> BuildPlan:
    return BuildPlan(
        builder_image="gradle:jdk21-alpine",
        runner_image="eclipse-temurin:21-jre-alpine",
        build_cmd="gradle --no-daemon bootJar",
        artifact_path="build/libs/*.jar",
    )


@pytest.fixture()
def maven_plan() -> BuildPlan:
    return BuildPlan(
        builder_image="maven:3.9-eclipse-temurin-21-alpine",
        runner_image="eclipse-temurin:21-jre-alpine",
        build_cmd="mvn -B package",
        artifact_path="target/*.jar",
    )


def _snapshot_dir() -> Path:
    """골든 스냅샷 디렉토리. 없으면 생성."""
    d = Path(__file__).parent / "snapshots" / "bl015"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _assert_golden(name: str, content: str) -> None:
    """스냅샷 파일 비교. 없으면 최초 작성 (UPDATE_SNAPSHOTS=1 환경변수로 갱신)."""
    import os

    path = _snapshot_dir() / name
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not path.exists():
        path.write_text(content, encoding="utf-8")
        return
    expected = path.read_text(encoding="utf-8")
    assert content == expected, (
        f"Dockerfile 출력이 골든 스냅샷과 다릅니다 ({name}). "
        f"변경이 의도적이면 UPDATE_SNAPSHOTS=1 로 재생성하세요.\n"
        f"--- expected ---\n{expected}\n--- actual ---\n{content}"
    )


def test_golden_gradle_without_gradle_dir(
    generator: DockerfileGenerator,
    gradle_plan: BuildPlan,
    inputs: UserInputs,
    defaults: ResourceDefaults,
    jvm_stack_module: JvmStackModule,
    gradle_detect_result: StackDetectResult,
    tmp_path: Path,
) -> None:
    # project_dir 지정하되 gradle/ 서브디렉토리 없음
    result = generator.generate(
        gradle_plan,
        inputs,
        defaults,
        stack_module=jvm_stack_module,
        detect_result=gradle_detect_result,
        project_dir=tmp_path,
    )
    _assert_golden("gradle_no_gradle_dir.Dockerfile", result)


def test_golden_gradle_with_gradle_dir(
    generator: DockerfileGenerator,
    gradle_plan: BuildPlan,
    inputs: UserInputs,
    defaults: ResourceDefaults,
    jvm_stack_module: JvmStackModule,
    gradle_detect_result: StackDetectResult,
    tmp_path: Path,
) -> None:
    (tmp_path / "gradle").mkdir()
    result = generator.generate(
        gradle_plan,
        inputs,
        defaults,
        stack_module=jvm_stack_module,
        detect_result=gradle_detect_result,
        project_dir=tmp_path,
    )
    _assert_golden("gradle_with_gradle_dir.Dockerfile", result)


def test_golden_maven(
    generator: DockerfileGenerator,
    maven_plan: BuildPlan,
    inputs: UserInputs,
    defaults: ResourceDefaults,
    jvm_stack_module: JvmStackModule,
    maven_detect_result: StackDetectResult,
    tmp_path: Path,
) -> None:
    result = generator.generate(
        maven_plan,
        inputs,
        defaults,
        stack_module=jvm_stack_module,
        detect_result=maven_detect_result,
        project_dir=tmp_path,
    )
    _assert_golden("maven.Dockerfile", result)


def test_golden_gradle_no_project_dir(
    generator: DockerfileGenerator,
    gradle_plan: BuildPlan,
    inputs: UserInputs,
    defaults: ResourceDefaults,
    jvm_stack_module: JvmStackModule,
    gradle_detect_result: StackDetectResult,
) -> None:
    # project_dir=None → has_gradle_dir 감지 불가 → False
    result = generator.generate(
        gradle_plan,
        inputs,
        defaults,
        stack_module=jvm_stack_module,
        detect_result=gradle_detect_result,
    )
    _assert_golden("gradle_no_project_dir.Dockerfile", result)
