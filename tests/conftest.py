"""공통 pytest fixtures — tests/ 전반에서 자동 로딩.

BL-015: DockerfileGenerator.generate() 시그니처에 stack_module + detect_result가
필수가 되면서, 기존 테스트가 호출부를 수정하지 않아도 되도록 helper fixture 제공.

기존 dockerfile_generator 테스트들은 `generator.generate(plan, inputs, defaults)` 형태로
호출하는데, _patch_generator()가 `generate()`를 래핑해서 build_cmd 토큰으로
gradle/maven detect_result를 자동 선택 + JvmStackModule 인스턴스 자동 주입한다.
명시적으로 stack_module / detect_result를 넘기면 래퍼가 그대로 통과시킨다.
"""

from __future__ import annotations

from typing import Literal

import pytest

from scripts._shared.types import BuildPlan, StackDetectResult
from scripts.dockerfile_generator import DockerfileGenerator
from scripts.stacks.jvm import JvmStackModule


@pytest.fixture()
def jvm_stack_module() -> JvmStackModule:
    """실제 JvmStackModule 인스턴스 (Protocol 경계 검증을 실 구현으로 수행)."""
    return JvmStackModule()


def _jvm_detect_result(build_system: Literal["gradle", "maven"]) -> StackDetectResult:
    return StackDetectResult(
        port=8080,
        entrypoint="",
        framework="spring-boot",
        version="3.2.0",
        build_system=build_system,
        actuator_enabled=True,
    )


@pytest.fixture()
def gradle_detect_result() -> StackDetectResult:
    return _jvm_detect_result("gradle")


@pytest.fixture()
def maven_detect_result() -> StackDetectResult:
    return _jvm_detect_result("maven")


def _infer_build_system(build_cmd: str) -> Literal["gradle", "maven"]:
    """build_cmd 토큰에서 gradle/maven 판별 (테스트 helper 전용).

    `DockerfileGenerator._detect_build_system()`에서 제거된 로직의 복제본.
    production 코드는 StackDetectResult.build_system을 사용하므로 문제 없음.
    """
    maven_tokens = {"mvn", "mvnw", "./mvnw", "mvn.cmd", "maven"}
    gradle_tokens = {"gradle", "gradlew", "./gradlew", "gradle.cmd"}
    for tok in build_cmd.lower().split():
        base = tok.rsplit("/", 1)[-1]
        if base in maven_tokens:
            return "maven"
    for tok in build_cmd.lower().split():
        base = tok.rsplit("/", 1)[-1]
        if base in gradle_tokens:
            return "gradle"
    return "gradle"


def auto_inject_generate(
    generator: DockerfileGenerator,
    jvm_module: JvmStackModule,
) -> None:
    """`generator.generate()`를 인플레이스 래핑.

    호출 시 stack_module / detect_result 명시 안 하면 build_cmd 기반으로
    Jvm + gradle/maven detect_result 자동 주입. 기존 테스트 body 수정 최소화.
    """
    original = generator.generate

    def wrapped(
        build_plan: BuildPlan,
        inputs,  # noqa: ANN001
        defaults,  # noqa: ANN001
        *,
        stack_module=None,  # noqa: ANN001
        detect_result=None,  # noqa: ANN001
        project_dir=None,  # noqa: ANN001
    ) -> str:
        sm = stack_module if stack_module is not None else jvm_module
        if detect_result is None:
            bs = _infer_build_system(build_plan.build_cmd)
            detect_result = _jvm_detect_result(bs)
        return original(
            build_plan,
            inputs,
            defaults,
            stack_module=sm,
            detect_result=detect_result,
            project_dir=project_dir,
        )

    generator.generate = wrapped  # type: ignore[method-assign]
