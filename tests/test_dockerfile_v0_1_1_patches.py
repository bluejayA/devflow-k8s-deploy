"""v0.1.1 패치: Dockerfile 템플릿 + jvm 빌드 cmd 수정 검증.

기존 v0.1.0 릴리즈는 4건의 `docker build` 시점 결함 보유:

- C1 (Critical): alpine 런너/빌더에 glibc 전용 `groupadd`/`useradd` 사용
- C2 (Critical): `COPY gradle gradle` + `COPY gradlew ./`로 wrapper 존재 강제
- I1 (Important): `build_cmd`가 `gradle bootJar` — `--no-daemon` 누락
- I2 (Important): `COPY . .`로 빌드 context 전체 복사 (`.git`, `build/`, 등)

본 파일은 v0.1.1 수정 후 상태를 검증하는 RED 테스트.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts._shared.types import BuildPlan, ResourceDefaults, UserInputs
from scripts.dockerfile_generator import DockerfileGenerator
from scripts.stacks.jvm import JvmStackModule
from scripts.template_renderer import TemplateRenderer
from tests.conftest import auto_inject_generate

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture()
def generator(jvm_stack_module: JvmStackModule) -> DockerfileGenerator:
    # BL-015: auto_inject_generate로 stack_module/detect_result 자동 주입.
    gen = DockerfileGenerator(TemplateRenderer(PROJECT_ROOT / "templates"))
    auto_inject_generate(gen, jvm_stack_module)
    return gen


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


@pytest.fixture()
def inputs() -> UserInputs:
    return UserInputs(
        app_name="sample",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )


@pytest.fixture()
def defaults() -> ResourceDefaults:
    return ResourceDefaults(
        cpu_request="250m",
        memory_request="256Mi",
        cpu_limit="500m",
        memory_limit="512Mi",
        writable_paths=["/tmp"],
    )


# ---------------------------------------------------------------------------
# C1: alpine 호환 사용자 관리
# ---------------------------------------------------------------------------


def test_gradle_dockerfile_uses_alpine_user_management(
    generator: DockerfileGenerator,
    gradle_plan: BuildPlan,
    inputs: UserInputs,
    defaults: ResourceDefaults,
) -> None:
    """alpine(busybox)에 존재하는 addgroup/adduser 사용, groupadd/useradd 금지."""
    result = generator.generate(gradle_plan, inputs, defaults)

    assert "addgroup" in result, "alpine 호환: addgroup 사용 필요"
    assert "adduser" in result, "alpine 호환: adduser 사용 필요"
    assert "groupadd" not in result, "alpine에 없는 glibc 명령 groupadd 사용 금지"
    assert "useradd" not in result, "alpine에 없는 glibc 명령 useradd 사용 금지"


def test_maven_dockerfile_uses_alpine_user_management(
    generator: DockerfileGenerator,
    maven_plan: BuildPlan,
    inputs: UserInputs,
    defaults: ResourceDefaults,
) -> None:
    result = generator.generate(maven_plan, inputs, defaults)

    assert "addgroup" in result
    assert "adduser" in result
    assert "groupadd" not in result
    assert "useradd" not in result


# ---------------------------------------------------------------------------
# C2: wrapper 의존 제거 (시스템 gradle 사용)
# ---------------------------------------------------------------------------


def test_gradle_dockerfile_no_wrapper_copy(
    generator: DockerfileGenerator,
    gradle_plan: BuildPlan,
    inputs: UserInputs,
    defaults: ResourceDefaults,
) -> None:
    """gradle:jdk*-alpine builder는 시스템 gradle 포함 — wrapper 불필요."""
    result = generator.generate(gradle_plan, inputs, defaults)

    assert "COPY gradle gradle" not in result, "gradle/ 디렉토리 COPY는 wrapper 의존 유발"
    assert "COPY gradlew" not in result, "gradlew 파일 COPY는 wrapper 의존 유발"


def test_gradle_dockerfile_uses_system_gradle_for_dep_cache(
    generator: DockerfileGenerator,
    gradle_plan: BuildPlan,
    inputs: UserInputs,
    defaults: ResourceDefaults,
) -> None:
    """의존성 캐시 레이어에서 ./gradlew가 아닌 시스템 gradle 호출."""
    result = generator.generate(gradle_plan, inputs, defaults)

    assert "./gradlew" not in result, "시스템 gradle 사용 — ./gradlew 호출 금지"
    assert "gradle --no-daemon dependencies" in result or "gradle dependencies" in result, (
        "의존성 캐시 warmup 레이어 유지 필요"
    )


# ---------------------------------------------------------------------------
# I1: build_cmd에 --no-daemon 포함 (jvm.py 실제 출력)
# ---------------------------------------------------------------------------


def test_jvm_gradle_build_cmd_has_no_daemon(tmp_path: Path) -> None:
    """JvmStackModule.build_plan()의 gradle build_cmd에 --no-daemon 포함.

    컨테이너 빌드에서 gradle daemon은 clean shutdown 실패 + 메모리 낭비 유발.
    """
    (tmp_path / "build.gradle.kts").write_text(
        "plugins {\n"
        '    id("org.springframework.boot") version "3.3.5"\n'
        '    kotlin("jvm") version "2.0.21"\n'
        "}\n"
        "dependencies {\n"
        '    implementation("org.springframework.boot:spring-boot-starter-web")\n'
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "settings.gradle.kts").write_text('rootProject.name = "x"\n', encoding="utf-8")

    module = JvmStackModule()
    detect = module.detect(tmp_path)
    assert detect is not None
    plan = module.build_plan(detect)

    assert "--no-daemon" in plan.build_cmd, (
        f"gradle build_cmd는 --no-daemon 포함 필요, got: {plan.build_cmd!r}"
    )
    assert "bootJar" in plan.build_cmd


# ---------------------------------------------------------------------------
# I2: context pollution 방어 — v0.2.0 Codex P1-b 피드백 이후
#     `COPY src ./src` 하드코딩은 multi-module 깨뜨려서 원복. 대신 `.dockerignore`로
#     .git / build/ / k8s-output/ / .env 유입 차단. 자세한 건
#     test_codex_p1_p2_fixes.py::test_dockerfile_generator_emits_dockerignore 참조.
# ---------------------------------------------------------------------------


def test_gradle_dockerfile_uses_full_context_with_ignore_filter(
    generator: DockerfileGenerator,
    gradle_plan: BuildPlan,
    inputs: UserInputs,
    defaults: ResourceDefaults,
) -> None:
    """`COPY . .` 복원 — multi-module 레이아웃 지원. pollution은 .dockerignore 담당."""
    result = generator.generate(gradle_plan, inputs, defaults)

    assert "COPY . ." in result, "multi-module 루트 지원을 위해 전체 context COPY 필요"


def test_maven_dockerfile_uses_full_context_with_ignore_filter(
    generator: DockerfileGenerator,
    maven_plan: BuildPlan,
    inputs: UserInputs,
    defaults: ResourceDefaults,
) -> None:
    result = generator.generate(maven_plan, inputs, defaults)

    assert "COPY . ." in result
