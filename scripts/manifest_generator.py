"""ManifestGenerator — Kubernetes YAML 생성기.

Deployment / Service / ServiceAccount YAML 생성.
Pod/Container securityContext + probes + 리소스 + 근거 주석(F-37).
emptyDir 기본 마운트 (/tmp, /var/log) (F-32).
automountServiceAccountToken: false (F-30, F-35).
"""

from __future__ import annotations

import re

from scripts._shared.types import (
    AnalysisResult,
    ProbeConfig,
    ProbeSpec,
    ResourceDefaults,
    UserInputs,
)
from scripts.dockerfile_generator import DockerfileGenerator
from scripts.template_renderer import TemplateRenderer

# k8s DNS-1123 label: 소문자 알파뉴메릭 + 하이픈, 63자 이하
# 시작/끝은 알파뉴메릭, 중간에 하이픈 허용
_DNS1123_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")

# 개행/제어문자 차단 패턴 (YAML 인젝션 방어)
_UNSAFE_CHARS = ("\n", "\r", "\x00")

# 기본 replicas (v0.1.0 고정값, v0.2+에서 설정화 예정)
_DEFAULT_REPLICAS = 2


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
    """
    if probe.kind == "http":
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
        # DockerfileGenerator에서 _validate_image_tag 재사용
        self._dockerfile_gen = DockerfileGenerator(renderer)

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
            analysis: 프로젝트 분석 결과 (현재 v0.1.0에서 직접 사용 안 함 — 확장 예약).
            defaults: 리소스 기본값 (cpu/memory requests/limits).
            probe: liveness/readiness probe 설정.
            image: 컨테이너 이미지 참조 (예: 'myrepo/app:1.0.0').

        Returns:
            정규화된 deployment.yaml 문자열.

        Raises:
            ValueError: app_name 또는 namespace가 DNS-1123 위반 또는 개행 포함 시.
            InvalidImageError: image에 'latest' 태그 또는 유효하지 않은 참조 형식 시.
        """
        # Fail-fast: 입력 검증
        _validate_dns1123_label(inputs.app_name, "app_name")
        _validate_dns1123_label(inputs.namespace, "namespace")
        self._dockerfile_gen._validate_image_tag(image)

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
        """
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
        """
        context: dict[str, object] = {
            "app_name": inputs.app_name,
            "namespace": inputs.namespace,
        }

        return self._renderer.render_manifest("serviceaccount", context)
