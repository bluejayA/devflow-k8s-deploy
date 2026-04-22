"""ManifestGenerator.generate_statefulset() 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

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


def _make_inputs(**kwargs: object) -> UserInputs:
    defaults = dict(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP",
        namespace="default",
        output_dir=Path("/tmp/out"),
        resource_hint="small",
        replicas=1,
    )
    defaults.update(kwargs)
    return UserInputs(**defaults)


def _make_analysis(**kwargs: object) -> AnalysisResult:
    defaults = dict(
        stack="jvm",
        detect_result=StackDetectResult(
            port=8080, entrypoint="", framework="spring-boot", version="3.2.0"
        ),
        build_plan=BuildPlan(
            builder_image="eclipse-temurin:21",
            runner_image="eclipse-temurin:21-jre",
            build_cmd="./gradlew bootJar",
            artifact_path="build/libs/app.jar",
        ),
        probe_config=ProbeConfig(
            liveness=ProbeSpec(kind="http", path="/actuator/health/liveness", port=8080),
            readiness=ProbeSpec(kind="http", path="/actuator/health/readiness", port=8080),
        ),
        defaults=ResourceDefaults(
            cpu_request="125m",
            memory_request="256Mi",
            cpu_limit="500m",
            memory_limit="512Mi",
            writable_paths=["/tmp"],
        ),
        artifact_paths=[Path("build/libs/app.jar")],
        selected_module=None,
        statefulness=StatefulnessSignal(
            is_stateful=True, confidence="high", reasons=["DB 연결 감지"]
        ),
        gaps=[],
    )
    defaults.update(kwargs)
    return AnalysisResult(**defaults)


def _make_cluster_config(**kwargs: object) -> ClusterConfig:
    defaults = dict(preset="orbstack", storage_class="local-path", network_policy=True)
    defaults.update(kwargs)
    return ClusterConfig(**defaults)


class TestGenerateStatefulset:
    def _make_generator(self) -> ManifestGenerator:
        renderer = TemplateRenderer(PROJECT_ROOT / "templates")
        return ManifestGenerator(renderer)

    def test_generate_statefulset_basic_yaml(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster)
        doc = yaml.safe_load(yaml_str)

        assert doc["kind"] == "StatefulSet"
        assert doc["apiVersion"] == "apps/v1"
        assert doc["metadata"]["name"] == "my-app"
        assert doc["spec"]["replicas"] == 1

    def test_generate_statefulset_volume_claim_templates(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster)
        doc = yaml.safe_load(yaml_str)

        vcts = doc["spec"]["volumeClaimTemplates"]
        assert isinstance(vcts, list)
        assert len(vcts) >= 1
        vct = vcts[0]
        assert vct["spec"]["accessModes"] == ["ReadWriteOnce"]
        assert "storage" in vct["spec"]["resources"]["requests"]

    def test_generate_statefulset_orbstack_storage_class(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config(storage_class="local-path")

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster)
        doc = yaml.safe_load(yaml_str)

        vct = doc["spec"]["volumeClaimTemplates"][0]
        assert vct["spec"]["storageClassName"] == "local-path"

    def test_generate_statefulset_storage_class_none(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config(storage_class=None)

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster)
        doc = yaml.safe_load(yaml_str)

        vct = doc["spec"]["volumeClaimTemplates"][0]
        assert "storageClassName" not in vct["spec"]

    def test_generate_statefulset_storage_size_invalid(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config()

        with pytest.raises(ValueError, match="storage_size"):
            gen.generate_statefulset(inputs, analysis, cluster, storage_size="not-valid")

    def test_generate_statefulset_injection_defense(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config(storage_class="local-path\nmalicious: true")

        with pytest.raises(ValueError):
            gen.generate_statefulset(inputs, analysis, cluster)
