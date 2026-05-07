"""JVM 매니페스트 4종 byte-identical 골든 스냅샷 테스트.

BL-001 Phase 1 (NFR-04 d-jvm) — Phase 3/4의 `generate_deployment` / `generate_statefulset` UID
동적화와 `StackModule.build_plan` Protocol 확장이 JVM 출력을 변경하지 않음을 증명하는 안전망.

fixture는 재현성을 위해 고정값으로 구성한다. 절대 변경 금지.

골든 최초 생성/갱신:
    UPDATE_GOLDEN=1 uv run pytest tests/test_manifest_jvm_golden.py

일반 실행:
    uv run pytest tests/test_manifest_jvm_golden.py
    → 골든과 byte-identical 비교. 불일치 시 실패.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts._shared.types import (
    AnalysisResult,
    BuildPlan,
    ClusterConfig,
    ProbeConfig,
    ProbeSpec,
    ResourceDefaults,
    StackDetectResult,
    StatefulnessSignal,
    UserInputs,
)
from scripts.manifest_generator import ManifestGenerator
from scripts.template_renderer import TemplateRenderer

PROJECT_ROOT = Path(__file__).parent.parent
SNAPSHOTS_DIR = PROJECT_ROOT / "tests" / "snapshots" / "jvm"


# ─────────────────────────────────────────────────────
# 고정 fixture — 절대 변경 금지 (골든 재현성)
# ─────────────────────────────────────────────────────

_INPUTS = UserInputs(
    app_name="jvm-app",
    port=8080,
    exposure="ClusterIP",
    namespace="default",
    output_dir=Path("/tmp/out"),
    resource_hint="medium",
    replicas=2,
)

_DEFAULTS = ResourceDefaults(
    cpu_request="100m",
    memory_request="512Mi",
    cpu_limit="1000m",
    memory_limit="1Gi",
    writable_paths=["/tmp", "/var/log"],
)

_PROBE = ProbeConfig(
    liveness=ProbeSpec(kind="http", path="/actuator/health/liveness", port=8080),
    readiness=ProbeSpec(kind="http", path="/actuator/health/readiness", port=8080),
)

_DETECT = StackDetectResult(
    port=8080,
    entrypoint="",
    framework="spring-boot",
    version="3.2.0",
    build_system="gradle",
    actuator_enabled=True,
)

_BUILD_PLAN = BuildPlan(
    builder_image="gradle:jdk21-alpine",
    runner_image="eclipse-temurin:21-jre-alpine",
    build_cmd="gradle --no-daemon bootJar",
    artifact_path="build/libs/*.jar",
)

_ANALYSIS = AnalysisResult(
    stack="jvm",
    detect_result=_DETECT,
    build_plan=_BUILD_PLAN,
    probe_config=_PROBE,
    defaults=_DEFAULTS,
    artifact_paths=[Path("build/libs/app.jar")],
    selected_module=None,
    statefulness=StatefulnessSignal(
        is_stateful=True, confidence="high", reasons=["golden fixture"]
    ),
    gaps=[],
)

_CLUSTER = ClusterConfig(
    preset="orbstack",
    storage_class="local-path",
    network_policy=True,
)

_IMAGE = "local/test:1.0.0"


# ─────────────────────────────────────────────────────
# 골든 비교 헬퍼
# ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def generator() -> ManifestGenerator:
    renderer = TemplateRenderer(PROJECT_ROOT / "templates")
    return ManifestGenerator(renderer)


def _assert_golden(name: str, actual: str) -> None:
    """byte-identical 골든 비교. `UPDATE_GOLDEN=1`이면 최신 출력으로 갱신 후 skip."""
    golden = SNAPSHOTS_DIR / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual)
        pytest.skip(f"골든 갱신됨: {golden.relative_to(PROJECT_ROOT)}")
    if not golden.exists():
        raise FileNotFoundError(
            f"골든 스냅샷 누락: {golden.relative_to(PROJECT_ROOT)}. "
            f"최초 락다운 시 `UPDATE_GOLDEN=1 uv run pytest {Path(__file__).name}` 실행."
        )
    expected = golden.read_text()
    assert actual == expected, (
        f"골든 스냅샷 불일치: {name}\n"
        f"expected ({len(expected)} bytes) != actual ({len(actual)} bytes)"
    )


# ─────────────────────────────────────────────────────
# 골든 비교 테스트 (4종)
# ─────────────────────────────────────────────────────


def test_jvm_deployment_golden(generator: ManifestGenerator) -> None:
    actual = generator.generate_deployment(
        _INPUTS, _ANALYSIS, _DEFAULTS, _PROBE, image=_IMAGE
    )
    _assert_golden("deployment.yaml", actual)


def test_jvm_service_golden(generator: ManifestGenerator) -> None:
    actual = generator.generate_service(_INPUTS)
    _assert_golden("service.yaml", actual)


def test_jvm_serviceaccount_golden(generator: ManifestGenerator) -> None:
    actual = generator.generate_serviceaccount(_INPUTS)
    _assert_golden("serviceaccount.yaml", actual)


def test_jvm_statefulset_golden(generator: ManifestGenerator) -> None:
    actual = generator.generate_statefulset(_INPUTS, _ANALYSIS, _CLUSTER, image=_IMAGE)
    _assert_golden("statefulset.yaml", actual)


def test_jvm_networkpolicy_golden(generator: ManifestGenerator) -> None:
    """BL-018: networkpolicy 첫 골든 — Jinja2 전환과 함께 도입.

    fixture는 deny-all + 단일 ingress + 단일 egress 조합으로 `{% for %}` 루프 커버.
    """
    actual = generator.generate_networkpolicy(
        _INPUTS,
        _CLUSTER,
        allow_ingress_from=[{"namespace": "frontend", "port": 8080}],
        allow_egress_to=[{"namespace": "db", "port": 5432}],
    )
    assert actual is not None
    _assert_golden("networkpolicy.yaml", actual)
