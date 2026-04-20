"""ManifestGenerator — Kubernetes YAML 생성기.

Deployment / Service / ServiceAccount YAML 생성.
Pod/Container securityContext + probes + 리소스 + 근거 주석(F-37).
emptyDir 기본 마운트 (/tmp, /var/log) (F-32).
automountServiceAccountToken: false (F-30, F-35).
"""

from __future__ import annotations

import re

from scripts._shared.image_ref import validate_image_reference
from scripts._shared.types import (
    AnalysisResult,
    ProbeConfig,
    ProbeSpec,
    ResourceDefaults,
    UserInputs,
)
from scripts.template_renderer import TemplateRenderer

# k8s DNS-1123 label: 소문자 알파뉴메릭 + 하이픈, 63자 이하
# 시작/끝은 알파뉴메릭, 중간에 하이픈 허용
_DNS1123_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")

# 개행/제어문자 차단 패턴 (YAML 인젝션 방어)
_UNSAFE_CHARS = ("\n", "\r", "\x00")

# 기본 replicas (v0.1.0 고정값, v0.2+에서 설정화 예정)
_DEFAULT_REPLICAS = 2

# exposure 허용 목록 — 런타임 검증 (Literal 타입은 런타임 강제 안 됨)
_ALLOWED_EXPOSURES: frozenset[str] = frozenset({"ClusterIP", "NodePort", "LoadBalancer"})


def _validate_manifest_field(value: str, field_name: str) -> None:
    """YAML 컨텍스트에 삽입될 문자열에서 개행/NUL 차단.

    Args:
        value: 검증할 문자열.
        field_name: 오류 메시지에 포함될 필드명.

    Raises:
        ValueError: 개행 또는 NUL 문자가 포함된 경우.
    """
    for ch in _UNSAFE_CHARS:
        if ch in value:
            raise ValueError(
                f"YAML 주입 방어: {field_name}에 개행 또는 제어문자 포함 금지: {value!r}"
            )


def _validate_dns1123_label(value: str, field_name: str) -> None:
    """k8s DNS-1123 label 규칙 검증.

    소문자 알파뉴메릭과 하이픈만 허용. 63자 이하.
    시작과 끝은 알파뉴메릭이어야 함.

    Args:
        value: 검증할 문자열.
        field_name: 오류 메시지에 포함될 필드명.

    Raises:
        ValueError: 개행/제어문자 포함, 또는 DNS-1123 규칙 위반 시.
    """
    # 개행/제어문자 먼저 차단
    _validate_manifest_field(value, field_name)

    if not _DNS1123_LABEL_RE.fullmatch(value):
        raise ValueError(
            f"k8s DNS-1123 label 위반: {field_name}={value!r}. "
            "소문자 알파뉴메릭·하이픈만 허용, 63자 이하, 시작/끝은 알파뉴메릭."
        )


def _build_probe_context(probe: ProbeSpec, prefix: str) -> dict[str, object]:
    """ProbeSpec을 템플릿 컨텍스트로 변환.

    Args:
        probe: 프로브 스펙 (http 또는 tcp).
        prefix: 컨텍스트 키 접두사 ('liveness' 또는 'readiness').

    Returns:
        템플릿 컨텍스트 dict. http면 '{prefix}_http' 설정, tcp면 '{prefix}_tcp_port' 설정.

    Raises:
        ValueError: http probe의 path에 개행/제어문자 포함 시.
    """
    if probe.kind == "http":
        # probe.path 개행/제어문자 차단 (YAML 인젝션 방어)
        if probe.path is not None:
            _validate_manifest_field(probe.path, "probe.path")
        return {
            f"{prefix}_http": {"path": probe.path, "port": probe.port},
            f"{prefix}_tcp_port": None,
        }
    else:
        return {
            f"{prefix}_http": None,
            f"{prefix}_tcp_port": probe.port,
        }


