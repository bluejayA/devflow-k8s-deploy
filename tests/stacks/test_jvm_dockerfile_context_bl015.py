"""BL-015 — JvmStackModule.dockerfile_context() 단위 테스트.

dockerfile_generator.py에서 이관된 로직(_detect_build_system, has_gradle_dir)이
JvmStackModule 내부에서 올바르게 작동하는지 검증.

Protocol 규약:
  - template_name: ClassVar[str] == "jvm"
  - dockerfile_context(build_plan, detect_result, inputs, project_dir) -> dict
    반환 딕트에 template 렌더에 필요한 모든 키 포함.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts._shared.types import BuildPlan, StackDetectResult, UserInputs
from scripts.stacks.jvm import JvmStackModule


@pytest.fixture()
def module() -> JvmStackModule:
    return JvmStackModule()


@pytest.fixture()
def inputs() -> UserInputs:
    return UserInputs(
        app_name="app",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/out"),
        resource_hint="medium",
    )


@pytest.fixture()
def detect_result_gradle() -> StackDetectResult:
    return StackDetectResult(
        port=8080,
        entrypoint="",
        framework="spring-boot",
        version="3.2.0",
        build_system="gradle",
        actuator_enabled=True,
    )


@pytest.fixture()
def detect_result_maven() -> StackDetectResult:
    return StackDetectResult(
        port=8080,
        entrypoint="",
        framework="spring-boot",
        version="3.2.0",
        build_system="maven",
        actuator_enabled=True,
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


# ---------------------------------------------------------------------------
# template_name
# ---------------------------------------------------------------------------


def test_template_name_is_jvm(module: JvmStackModule) -> None:
    assert module.template_name == "jvm"


# ---------------------------------------------------------------------------
# dockerfile_context — Gradle
# ---------------------------------------------------------------------------


def test_dockerfile_context_gradle_basic(
    module: JvmStackModule,
    gradle_plan: BuildPlan,
    detect_result_gradle: StackDetectResult,
    inputs: UserInputs,
    tmp_path: Path,
) -> None:
    context = module.dockerfile_context(
        build_plan=gradle_plan,
        detect_result=detect_result_gradle,
        inputs=inputs,
        project_dir=tmp_path,
    )
    assert context["build_system"] == "gradle"
    assert context["builder_image"] == "gradle:jdk21-alpine"
    assert context["runner_image"] == "eclipse-temurin:21-jre-alpine"
    assert context["build_cmd"] == "gradle --no-daemon bootJar"
    assert context["artifact_path"] == "build/libs/*.jar"
    assert context["port"] == 8080
    assert context["has_gradle_dir"] is False  # gradle/ 서브디렉토리 없음


def test_dockerfile_context_gradle_with_gradle_dir(
    module: JvmStackModule,
    gradle_plan: BuildPlan,
    detect_result_gradle: StackDetectResult,
    inputs: UserInputs,
    tmp_path: Path,
) -> None:
    (tmp_path / "gradle").mkdir()
    context = module.dockerfile_context(
        build_plan=gradle_plan,
        detect_result=detect_result_gradle,
        inputs=inputs,
        project_dir=tmp_path,
    )
    assert context["has_gradle_dir"] is True


def test_dockerfile_context_gradle_no_project_dir(
    module: JvmStackModule,
    gradle_plan: BuildPlan,
    detect_result_gradle: StackDetectResult,
    inputs: UserInputs,
) -> None:
    context = module.dockerfile_context(
        build_plan=gradle_plan,
        detect_result=detect_result_gradle,
        inputs=inputs,
        project_dir=None,
    )
    assert context["has_gradle_dir"] is False


# ---------------------------------------------------------------------------
# dockerfile_context — Maven
# ---------------------------------------------------------------------------


def test_dockerfile_context_maven_basic(
    module: JvmStackModule,
    maven_plan: BuildPlan,
    detect_result_maven: StackDetectResult,
    inputs: UserInputs,
    tmp_path: Path,
) -> None:
    context = module.dockerfile_context(
        build_plan=maven_plan,
        detect_result=detect_result_maven,
        inputs=inputs,
        project_dir=tmp_path,
    )
    assert context["build_system"] == "maven"
    assert context["has_gradle_dir"] is False  # maven이면 무관하지만 False로 고정
