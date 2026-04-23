"""Codex 리뷰 (2026-04-22, PR #3) 지적 3건 수정 검증.

- P1-a: `COPY gradle gradle` 제거로 Version Catalog(gradle/libs.versions.toml)
        또는 convention scripts 프로젝트 빌드 실패 → `gradle/` 존재 시 조건부 COPY.
- P1-b: `COPY src ./src` 하드코딩이 multi-module 레이아웃 즉시 실패 →
        `COPY . .` 원복 + `.dockerignore` 템플릿 동반 생성으로 context pollution 방어.
- P2 : imagePullPolicy 주석 "tag mutation 재푸시 시 갱신 보장"은 IfNotPresent
        실동작과 반대 → non-mutable tag 전제 문구로 교체.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts._shared.types import BuildPlan, ResourceDefaults, UserInputs
from scripts.dockerfile_generator import DockerfileGenerator
from scripts.manifest_generator import ManifestGenerator
from scripts.stacks.jvm import JvmStackModule
from scripts.template_renderer import TemplateRenderer
from tests.conftest import auto_inject_generate

PROJECT_ROOT = Path(__file__).parent.parent


def _renderer() -> TemplateRenderer:
    return TemplateRenderer(PROJECT_ROOT / "templates")


def _make_generator() -> DockerfileGenerator:
    # BL-015: generate() 시그니처에 stack_module/detect_result 필수가 되면서,
    # 테스트 호출부 수정 최소화를 위해 auto-inject 래퍼 적용.
    gen = DockerfileGenerator(_renderer())
    auto_inject_generate(gen, JvmStackModule())
    return gen


def _make_inputs() -> UserInputs:
    return UserInputs(
        app_name="sample",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/out"),
        resource_hint="medium",
    )


def _make_defaults() -> ResourceDefaults:
    return ResourceDefaults(
        cpu_request="100m",
        memory_request="512Mi",
        cpu_limit="1000m",
        memory_limit="1Gi",
        writable_paths=["/tmp"],
    )


def _gradle_plan() -> BuildPlan:
    return BuildPlan(
        builder_image="gradle:jdk21-alpine",
        runner_image="eclipse-temurin:21-jre-alpine",
        build_cmd="gradle --no-daemon bootJar",
        artifact_path="build/libs/*.jar",
    )


# ---------------------------------------------------------------------------
# P1-b: multi-module 지원 — COPY . . + .dockerignore
# ---------------------------------------------------------------------------


def test_dockerfile_uses_full_context_copy(tmp_path: Path) -> None:
    """`COPY . .`로 복원되어 multi-module 루트(src 없음) 지원."""
    gen = _make_generator()
    out = gen.generate(_gradle_plan(), _make_inputs(), _make_defaults(), project_dir=tmp_path)

    assert "COPY . ." in out, "multi-module 지원을 위해 전체 context COPY 필요"
    assert "COPY src ./src" not in out, "하드코딩된 src COPY는 multi-module 레이아웃에서 실패"


def test_dockerfile_generator_emits_dockerignore(tmp_path: Path) -> None:
    """DockerfileGenerator가 .dockerignore 내용도 함께 생성 (context pollution 방어)."""
    gen = _make_generator()
    # 신규 API: generate_dockerignore() 메서드
    ignore = gen.generate_dockerignore()

    # 필수 제외 엔트리: 빌드 산출물 + VCS + 시크릿 + 출력 디렉토리
    for pattern in [".git", "build", "target", ".gradle", "k8s-output", ".env"]:
        assert pattern in ignore, f".dockerignore에 {pattern!r} 제외 엔트리 필요"


# ---------------------------------------------------------------------------
# P1-a: gradle/ 디렉토리 조건부 COPY (Version Catalog 지원)
# ---------------------------------------------------------------------------


def test_dockerfile_includes_gradle_dir_when_present(tmp_path: Path) -> None:
    """project_dir에 gradle/ 존재 시 dep cache 레이어가 해당 디렉토리도 COPY.

    이유: gradle/libs.versions.toml (Version Catalog), gradle/*.gradle.kts (convention
    plugins)를 쓰는 현대 Gradle 프로젝트가 `dependencies`/`bootJar`에서 실패하지 않도록.
    """
    (tmp_path / "gradle").mkdir()
    (tmp_path / "gradle" / "libs.versions.toml").write_text(
        "[libraries]\nspring = { module = 'org.springframework:spring-core', version = '6.0.0' }\n",
        encoding="utf-8",
    )

    gen = _make_generator()
    out = gen.generate(_gradle_plan(), _make_inputs(), _make_defaults(), project_dir=tmp_path)

    # 대소문자 관계없이 gradle dir COPY가 포함되어야 함
    assert "COPY gradle" in out, "gradle/ 존재 시 dep cache 레이어가 해당 디렉토리 COPY 필요"


def test_dockerfile_omits_gradle_dir_when_absent(tmp_path: Path) -> None:
    """project_dir에 gradle/ 없으면 `COPY gradle` 부재 (Docker build 즉시 실패 방지)."""
    gen = _make_generator()
    out = gen.generate(_gradle_plan(), _make_inputs(), _make_defaults(), project_dir=tmp_path)

    # 어떠한 `COPY gradle ` 시퀀스도 없어야 함 (gradle.properties*는 별개 패턴이라 OK)
    assert "COPY gradle\n" not in out
    assert "COPY gradle " not in out or "COPY gradle.properties" in out


# ---------------------------------------------------------------------------
# P2: imagePullPolicy 주석 정정
# ---------------------------------------------------------------------------


def test_deployment_pull_policy_comment_matches_actual_behavior() -> None:
    """주석이 IfNotPresent 실동작과 일치해야 함.

    `IfNotPresent`는 캐시된 태그 있으면 재pull 안 함 — tag mutation 감지 불가.
    주석은 'non-mutable tag 전제' 또는 'digest pinning 권장'으로 표현되어야 함.
    """
    from tests.test_orchestrator import _make_analysis_result

    gen = ManifestGenerator(_renderer())
    analysis = _make_analysis_result()
    yaml_str = gen.generate_deployment(
        _make_inputs(),
        analysis,
        analysis.defaults,
        analysis.probe_config,
        image="myregistry/app:1.0.0",
    )

    # 잘못된 설명(tag mutation에 대해 refresh 보장) 금지
    assert "tag mutation 재푸시 시 갱신 보장" not in yaml_str
    assert "재푸시 시 갱신" not in yaml_str

    # pullpolicy 자체는 여전히 존재
    doc = yaml.safe_load(yaml_str)
    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert container["imagePullPolicy"] == "IfNotPresent"
