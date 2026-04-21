"""TDD: DockerfileGenerator — multi-stage Dockerfile 생성기.

RED → GREEN → REFACTOR 순서.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts._shared.errors import InvalidImageError
from scripts._shared.types import BuildPlan, ResourceDefaults, UserInputs
from scripts.dockerfile_generator import DockerfileGenerator
from scripts.template_renderer import TemplateRenderer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture()
def renderer() -> TemplateRenderer:
    """실제 프로젝트 templates/ 디렉토리를 사용하는 TemplateRenderer."""
    return TemplateRenderer(PROJECT_ROOT / "templates")


@pytest.fixture()
def generator(renderer: TemplateRenderer) -> DockerfileGenerator:
    return DockerfileGenerator(renderer)


@pytest.fixture()
def gradle_build_plan() -> BuildPlan:
    return BuildPlan(
        builder_image="eclipse-temurin:21-jdk-alpine",
        runner_image="eclipse-temurin:21-jre-alpine",
        build_cmd="./gradlew bootJar --no-daemon",
        artifact_path="build/libs/app.jar",
    )


@pytest.fixture()
def maven_build_plan() -> BuildPlan:
    return BuildPlan(
        builder_image="eclipse-temurin:21-jdk-alpine",
        runner_image="eclipse-temurin:21-jre-alpine",
        build_cmd="mvn package -DskipTests",
        artifact_path="target/app.jar",
    )


@pytest.fixture()
def user_inputs() -> UserInputs:
    return UserInputs(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )


@pytest.fixture()
def resource_defaults() -> ResourceDefaults:
    return ResourceDefaults(
        cpu_request="250m",
        memory_request="256Mi",
        cpu_limit="500m",
        memory_limit="512Mi",
        writable_paths=["/tmp", "/var/log"],
    )


# ---------------------------------------------------------------------------
# 1. generate — basic Gradle Spring Boot: multi-stage, USER appuser,
#    COPY --chown, EXPOSE port, ENTRYPOINT
# ---------------------------------------------------------------------------


def test_generate_gradle_multi_stage_structure(
    generator: DockerfileGenerator,
    gradle_build_plan: BuildPlan,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    result = generator.generate(gradle_build_plan, user_inputs, resource_defaults)

    # multi-stage: FROM ... AS builder + FROM runner
    assert "AS builder" in result
    assert result.count("FROM ") >= 2
    # 비root
    assert "USER appuser" in result
    # COPY --chown
    assert "COPY --from=builder" in result
    assert "--chown=" in result
    # EXPOSE
    assert "EXPOSE 8080" in result
    # ENTRYPOINT
    assert "ENTRYPOINT" in result


# ---------------------------------------------------------------------------
# 2. generate — Maven: Maven 분기 (COPY pom.xml, mvn dependency:go-offline)
# ---------------------------------------------------------------------------


def test_generate_maven_branch(
    generator: DockerfileGenerator,
    maven_build_plan: BuildPlan,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    result = generator.generate(maven_build_plan, user_inputs, resource_defaults)

    assert "pom.xml" in result
    assert "dependency:go-offline" in result or "go-offline" in result


# ---------------------------------------------------------------------------
# 3. _validate_image_tag — latest 차단
# ---------------------------------------------------------------------------


def test_validate_latest_tag_raises(generator: DockerfileGenerator) -> None:
    with pytest.raises(InvalidImageError, match="latest"):
        generator._validate_image_tag("alpine:latest")


# ---------------------------------------------------------------------------
# 4. _validate_image_tag — 태그 누락 차단
# ---------------------------------------------------------------------------


def test_validate_missing_tag_raises(generator: DockerfileGenerator) -> None:
    with pytest.raises(InvalidImageError):
        generator._validate_image_tag("alpine")


# ---------------------------------------------------------------------------
# 5. _validate_image_tag — digest pinning 허용
# ---------------------------------------------------------------------------


def test_validate_digest_pinning_allowed(generator: DockerfileGenerator) -> None:
    # @sha256:<64 hex> 형식은 태그 없어도 통과
    digest = "a" * 64
    generator._validate_image_tag(f"alpine@sha256:{digest}")  # no raise


# ---------------------------------------------------------------------------
# 6. _validate_image_tag — 정상 태그 통과
# ---------------------------------------------------------------------------


def test_validate_normal_tag_passes(generator: DockerfileGenerator) -> None:
    generator._validate_image_tag("eclipse-temurin:21-jdk-alpine")  # no raise


# ---------------------------------------------------------------------------
# 7. generate — builder_image=latest → InvalidImageError
# ---------------------------------------------------------------------------


def test_generate_builder_latest_raises(
    generator: DockerfileGenerator,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    bad_plan = BuildPlan(
        builder_image="eclipse-temurin:latest",
        runner_image="eclipse-temurin:21-jre-alpine",
        build_cmd="./gradlew bootJar --no-daemon",
        artifact_path="build/libs/app.jar",
    )
    with pytest.raises(InvalidImageError, match="latest"):
        generator.generate(bad_plan, user_inputs, resource_defaults)


# ---------------------------------------------------------------------------
# 8. generate — runner_image=latest → InvalidImageError
# ---------------------------------------------------------------------------


def test_generate_runner_latest_raises(
    generator: DockerfileGenerator,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    bad_plan = BuildPlan(
        builder_image="eclipse-temurin:21-jdk-alpine",
        runner_image="eclipse-temurin:latest",
        build_cmd="./gradlew bootJar --no-daemon",
        artifact_path="build/libs/app.jar",
    )
    with pytest.raises(InvalidImageError, match="latest"):
        generator.generate(bad_plan, user_inputs, resource_defaults)


# ---------------------------------------------------------------------------
# 9. generate — 비root 사용자 지시자 포함: addgroup, adduser, USER appuser
#    (v0.1.1 이후: alpine 호환 busybox 유틸)
# ---------------------------------------------------------------------------


def test_generate_non_root_directives(
    generator: DockerfileGenerator,
    gradle_build_plan: BuildPlan,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    result = generator.generate(gradle_build_plan, user_inputs, resource_defaults)

    assert "addgroup" in result
    assert "adduser" in result
    assert "USER appuser" in result


# ---------------------------------------------------------------------------
# 10. generate — 보안 주석 포함: 한국어 "비root 사용자", "latest 태그 금지", "COPY --chown"
# ---------------------------------------------------------------------------


def test_generate_security_comments(
    generator: DockerfileGenerator,
    gradle_build_plan: BuildPlan,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    result = generator.generate(gradle_build_plan, user_inputs, resource_defaults)

    assert "비root 사용자" in result
    assert "latest 태그 금지" in result
    assert "COPY --chown" in result


# ---------------------------------------------------------------------------
# 11. generate — EXPOSE 포트: UserInputs.port=9000 → EXPOSE 9000
# ---------------------------------------------------------------------------


def test_generate_expose_port(
    generator: DockerfileGenerator,
    gradle_build_plan: BuildPlan,
    resource_defaults: ResourceDefaults,
) -> None:
    inputs = UserInputs(
        app_name="my-app",
        port=9000,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    result = generator.generate(gradle_build_plan, inputs, resource_defaults)
    assert "EXPOSE 9000" in result


# ---------------------------------------------------------------------------
# 12. generate — 결정론 (cksum 동일): 같은 입력으로 2번 render → SHA-256 동일
# ---------------------------------------------------------------------------


def test_generate_determinism(
    generator: DockerfileGenerator,
    gradle_build_plan: BuildPlan,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    result1 = generator.generate(gradle_build_plan, user_inputs, resource_defaults)
    result2 = generator.generate(gradle_build_plan, user_inputs, resource_defaults)

    sha1 = hashlib.sha256(result1.encode()).hexdigest()
    sha2 = hashlib.sha256(result2.encode()).hexdigest()
    assert sha1 == sha2


# ---------------------------------------------------------------------------
# 13. generate — Gradle 캐시 레이어: gradle wrapper + dependencies 관련 명령
# ---------------------------------------------------------------------------


def test_generate_gradle_cache_layer(
    generator: DockerfileGenerator,
    gradle_build_plan: BuildPlan,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    result = generator.generate(gradle_build_plan, user_inputs, resource_defaults)

    # v0.1.1: 시스템 gradle 사용 — build.gradle* 스크립트만 먼저 복사 + dependencies warmup.
    assert "COPY build.gradle" in result
    assert "dependencies" in result


# ---------------------------------------------------------------------------
# 14. generate — Maven 캐시 레이어: dependency:go-offline 포함
# ---------------------------------------------------------------------------


def test_generate_maven_cache_layer(
    generator: DockerfileGenerator,
    maven_build_plan: BuildPlan,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    result = generator.generate(maven_build_plan, user_inputs, resource_defaults)

    assert "dependency:go-offline" in result


# ---------------------------------------------------------------------------
# 15. generate — artifact_path 반영: COPY --from=builder ... artifact_path
# ---------------------------------------------------------------------------


def test_generate_artifact_path(
    generator: DockerfileGenerator,
    gradle_build_plan: BuildPlan,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    result = generator.generate(gradle_build_plan, user_inputs, resource_defaults)

    assert gradle_build_plan.artifact_path in result


# ---------------------------------------------------------------------------
# 16. generate — USER appuser가 ENTRYPOINT 직전 위치
# ---------------------------------------------------------------------------


def test_generate_user_before_entrypoint(
    generator: DockerfileGenerator,
    gradle_build_plan: BuildPlan,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    result = generator.generate(gradle_build_plan, user_inputs, resource_defaults)

    lines = [line.strip() for line in result.splitlines()]
    # USER appuser 와 ENTRYPOINT 위치 확인
    user_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("USER appuser")), -1
    )
    entrypoint_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("ENTRYPOINT")), -1
    )
    assert user_idx != -1, "USER appuser 지시어가 없음"
    assert entrypoint_idx != -1, "ENTRYPOINT 지시어가 없음"
    assert user_idx < entrypoint_idx, "USER appuser가 ENTRYPOINT 이전에 있어야 함"
    # ENTRYPOINT 바로 전 비어있지 않은 라인이 USER appuser여야 함
    non_empty_before = [
        lines[i] for i in range(entrypoint_idx - 1, -1, -1) if lines[i].strip()
    ]
    assert non_empty_before[0].startswith("USER appuser"), (
        f"ENTRYPOINT 직전 비어있지 않은 라인이 USER appuser가 아님: {non_empty_before[0]!r}"
    )


# ---------------------------------------------------------------------------
# 17. _validate_image_tag — 개행 포함 이미지 참조 거부 (Important 1: 인젝션 차단)
# ---------------------------------------------------------------------------


def test_validate_image_tag_rejects_newline(generator: DockerfileGenerator) -> None:
    with pytest.raises(InvalidImageError):
        generator._validate_image_tag("alpine:3.19\nUSER root\n")


# ---------------------------------------------------------------------------
# 18. _validate_image_tag — latest+digest 우회 시도 거부 (Important 1)
# ---------------------------------------------------------------------------


def test_validate_image_tag_rejects_latest_with_digest_bypass(
    generator: DockerfileGenerator,
) -> None:
    # "alpine:latest@sha256:<64 hex>" — digest 존재해도 latest 태그 명시 거부
    digest = "a" * 64
    with pytest.raises(InvalidImageError, match="latest"):
        generator._validate_image_tag(f"alpine:latest@sha256:{digest}")


# ---------------------------------------------------------------------------
# 19. _validate_image_tag — 태그+digest 조합 허용 (Important 1)
# ---------------------------------------------------------------------------


def test_validate_image_tag_accepts_tag_with_digest(
    generator: DockerfileGenerator,
) -> None:
    digest = "a" * 64
    # no raise
    generator._validate_image_tag(f"eclipse-temurin:21-jdk-alpine@sha256:{digest}")


# ---------------------------------------------------------------------------
# 20. _validate_image_tag — 짧은 digest 거부 (Important 1: 64 hex 미달)
# ---------------------------------------------------------------------------


def test_validate_image_tag_rejects_short_digest(
    generator: DockerfileGenerator,
) -> None:
    with pytest.raises(InvalidImageError):
        generator._validate_image_tag("alpine@sha256:abc123")


# ---------------------------------------------------------------------------
# 21. generate — build_cmd에 개행 포함 시 거부 (Important 2)
# ---------------------------------------------------------------------------


def test_generate_rejects_build_cmd_with_newline(
    generator: DockerfileGenerator,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    bad_plan = BuildPlan(
        builder_image="eclipse-temurin:21-jdk-alpine",
        runner_image="eclipse-temurin:21-jre-alpine",
        build_cmd="gradle bootJar\nRUN evil",
        artifact_path="build/libs/app.jar",
    )
    with pytest.raises(InvalidImageError):
        generator.generate(bad_plan, user_inputs, resource_defaults)


# ---------------------------------------------------------------------------
# 22. generate — artifact_path에 개행 포함 시 거부 (Important 2 / 4)
# ---------------------------------------------------------------------------


def test_generate_rejects_artifact_path_with_newline(
    generator: DockerfileGenerator,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    bad_plan = BuildPlan(
        builder_image="eclipse-temurin:21-jdk-alpine",
        runner_image="eclipse-temurin:21-jre-alpine",
        build_cmd="./gradlew bootJar --no-daemon",
        artifact_path="build/libs/*.jar\nEXPOSE 22",
    )
    with pytest.raises(InvalidImageError):
        generator.generate(bad_plan, user_inputs, resource_defaults)


# ---------------------------------------------------------------------------
# 23. _detect_build_system — 토큰 분해: gradle 후 maven 주석어가 와도 gradle 반환 (Important 3)
# ---------------------------------------------------------------------------


def test_detect_build_system_ignores_comment_tokens(
    generator: DockerfileGenerator,
    user_inputs: UserInputs,
    resource_defaults: ResourceDefaults,
) -> None:
    """'gradle wrapper # using maven-style' 같은 문구는 gradle로 판정해야 함."""
    from scripts.dockerfile_generator import _detect_build_system

    result = _detect_build_system("gradle wrapper # using maven-style")
    assert result == "gradle"


# ---------------------------------------------------------------------------
# 24. _detect_build_system — ./mvnw → maven (Important 3)
# ---------------------------------------------------------------------------


def test_detect_build_system_mvnw(
    generator: DockerfileGenerator,
) -> None:
    from scripts.dockerfile_generator import _detect_build_system

    result = _detect_build_system("./mvnw package -DskipTests")
    assert result == "maven"
