"""TDD: ManifestGenerator — Deployment/Service/ServiceAccount YAML 생성기.

RED → GREEN → REFACTOR 순서.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from scripts._shared.errors import InvalidImageError
from scripts._shared.types import (
    AnalysisResult,
    BuildPlan,
    ProbeConfig,
    ProbeSpec,
    ResourceDefaults,
    StackDetectResult,
    StatefulnessSignal,
    UserInputs,
)
from scripts.manifest_generator import ManifestGenerator
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
def generator(renderer: TemplateRenderer) -> ManifestGenerator:
    return ManifestGenerator(renderer)


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


@pytest.fixture()
def http_probe_config() -> ProbeConfig:
    return ProbeConfig(
        liveness=ProbeSpec(kind="http", path="/actuator/health/liveness", port=8080),
        readiness=ProbeSpec(kind="http", path="/actuator/health/readiness", port=8080),
    )


@pytest.fixture()
def tcp_probe_config() -> ProbeConfig:
    return ProbeConfig(
        liveness=ProbeSpec(kind="tcp", path=None, port=8080),
        readiness=ProbeSpec(kind="tcp", path=None, port=8080),
    )


@pytest.fixture()
def analysis_result(
    http_probe_config: ProbeConfig, resource_defaults: ResourceDefaults
) -> AnalysisResult:
    return AnalysisResult(
        stack="jvm",
        detect_result=StackDetectResult(
            port=8080,
            entrypoint="java -jar app.jar",
            framework="spring-boot",
            version="3.2.0",
            build_system="gradle",
            actuator_enabled=True,
        ),
        build_plan=BuildPlan(
            builder_image="eclipse-temurin:21-jdk-alpine",
            runner_image="eclipse-temurin:21-jre-alpine",
            build_cmd="./gradlew bootJar --no-daemon",
            artifact_path="build/libs/app.jar",
        ),
        probe_config=http_probe_config,
        defaults=resource_defaults,
        artifact_paths=[Path("build/libs/app.jar")],
        selected_module=None,
        statefulness=StatefulnessSignal(is_stateful=False, confidence="high", reasons=[]),
        gaps=[],
    )


# ---------------------------------------------------------------------------
# generate_deployment テスト
# ---------------------------------------------------------------------------


# 1. basic deployment 생성 → YAML 파싱 가능, kind=Deployment
def test_generate_deployment_parseable_yaml(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    assert doc["kind"] == "Deployment"
    assert doc["apiVersion"] == "apps/v1"


# 2. metadata.name/namespace = inputs 값
def test_generate_deployment_metadata(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    assert doc["metadata"]["name"] == "my-app"
    assert doc["metadata"]["namespace"] == "dev"


# 3. replicas == 2 (default)
def test_generate_deployment_replicas(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    assert doc["spec"]["replicas"] == 2


# 3b. replicas 설정값이 deployment spec.replicas에 반영됨
def test_generate_deployment_custom_replicas(
    generator: ManifestGenerator,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    inputs = UserInputs(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
        replicas=5,
    )
    result = generator.generate_deployment(
        inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    assert doc["spec"]["replicas"] == 5


# 4. serviceAccountName == '{app_name}-sa'
def test_generate_deployment_service_account_name(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    pod_spec = doc["spec"]["template"]["spec"]
    assert pod_spec["serviceAccountName"] == "my-app-sa"


# 5. automountServiceAccountToken == False (Pod 레벨)
def test_generate_deployment_automount_sa_false(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    pod_spec = doc["spec"]["template"]["spec"]
    assert pod_spec["automountServiceAccountToken"] is False


# 6. Pod securityContext: runAsNonRoot, runAsUser=1000, fsGroup=1000,
#    seccompProfile.type=RuntimeDefault
def test_generate_deployment_pod_security_context(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    sc = doc["spec"]["template"]["spec"]["securityContext"]
    assert sc["runAsNonRoot"] is True
    assert sc["runAsUser"] == 1000
    assert sc["fsGroup"] == 1000
    assert sc["seccompProfile"]["type"] == "RuntimeDefault"


# 7. Container securityContext: readOnlyRootFilesystem, allowPrivilegeEscalation=false,
#    capabilities.drop=[ALL]
def test_generate_deployment_container_security_context(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    container = doc["spec"]["template"]["spec"]["containers"][0]
    csc = container["securityContext"]
    assert csc["readOnlyRootFilesystem"] is True
    assert csc["allowPrivilegeEscalation"] is False
    assert csc["privileged"] is False
    assert "ALL" in csc["capabilities"]["drop"]


# 8. resources: cpu/memory requests+limits
def test_generate_deployment_resources(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    container = doc["spec"]["template"]["spec"]["containers"][0]
    resources = container["resources"]
    assert resources["requests"]["cpu"] == "250m"
    assert resources["requests"]["memory"] == "256Mi"
    assert resources["limits"]["cpu"] == "500m"
    assert resources["limits"]["memory"] == "512Mi"


# 9. emptyDir volumes '/tmp', '/var/log' 마운트
def test_generate_deployment_emptydir_volumes(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    pod_spec = doc["spec"]["template"]["spec"]
    containers = doc["spec"]["template"]["spec"]["containers"]
    mount_paths = {vm["mountPath"] for vm in containers[0]["volumeMounts"]}
    assert "/tmp" in mount_paths
    assert "/var/log" in mount_paths
    volume_names = {v["name"] for v in pod_spec["volumes"]}
    assert "tmp" in volume_names
    assert "var-log" in volume_names
    # emptyDir {} 확인
    for v in pod_spec["volumes"]:
        assert "emptyDir" in v


# 10. HttpProbe 분기 → livenessProbe.httpGet 있음
def test_generate_deployment_http_probe_liveness(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    container = doc["spec"]["template"]["spec"]["containers"][0]
    liveness = container["livenessProbe"]
    assert "httpGet" in liveness
    assert liveness["httpGet"]["path"] == "/actuator/health/liveness"
    assert liveness["httpGet"]["port"] == 8080


# 11. TcpProbe 분기 → livenessProbe.tcpSocket 있음
def test_generate_deployment_tcp_probe_liveness(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    tcp_probe_config: ProbeConfig,
) -> None:
    analysis_with_tcp = AnalysisResult(
        stack=analysis_result.stack,
        detect_result=analysis_result.detect_result,
        build_plan=analysis_result.build_plan,
        probe_config=tcp_probe_config,
        defaults=analysis_result.defaults,
        artifact_paths=analysis_result.artifact_paths,
        selected_module=analysis_result.selected_module,
        statefulness=analysis_result.statefulness,
        gaps=analysis_result.gaps,
    )
    result = generator.generate_deployment(
        user_inputs, analysis_with_tcp, resource_defaults, tcp_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    container = doc["spec"]["template"]["spec"]["containers"][0]
    liveness = container["livenessProbe"]
    assert "tcpSocket" in liveness
    assert liveness["tcpSocket"]["port"] == 8080
    assert "httpGet" not in liveness


# 12. 보안 근거 주석 (한국어) 포함
def test_generate_deployment_security_comments(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    # F-37: 보안 주석 필수
    assert "컨테이너 권한 분리" in result
    assert "OOMKill" in result
    assert "헬스체크" in result


# 13. 결정론 (SHA-256 동일)
def test_generate_deployment_determinism(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result1 = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    result2 = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    sha1 = hashlib.sha256(result1.encode()).hexdigest()
    sha2 = hashlib.sha256(result2.encode()).hexdigest()
    assert sha1 == sha2


# 14. app_name 개행 주입 차단
def test_generate_deployment_rejects_newline_in_app_name(
    generator: ManifestGenerator,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    bad_inputs = UserInputs(
        app_name="my-app\nevil",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises((ValueError, InvalidImageError)):
        generator.generate_deployment(
            bad_inputs, analysis_result, resource_defaults, http_probe_config,
            image="myrepo/my-app:1.0.0",
        )


# 15. namespace 개행 주입 차단
def test_generate_deployment_rejects_newline_in_namespace(
    generator: ManifestGenerator,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    bad_inputs = UserInputs(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP",
        namespace="dev\nevil",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises((ValueError, InvalidImageError)):
        generator.generate_deployment(
            bad_inputs, analysis_result, resource_defaults, http_probe_config,
            image="myrepo/my-app:1.0.0",
        )


# 16. namespace가 DNS-1123 위반 (대문자) → ValueError
def test_generate_deployment_rejects_uppercase_namespace(
    generator: ManifestGenerator,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    bad_inputs = UserInputs(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP",
        namespace="Dev-NS",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises(ValueError):
        generator.generate_deployment(
            bad_inputs, analysis_result, resource_defaults, http_probe_config,
            image="myrepo/my-app:1.0.0",
        )


# 17. image invalid tag (latest) → InvalidImageError
def test_generate_deployment_rejects_latest_image(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    with pytest.raises(InvalidImageError, match="latest"):
        generator.generate_deployment(
            user_inputs, analysis_result, resource_defaults, http_probe_config,
            image="myrepo/my-app:latest",
        )


# ---------------------------------------------------------------------------
# generate_service テスト
# ---------------------------------------------------------------------------


# 18. 기본 Service 생성 → kind=Service, type=inputs.exposure
def test_generate_service_basic(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
) -> None:
    result = generator.generate_service(user_inputs)
    doc = yaml.safe_load(result)
    assert doc["kind"] == "Service"
    assert doc["apiVersion"] == "v1"
    assert doc["metadata"]["name"] == "my-app"
    assert doc["metadata"]["namespace"] == "dev"
    assert doc["spec"]["type"] == "ClusterIP"


# 19. targetPort = container port
def test_generate_service_target_port(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
) -> None:
    result = generator.generate_service(user_inputs)
    doc = yaml.safe_load(result)
    port_entry = doc["spec"]["ports"][0]
    assert port_entry["targetPort"] == 8080


# ---------------------------------------------------------------------------
# generate_serviceaccount テスト
# ---------------------------------------------------------------------------


# 20. kind=ServiceAccount, automountServiceAccountToken=false
def test_generate_serviceaccount_basic(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
) -> None:
    result = generator.generate_serviceaccount(user_inputs)
    doc = yaml.safe_load(result)
    assert doc["kind"] == "ServiceAccount"
    assert doc["apiVersion"] == "v1"
    assert doc["metadata"]["name"] == "my-app-sa"
    assert doc["metadata"]["namespace"] == "dev"
    assert doc["automountServiceAccountToken"] is False


# ---------------------------------------------------------------------------
# 추가 테스트: edge cases & coverage
# ---------------------------------------------------------------------------


# 21. NodePort exposure → service type NodePort
def test_generate_service_nodeport_type(
    generator: ManifestGenerator,
) -> None:
    inputs = UserInputs(
        app_name="my-app",
        port=8080,
        exposure="NodePort",
        namespace="prod",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    result = generator.generate_service(inputs)
    doc = yaml.safe_load(result)
    assert doc["spec"]["type"] == "NodePort"


# 22. readinessProbe http분기 확인
def test_generate_deployment_http_probe_readiness(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    container = doc["spec"]["template"]["spec"]["containers"][0]
    readiness = container["readinessProbe"]
    assert "httpGet" in readiness
    assert readiness["httpGet"]["path"] == "/actuator/health/readiness"


# 23. app_name DNS-1123 위반 → ValueError
def test_generate_deployment_rejects_uppercase_app_name(
    generator: ManifestGenerator,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    bad_inputs = UserInputs(
        app_name="MyApp",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises(ValueError):
        generator.generate_deployment(
            bad_inputs, analysis_result, resource_defaults, http_probe_config,
            image="myrepo/my-app:1.0.0",
        )


# 24. image 개행 주입 차단
def test_generate_deployment_rejects_newline_in_image(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    with pytest.raises((ValueError, InvalidImageError)):
        generator.generate_deployment(
            user_inputs, analysis_result, resource_defaults, http_probe_config,
            image="myrepo/my-app:1.0.0\nENV EVIL=1",
        )


# ---------------------------------------------------------------------------
# Critical 1: generate_service / generate_serviceaccount 입력 검증
# ---------------------------------------------------------------------------


# 25. generate_service — app_name 개행 차단
def test_generate_service_rejects_newline_in_app_name(
    generator: ManifestGenerator,
) -> None:
    bad = UserInputs(
        app_name="my-app\nevil",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises(ValueError):
        generator.generate_service(bad)


# 26. generate_service — namespace DNS-1123 위반 차단
def test_generate_service_rejects_invalid_namespace(
    generator: ManifestGenerator,
) -> None:
    bad = UserInputs(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP",
        namespace="Dev-NS",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises(ValueError):
        generator.generate_service(bad)


# 27. generate_serviceaccount — app_name DNS-1123 위반 차단
def test_generate_serviceaccount_rejects_invalid_app_name(
    generator: ManifestGenerator,
) -> None:
    bad = UserInputs(
        app_name="MyApp",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises(ValueError):
        generator.generate_serviceaccount(bad)


# 28. generate_serviceaccount — namespace 개행 차단
def test_generate_serviceaccount_rejects_newline_in_namespace(
    generator: ManifestGenerator,
) -> None:
    bad = UserInputs(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP",
        namespace="dev\nevil",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises(ValueError):
        generator.generate_serviceaccount(bad)


# ---------------------------------------------------------------------------
# Critical 2: exposure whitelist 런타임 검증
# ---------------------------------------------------------------------------


# 29. generate_service — 허용되지 않은 exposure 거부
def test_generate_service_rejects_invalid_exposure(
    generator: ManifestGenerator,
) -> None:
    bad = UserInputs(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP\n  externalIPs: [1.2.3.4]",  # type: ignore[arg-type]
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises(ValueError, match="exposure"):
        generator.generate_service(bad)


# 30. generate_service — 임의 문자열 exposure 거부
def test_generate_service_rejects_arbitrary_exposure(
    generator: ManifestGenerator,
) -> None:
    bad = UserInputs(
        app_name="my-app",
        port=8080,
        exposure="ExternalName",  # type: ignore[arg-type]
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises(ValueError, match="exposure"):
        generator.generate_service(bad)


# 31. generate_service — LoadBalancer 허용
def test_generate_service_allows_loadbalancer(
    generator: ManifestGenerator,
) -> None:
    inputs = UserInputs(
        app_name="my-app",
        port=8080,
        exposure="LoadBalancer",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    result = generator.generate_service(inputs)
    doc = yaml.safe_load(result)
    assert doc["spec"]["type"] == "LoadBalancer"


# ---------------------------------------------------------------------------
# Important 5: port 런타임 검증
# ---------------------------------------------------------------------------


# 32. generate_deployment — port=0 거부
def test_generate_deployment_rejects_port_zero(
    generator: ManifestGenerator,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    bad = UserInputs(
        app_name="my-app",
        port=0,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises(ValueError, match="port"):
        generator.generate_deployment(
            bad, analysis_result, resource_defaults, http_probe_config,
            image="myrepo/my-app:1.0.0",
        )


# 33. generate_deployment — port=65536 거부
def test_generate_deployment_rejects_port_out_of_range(
    generator: ManifestGenerator,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    bad = UserInputs(
        app_name="my-app",
        port=65536,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises(ValueError, match="port"):
        generator.generate_deployment(
            bad, analysis_result, resource_defaults, http_probe_config,
            image="myrepo/my-app:1.0.0",
        )


# 34. generate_service — port=0 거부
def test_generate_service_rejects_port_zero(
    generator: ManifestGenerator,
) -> None:
    bad = UserInputs(
        app_name="my-app",
        port=0,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    with pytest.raises(ValueError, match="port"):
        generator.generate_service(bad)


# 35. generate_service — port=65535 허용 (경계값)
def test_generate_service_allows_max_port(
    generator: ManifestGenerator,
) -> None:
    inputs = UserInputs(
        app_name="my-app",
        port=65535,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/output"),
        resource_hint="medium",
    )
    result = generator.generate_service(inputs)
    assert result  # no raise


# ---------------------------------------------------------------------------
# Important 6: probe.path 개행 검증
# ---------------------------------------------------------------------------


# 36. generate_deployment — liveness probe.path에 개행 포함 시 차단
def test_generate_deployment_rejects_newline_in_probe_path(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
) -> None:
    bad_probe = ProbeConfig(
        liveness=ProbeSpec(kind="http", path="/health\nevil: true", port=8080),
        readiness=ProbeSpec(kind="http", path="/actuator/health/readiness", port=8080),
    )
    with pytest.raises(ValueError, match="probe"):
        generator.generate_deployment(
            user_inputs, analysis_result, resource_defaults, bad_probe,
            image="myrepo/my-app:1.0.0",
        )


# 37. generate_deployment — readiness probe.path에 개행 포함 시 차단
def test_generate_deployment_rejects_newline_in_readiness_probe_path(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
) -> None:
    bad_probe = ProbeConfig(
        liveness=ProbeSpec(kind="http", path="/actuator/health/liveness", port=8080),
        readiness=ProbeSpec(kind="http", path="/health\nevil: injected", port=8080),
    )
    with pytest.raises(ValueError, match="probe"):
        generator.generate_deployment(
            user_inputs, analysis_result, resource_defaults, bad_probe,
            image="myrepo/my-app:1.0.0",
        )


# ---------------------------------------------------------------------------
# Important 8: emptyDir sizeLimit 기본값
# ---------------------------------------------------------------------------


# 38. emptyDir volumes에 sizeLimit 있음
def test_generate_deployment_emptydir_sizelimit(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    resource_defaults: ResourceDefaults,
    http_probe_config: ProbeConfig,
) -> None:
    result = generator.generate_deployment(
        user_inputs, analysis_result, resource_defaults, http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    pod_spec = doc["spec"]["template"]["spec"]
    volumes_by_name = {v["name"]: v for v in pod_spec["volumes"]}

    assert "tmp" in volumes_by_name
    assert "var-log" in volumes_by_name

    tmp_vol = volumes_by_name["tmp"]
    varlog_vol = volumes_by_name["var-log"]

    # DoS 방어 sizeLimit 존재 확인
    assert "emptyDir" in tmp_vol
    assert "sizeLimit" in tmp_vol["emptyDir"], "tmp emptyDir에 sizeLimit 없음"
    assert tmp_vol["emptyDir"]["sizeLimit"] == "50Mi"

    assert "emptyDir" in varlog_vol
    assert "sizeLimit" in varlog_vol["emptyDir"], "var-log emptyDir에 sizeLimit 없음"
    assert varlog_vol["emptyDir"]["sizeLimit"] == "100Mi"


# ---------------------------------------------------------------------------
# BL-001 Phase 3: manifest 하드코딩 제거 (F-31 run_as_user + F-32 writable_paths)
# ---------------------------------------------------------------------------


def test_generate_deployment_run_as_user_dynamic(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    http_probe_config: ProbeConfig,
) -> None:
    """F-31: deployment runAsUser/Group/fsGroup은 defaults.run_as_user 기반."""
    defaults_go = ResourceDefaults(
        cpu_request="50m",
        memory_request="64Mi",
        cpu_limit="250m",
        memory_limit="128Mi",
        writable_paths=["/tmp"],
        run_as_user=65532,
    )
    result = generator.generate_deployment(
        user_inputs,
        analysis_result,
        defaults_go,
        http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    pod_sec = doc["spec"]["template"]["spec"]["securityContext"]

    assert pod_sec["runAsUser"] == 65532
    assert pod_sec["runAsGroup"] == 65532
    assert pod_sec["fsGroup"] == 65532


def test_generate_deployment_writable_paths_dynamic(
    generator: ManifestGenerator,
    user_inputs: UserInputs,
    analysis_result: AnalysisResult,
    http_probe_config: ProbeConfig,
) -> None:
    """F-32: writable_paths=['/tmp']만 있으면 /var/log 볼륨 없음."""
    defaults_go = ResourceDefaults(
        cpu_request="50m",
        memory_request="64Mi",
        cpu_limit="250m",
        memory_limit="128Mi",
        writable_paths=["/tmp"],
        run_as_user=65532,
    )
    result = generator.generate_deployment(
        user_inputs,
        analysis_result,
        defaults_go,
        http_probe_config,
        image="myrepo/my-app:1.0.0",
    )
    doc = yaml.safe_load(result)
    pod_spec = doc["spec"]["template"]["spec"]
    volumes_by_name = {v["name"]: v for v in pod_spec["volumes"]}
    mounts_by_name = {m["name"]: m for m in pod_spec["containers"][0]["volumeMounts"]}

    # /tmp만 있고 /var/log 없음
    assert "tmp" in volumes_by_name
    assert "var-log" not in volumes_by_name
    assert "tmp" in mounts_by_name
    assert "var-log" not in mounts_by_name
    assert mounts_by_name["tmp"]["mountPath"] == "/tmp"
    # 기본 sizeLimit 50Mi (JVM /tmp 관례값 보존)
    assert volumes_by_name["tmp"]["emptyDir"]["sizeLimit"] == "50Mi"