class ManifestGenerator:
    """Kubernetes manifest YAML 생성 서비스."""

    def __init__(self, renderer: TemplateRenderer) -> None:
        self._renderer = renderer

    def _validate_inputs_common(self, inputs: UserInputs) -> None:
        """세 generate_* 메서드 공통 입력 검증.

        app_name / namespace: DNS-1123 label + 개행/제어문자 차단.
        호출: generate_deployment/generate_service/generate_serviceaccount 진입부.

        Args:
            inputs: 사용자 입력.

        Raises:
            ValueError: app_name 또는 namespace가 DNS-1123 위반 또는 개행 포함 시.
        """
        _validate_dns1123_label(inputs.app_name, "app_name")
        _validate_dns1123_label(inputs.namespace, "namespace")

    def _validate_port(self, port: object) -> None:
        """port 런타임 검증 (1-65535 정수).

        Args:
            port: 포트 값. 정수 타입이며 1~65535 범위여야 함.

        Raises:
            ValueError: 정수가 아니거나 범위 초과 시.
        """
        if not isinstance(port, int) or isinstance(port, bool):
            raise ValueError(f"port는 정수여야 함: {port!r}")
        if not (1 <= port <= 65535):
            raise ValueError(f"port 범위 초과 (1-65535): {port}")

    def generate_deployment(
        self,
        inputs: UserInputs,
        analysis: AnalysisResult,
        defaults: ResourceDefaults,
        probe: ProbeConfig,
        *,
        image: str,
    ) -> str:
        """deployment.yaml 문자열 반환.

        포함:
          - metadata.name = inputs.app_name, namespace = inputs.namespace
          - spec.replicas (default 2 — v0.1.0 고정값)
          - spec.template.spec.serviceAccountName = '{app_name}-sa'
          - spec.template.spec.automountServiceAccountToken: false
          - Pod securityContext (F-31): runAsNonRoot, runAsUser=1000,
            fsGroup=1000, seccompProfile=RuntimeDefault
          - Container securityContext (F-32): readOnlyRootFilesystem,
            allowPrivilegeEscalation=false, capabilities.drop=[ALL], privileged=false
          - emptyDir 볼륨 [/tmp, /var/log] 자동 마운트 (F-32)
          - resources (F-33): requests/limits cpu+memory from defaults
          - probes (F-34): liveness + readiness from ProbeConfig
          - 보안 근거 주석 (F-37)

        Args:
            inputs: STEP 1 사용자 입력 (앱 이름, 포트, 네임스페이스 등).
            analysis: 프로젝트 분석 결과.
                v0.1.0에서는 미사용. v0.2+에서 ``analysis.statefulness.is_stateful``로
                StatefulSet 전환, ``analysis.selected_module``로 multi-module 대응 예정.
            defaults: 리소스 기본값 (cpu/memory requests/limits).
            probe: liveness/readiness probe 설정.
            image: 컨테이너 이미지 참조 (예: 'myrepo/app:1.0.0').

        Returns:
            정규화된 deployment.yaml 문자열.

        Raises:
            ValueError: app_name 또는 namespace가 DNS-1123 위반, 개행 포함, 또는 port 범위 초과 시.
            InvalidImageError: image에 'latest' 태그 또는 유효하지 않은 참조 형식 시.
        """
        # Fail-fast: 입력 검증
        self._validate_inputs_common(inputs)
        self._validate_port(inputs.port)
        validate_image_reference(image)
        # analysis: v0.1.0 미사용 — v0.2+ StatefulSet 전환 + multi-module 예약
        _ = analysis

        # ProbeSpec → 템플릿 컨텍스트 변환
        liveness_ctx = _build_probe_context(probe.liveness, "liveness")
        readiness_ctx = _build_probe_context(probe.readiness, "readiness")

        context: dict[str, object] = {
            "app_name": inputs.app_name,
            "cpu_limit": defaults.cpu_limit,
            "cpu_request": defaults.cpu_request,
            "image": image,
            "memory_limit": defaults.memory_limit,
            "memory_request": defaults.memory_request,
            "namespace": inputs.namespace,
            "port": inputs.port,
            "replicas": _DEFAULT_REPLICAS,
            **liveness_ctx,
            **readiness_ctx,
        }

        return self._renderer.render_manifest("deployment", context)

    def generate_service(self, inputs: UserInputs) -> str:
        """service.yaml 문자열 반환.

        type = inputs.exposure. targetPort = container port.

        Args:
            inputs: STEP 1 사용자 입력 (앱 이름, 포트, 네임스페이스, exposure 등).

        Returns:
            정규화된 service.yaml 문자열.

        Raises:
            ValueError: app_name/namespace DNS-1123 위반, port 범위 초과,
                또는 exposure가 허용 목록 외 값인 경우.
        """
        # Fail-fast: 입력 검증
        self._validate_inputs_common(inputs)
        self._validate_port(inputs.port)
        if inputs.exposure not in _ALLOWED_EXPOSURES:
            raise ValueError(
                f"exposure는 {sorted(_ALLOWED_EXPOSURES)} 중 하나여야 함: {inputs.exposure!r}"
            )

        context: dict[str, object] = {
            "app_name": inputs.app_name,
            "namespace": inputs.namespace,
            "service_port": inputs.port,
            "service_type": inputs.exposure,
            "target_port": inputs.port,
        }

        return self._renderer.render_manifest("service", context)

    def generate_serviceaccount(self, inputs: UserInputs) -> str:
        """serviceaccount.yaml 문자열 반환.

        name = '{app_name}-sa', automountServiceAccountToken: false.

        Args:
            inputs: STEP 1 사용자 입력 (앱 이름, 네임스페이스 등).

        Returns:
            정규화된 serviceaccount.yaml 문자열.

        Raises:
            ValueError: app_name 또는 namespace가 DNS-1123 위반 또는 개행 포함 시.
        """
        # Fail-fast: 입력 검증
        self._validate_inputs_common(inputs)

        context: dict[str, object] = {
            "app_name": inputs.app_name,
            "namespace": inputs.namespace,
        }

        return self._renderer.render_manifest("serviceaccount", context)
