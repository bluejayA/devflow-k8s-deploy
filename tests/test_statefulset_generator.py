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

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")
        doc = yaml.safe_load(yaml_str)

        assert doc["kind"] == "StatefulSet"
        assert doc["apiVersion"] == "apps/v1"
        assert doc["metadata"]["name"] == "my-app"
        assert doc["spec"]["replicas"] == 1
        container = doc["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "myrepo/app:1.0.0"

    def test_generate_statefulset_container_security_context(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")
        doc = yaml.safe_load(yaml_str)

        sec = doc["spec"]["template"]["spec"]["containers"][0]["securityContext"]
        assert sec["allowPrivilegeEscalation"] is False
        assert sec["readOnlyRootFilesystem"] is True
        assert sec.get("privileged") is False
        assert sec["capabilities"]["drop"] == ["ALL"]

    def test_generate_statefulset_volume_claim_templates(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")
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

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")
        doc = yaml.safe_load(yaml_str)

        vct = doc["spec"]["volumeClaimTemplates"][0]
        assert vct["spec"]["storageClassName"] == "local-path"

    def test_generate_statefulset_storage_class_none(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config(storage_class=None)

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")
        doc = yaml.safe_load(yaml_str)

        vct = doc["spec"]["volumeClaimTemplates"][0]
        assert "storageClassName" not in vct["spec"]

    def test_generate_statefulset_storage_size_invalid(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config()

        with pytest.raises(ValueError, match="storage_size"):
            gen.generate_statefulset(
                inputs, analysis, cluster, image="myrepo/app:1.0.0", storage_size="not-valid"
            )

    def test_generate_statefulset_has_probes(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")
        doc = yaml.safe_load(yaml_str)

        container = doc["spec"]["template"]["spec"]["containers"][0]
        assert "livenessProbe" in container, "livenessProbe 누락 — PRB-001 FAIL"
        assert "readinessProbe" in container, "readinessProbe 누락 — PRB-002 FAIL"
        assert container["livenessProbe"]["httpGet"]["path"] == "/actuator/health/liveness"
        assert container["readinessProbe"]["httpGet"]["path"] == "/actuator/health/readiness"

    def test_generate_statefulset_injection_defense(self) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config(storage_class="local-path\nmalicious: true")

        with pytest.raises(ValueError):
            gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")

    def test_generate_statefulset_run_as_user_dynamic(self) -> None:
        """F-31: statefulset runAsUser/Group/fsGroup은 defaults.run_as_user 기반."""
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis(
            defaults=ResourceDefaults(
                cpu_request="50m",
                memory_request="64Mi",
                cpu_limit="250m",
                memory_limit="128Mi",
                writable_paths=["/tmp"],
                run_as_user=65532,
            )
        )
        cluster = _make_cluster_config()

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")
        doc = yaml.safe_load(yaml_str)
        pod_sec = doc["spec"]["template"]["spec"]["securityContext"]

        assert pod_sec["runAsUser"] == 65532
        assert pod_sec["runAsGroup"] == 65532
        assert pod_sec["fsGroup"] == 65532


# ──────────────────────────────────────────────────────────────────────────────
# BL-018: parsed YAML deep-equality baseline (Jinja2 전환 안전망)
# ──────────────────────────────────────────────────────────────────────────────


_BL018_STATEFULSET_BASELINE: dict[str, object] = {
    "apiVersion": "apps/v1",
    "kind": "StatefulSet",
    "metadata": {"name": "my-app", "namespace": "default"},
    "spec": {
        "replicas": 1,
        "serviceName": "my-app",
        "selector": {"matchLabels": {"app": "my-app"}},
        "template": {
            "metadata": {"labels": {"app": "my-app"}},
            "spec": {
                "serviceAccountName": "my-app-sa",
                "automountServiceAccountToken": False,
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 1000,
                    "runAsGroup": 1000,
                    "fsGroup": 1000,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [
                    {
                        "name": "my-app",
                        "image": "myrepo/app:1.0.0",
                        "ports": [{"containerPort": 8080, "protocol": "TCP"}],
                        "livenessProbe": {
                            "httpGet": {"path": "/actuator/health/liveness", "port": 8080},
                            "initialDelaySeconds": 10,
                            "periodSeconds": 10,
                        },
                        "readinessProbe": {
                            "httpGet": {"path": "/actuator/health/readiness", "port": 8080},
                            "initialDelaySeconds": 5,
                            "periodSeconds": 5,
                        },
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "privileged": False,
                            "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "resources": {
                            "requests": {"cpu": "125m", "memory": "256Mi"},
                            "limits": {"cpu": "500m", "memory": "512Mi"},
                        },
                        "volumeMounts": [
                            {"name": "tmp", "mountPath": "/tmp"},
                            {"name": "data", "mountPath": "/data"},
                        ],
                    }
                ],
                "volumes": [{"name": "tmp", "emptyDir": {}}],
            },
        },
        "volumeClaimTemplates": [
            {
                "metadata": {"name": "data"},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "resources": {"requests": {"storage": "1Gi"}},
                    "storageClassName": "local-path",
                },
            }
        ],
    },
}


class TestBL018StatefulsetParsedEquivalence:
    """BL-018: dict+yaml.dump → Jinja2 전환 시 parsed dict 의미 보존 가드.

    이전 출력의 parsed 결과를 baseline으로 박제. 신규 statefulset.tmpl이
    동일 시멘틱(deep-equality)을 유지하는지 회귀 보호.
    """

    def test_statefulset_parsed_equivalent_to_baseline(self) -> None:
        renderer = TemplateRenderer(PROJECT_ROOT / "templates")
        gen = ManifestGenerator(renderer)
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")
        doc = yaml.safe_load(yaml_str)

        assert doc == _BL018_STATEFULSET_BASELINE

    def test_statefulset_parsed_storage_class_none_baseline(self) -> None:
        """storage_class=None 시 storageClassName 키 자체가 부재해야 함."""
        renderer = TemplateRenderer(PROJECT_ROOT / "templates")
        gen = ManifestGenerator(renderer)
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config(storage_class=None)

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")
        doc = yaml.safe_load(yaml_str)

        vct_spec = doc["spec"]["volumeClaimTemplates"][0]["spec"]
        assert vct_spec == {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "1Gi"}},
        }
        assert "storageClassName" not in vct_spec

    def test_statefulset_storage_class_empty_string_emits_field(self) -> None:
        """BL-018 R2 (Codex adversarial MEDIUM): storage_class='' vs None 분리.

        K8s PVC semantics:
          - missing field: cluster default StorageClass 사용
          - storageClassName: '': 동적 프로비저닝 비활성화 (다른 의미)

        이전 dict 경로는 `is not None` 분기로 ''에서 storageClassName 키를 emit했으나
        Jinja2 전환 시 `{% if storage_class %}` falsy 검사로 변경되어 ''에서 키 누락.
        해당 분기를 명시 None 검사로 교정 + 회귀 가드.
        """
        renderer = TemplateRenderer(PROJECT_ROOT / "templates")
        gen = ManifestGenerator(renderer)
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config(storage_class="")

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")
        doc = yaml.safe_load(yaml_str)

        vct_spec = doc["spec"]["volumeClaimTemplates"][0]["spec"]
        # 키가 emit되어야 함 (None과 구분)
        assert "storageClassName" in vct_spec, (
            "storage_class=''는 storageClassName: '' 형태로 emit되어야 함 — "
            "K8s 동적 프로비저닝 비활성화 의미 보존"
        )
        assert vct_spec["storageClassName"] == ""


# ──────────────────────────────────────────────────────────────────────────────
# BL-018 R3: storage_class 입력 검증 + tojson defense-in-depth
# (Codex adversarial round 2 finding HIGH)
# ──────────────────────────────────────────────────────────────────────────────


class TestBL018StorageClassValidation:
    """BL-018 R3: storage_class trust boundary 검증.

    이전 R2 회귀: storageClassName: \"{{ storage_class }}\" 수동 quoting은
    값에 `\"` 또는 `\\\\` 포함 시 YAML 깨뜨림.
    Codex 재현: storage_class='foo\"bar' → 파서 실패.

    수정: K8s StorageClass name 규칙(DNS-1123 subdomain) 검증 + tojson 안전 직렬화.
    빈 문자열은 K8s 동적 프로비저닝 비활성화 sentinel로 명시 허용.
    """

    def _make_generator(self) -> ManifestGenerator:
        return ManifestGenerator(TemplateRenderer(PROJECT_ROOT / "templates"))

    @pytest.mark.parametrize(
        "bad_storage_class",
        [
            'foo"bar',          # 더블쿼트 — YAML quoted scalar 깨뜨림
            "back\\slash",      # 백슬래시 — escape 시퀀스
            "UPPERCASE",        # DNS-1123 위반 (대문자)
            "starts.with.dot.", # 끝이 점/하이픈
            ".leading-dot",     # 시작이 점/하이픈
            "under_score",      # underscore (DNS-1123 위반)
            "with space",       # 공백
            "with#comment",     # YAML 메타문자
            "with:colon",       # YAML 메타문자
            "x" * 254,          # 길이 초과 (>253 DNS-1123 subdomain 한도)
        ],
    )
    def test_invalid_storage_class_rejected(self, bad_storage_class: str) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config(storage_class=bad_storage_class)

        with pytest.raises(ValueError, match="storage_class"):
            gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")

    @pytest.mark.parametrize(
        "valid_storage_class",
        [
            "",                           # K8s 동적 프로비저닝 비활성화 sentinel
            "local-path",                 # 기본 케이스
            "local-path.production",      # subdomain dot 허용
            "fast-ssd",                   # 일반 case
            "a",                          # 최소 1자
            "a" + ".a" * 126,             # 최대 253자 (다중 세그먼트, 각 ≤63자)
        ],
    )
    def test_valid_storage_class_accepted(self, valid_storage_class: str) -> None:
        gen = self._make_generator()
        inputs = _make_inputs()
        analysis = _make_analysis()
        cluster = _make_cluster_config(storage_class=valid_storage_class)

        yaml_str = gen.generate_statefulset(inputs, analysis, cluster, image="myrepo/app:1.0.0")
        doc = yaml.safe_load(yaml_str)

        vct_spec = doc["spec"]["volumeClaimTemplates"][0]["spec"]
        assert "storageClassName" in vct_spec
        assert vct_spec["storageClassName"] == valid_storage_class
