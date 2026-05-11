"""ManifestGenerator — Kubernetes YAML 생성기.

Deployment / Service / ServiceAccount / StatefulSet / NetworkPolicy YAML 생성.
BL-018: 5개 매니페스트 모두 단일 Jinja2 렌더 경로(`templates/manifest/*.tmpl`) 사용 — ADR-0001.
Pod/Container securityContext + probes + 리소스 + 근거 주석(F-37).
emptyDir 기본 마운트 (/tmp, /var/log) (F-32).
automountServiceAccountToken: false (F-30, F-35).
"""

from __future__ import annotations

import re

from scripts._shared.image_ref import validate_image_reference
from scripts._shared.text_safety import reject_unsafe_chars
from scripts._shared.types import (
    AnalysisResult,
    ClusterConfig,
    ProbeConfig,
    ProbeSpec,
    ResourceDefaults,
    UserInputs,
)
from scripts.template_renderer import TemplateRenderer

# storage_size K8s quantity 패턴: 숫자 + 단위 (Ki, Mi, Gi, Ti, Pi, Ei 또는 K, M, G, T, P, E)
_K8S_QUANTITY_RE = re.compile(r"^[0-9]+([KMGTPE]i|[KMGTPE])?$")

# k8s DNS-1123 label: 소문자 알파뉴메릭 + 하이픈, 63자 이하
# 시작/끝은 알파뉴메릭, 중간에 하이픈 허용
_DNS1123_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")

# BL-018 R3: k8s DNS-1123 subdomain (StorageClass name 규칙) — 라벨 + dot 허용, 253자 이하.
# 각 dot-구분 세그먼트는 DNS-1123 label 규칙(시작/끝 알파뉴메릭) 준수.
_DNS1123_SUBDOMAIN_RE = re.compile(
    r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?)*$"
)
_MAX_DNS1123_SUBDOMAIN_LEN = 253



# exposure 허용 목록 — 런타임 검증 (Literal 타입은 런타임 강제 안 됨)
_ALLOWED_EXPOSURES: frozenset[str] = frozenset({"ClusterIP", "NodePort", "LoadBalancer"})

# BL-001 Phase 3 (F-32): writable_paths 경로별 emptyDir sizeLimit + 주석 매핑.
# 공통 컨벤션 — /tmp(런타임 임시, 50Mi), /var/log(런타임 로그, 100Mi). JVM·Go 모두 호환.
# 미매핑 경로는 _DEFAULT_SIZE_LIMIT / _DEFAULT_VOLUME_COMMENT fallback.
_WRITABLE_SIZE_LIMITS: dict[str, str] = {
    "/tmp": "50Mi",
    "/var/log": "100Mi",
}
_DEFAULT_SIZE_LIMIT = "50Mi"

_WRITABLE_VOLUME_COMMENTS: dict[str, str] = {
    "/tmp": "DoS 방어 — 노드 디스크 소진 방지 (런타임 임시 파일, 예: Tomcat work / JVM temp)",
    "/var/log": "DoS 방어 + 런타임 로그 경로 (예: Spring Boot, syslog)",
}
_DEFAULT_VOLUME_COMMENT = "DoS 방어 — emptyDir sizeLimit"


def _volume_name_for_path(path: str) -> str:
    """K8s DNS-1123 label 호환 volume 이름. 예: `/var/log` → `var-log`, `/` → `root`."""
    return path.lstrip("/").replace("/", "-") or "root"


def _writable_volume_mounts(paths: list[str]) -> list[dict[str, str]]:
    """volumeMounts 컨텍스트 리스트 (F-32)."""
    return [
        {"name": _volume_name_for_path(p), "mount_path": p} for p in paths
    ]


def _writable_volumes(paths: list[str]) -> list[dict[str, str]]:
    """volumes 컨텍스트 리스트 (F-32). 경로별 sizeLimit + 주석."""
    return [
        {
            "name": _volume_name_for_path(p),
            "size_limit": _WRITABLE_SIZE_LIMITS.get(p, _DEFAULT_SIZE_LIMIT),
            "comment": _WRITABLE_VOLUME_COMMENTS.get(p, _DEFAULT_VOLUME_COMMENT),
        }
        for p in paths
    ]


def _validate_manifest_field(value: str, field_name: str) -> None:
    """YAML 컨텍스트에 삽입될 문자열에서 개행/NUL 차단.

    scripts._shared.text_safety.reject_unsafe_chars에 위임.

    Args:
        value: 검증할 문자열.
        field_name: 오류 메시지에 포함될 필드명.

    Raises:
        ValueError: 개행 또는 NUL 문자가 포함된 경우.
    """
    reject_unsafe_chars(value, field_name, message_prefix="YAML 주입 방어")


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


def _validate_storage_class_name(value: str) -> None:
    """BL-018 R3: K8s StorageClass name 검증 (DNS-1123 subdomain).

    빈 문자열 ''는 K8s 동적 프로비저닝 비활성화 sentinel로 명시 허용 — 검증 건너뜀.
    그 외에는 DNS-1123 subdomain 규칙:
      - 소문자 알파뉴메릭 + 하이픈, dot 구분 세그먼트
      - 각 세그먼트는 시작/끝 알파뉴메릭, ≤63자
      - 전체 길이 ≤253자

    이 검증은 trust boundary에서 fail-fast로 작동. 템플릿 측에는 `| tojson`
    안전 직렬화가 defense-in-depth로 적용된다 (statefulset.tmpl).

    Args:
        value: storage_class 값. `None`은 호출자가 분기해 이 함수에 도달하지 않음.

    Raises:
        ValueError: 빈 문자열 외 입력이 DNS-1123 subdomain 규칙을 위반할 때.
    """
    if value == "":
        return  # K8s 동적 프로비저닝 비활성화 sentinel — 허용
    if len(value) > _MAX_DNS1123_SUBDOMAIN_LEN:
        raise ValueError(
            f"storage_class 길이 초과 (>{_MAX_DNS1123_SUBDOMAIN_LEN}): {value!r}"
        )
    if not _DNS1123_SUBDOMAIN_RE.fullmatch(value):
        raise ValueError(
            f"storage_class DNS-1123 subdomain 위반: {value!r}. "
            "소문자 알파뉴메릭·하이픈·dot만 허용, 각 세그먼트 시작/끝 알파뉴메릭."
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
          - spec.replicas = inputs.replicas
          - spec.template.spec.serviceAccountName = '{app_name}-sa'
          - spec.template.spec.automountServiceAccountToken: false
          - Pod securityContext (F-31): runAsNonRoot, runAsUser/fsGroup은
            defaults.run_as_user 기반 동적 주입 (JVM 관례 1000, Go distroless 65532),
            seccompProfile=RuntimeDefault
          - Container securityContext (F-32): readOnlyRootFilesystem,
            allowPrivilegeEscalation=false, capabilities.drop=[ALL], privileged=false
          - emptyDir 볼륨은 defaults.writable_paths 기반 동적 마운트 (F-32)
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
            "replicas": inputs.replicas,
            # BL-001 Phase 3 (F-31/F-32): UID + writable_paths 동적화
            "run_as_user": defaults.run_as_user,
            "writable_volume_mounts": _writable_volume_mounts(defaults.writable_paths),
            "writable_volumes": _writable_volumes(defaults.writable_paths),
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

    def generate_statefulset(
        self,
        inputs: UserInputs,
        analysis: AnalysisResult,
        cluster: ClusterConfig,
        *,
        image: str,
        storage_size: str = "1Gi",
    ) -> str:
        """statefulset.yaml 문자열 반환.

        BL-018: dict+yaml.dump → Jinja2(`templates/manifest/statefulset.tmpl`) 일원화.
        cluster.storage_class가 None이면 `storageClassName` 필드를 템플릿에서 생략한다.

        Raises:
            ValueError: storage_size가 K8s quantity 형식이 아닌 경우.
            ValueError: cluster.storage_class에 개행/제어문자 포함 시.
        """
        self._validate_inputs_common(inputs)
        self._validate_port(inputs.port)
        validate_image_reference(image)
        _validate_k8s_quantity(storage_size)
        if cluster.storage_class is not None:
            # BL-018 R3: DNS-1123 subdomain 검증 ('' sentinel은 명시 허용).
            # 이전 R2의 _validate_manifest_field(개행/CR/NUL 차단)는 quote/backslash 통과 →
            # statefulset.tmpl의 quoted scalar 깨뜨림. trust boundary fail-fast.
            _validate_storage_class_name(cluster.storage_class)

        defaults = analysis.defaults
        liveness_ctx = _build_probe_context(analysis.probe_config.liveness, "liveness")
        readiness_ctx = _build_probe_context(analysis.probe_config.readiness, "readiness")

        # BL-018 R2 (Codex adversarial MEDIUM): None vs '' 시맨틱 보존.
        # K8s PVC: missing field → cluster default StorageClass / '' → 동적 프로비저닝 비활성화.
        # 템플릿이 falsy 체크(`{% if storage_class %}`)면 ''에서도 키 누락 → 의미 drift.
        # 명시 has_storage_class 플래그로 None만 누락하도록 분기.
        context: dict[str, object] = {
            "app_name": inputs.app_name,
            "cpu_limit": defaults.cpu_limit,
            "cpu_request": defaults.cpu_request,
            "has_storage_class": cluster.storage_class is not None,
            "image": image,
            "memory_limit": defaults.memory_limit,
            "memory_request": defaults.memory_request,
            "namespace": inputs.namespace,
            "port": inputs.port,
            "replicas": inputs.replicas,
            "run_as_user": defaults.run_as_user,
            "storage_class": cluster.storage_class if cluster.storage_class is not None else "",
            "storage_size": storage_size,
            **liveness_ctx,
            **readiness_ctx,
        }
        return self._renderer.render_manifest("statefulset", context)


    def generate_networkpolicy(
        self,
        inputs: UserInputs,
        cluster: ClusterConfig,
        *,
        allow_ingress_from: list[dict[str, object]] | None = None,
        allow_egress_to: list[dict[str, object]] | None = None,
    ) -> str | None:
        """networkpolicy.yaml 문자열 반환. network_policy=False 시 None.

        BL-018: dict+yaml.dump → Jinja2(`templates/manifest/networkpolicy.tmpl`) 일원화.
        기본 정책: deny-all ingress/egress.
        CoreDNS egress(kube-system namespace, port 53 UDP+TCP)는 템플릿에서 항상 포함.

        allow_ingress_from / allow_egress_to 형식:
            [{"namespace": "ns-name", "port": 8080}, ...]

        Raises:
            ValueError: inputs.app_name 또는 namespace가 DNS-1123 위반 시.
        """
        if not cluster.network_policy:
            return None

        self._validate_inputs_common(inputs)

        ingress_rules = list(allow_ingress_from or [])
        extra_egress = list(allow_egress_to or [])

        # BL-018 R2 (Codex adversarial HIGH): unquoted Jinja 치환 → trust boundary.
        # entry는 정확히 {"namespace": str, "port": int} 형태만 허용. 위반 시 fail-fast.
        # yaml.dump의 자동 quoting 안전성 회귀를 막기 위한 explicit schema 검증.
        for entry in (*ingress_rules, *extra_egress):
            self._validate_netpol_entry(entry)

        context: dict[str, object] = {
            "app_name": inputs.app_name,
            "extra_egress": extra_egress,
            "ingress_rules": ingress_rules,
            "namespace": inputs.namespace,
        }
        return self._renderer.render_manifest("networkpolicy", context)

    @staticmethod
    def _validate_netpol_entry(entry: object) -> None:
        """BL-018 R2: NetworkPolicy allow_*_from/to entry schema 가드.

        허용 형태: dict, exact keys = {"namespace", "port"}.
        - namespace: DNS-1123 label (소문자 알파뉴메릭+하이픈, 시작/끝 알파뉴메릭, ≤63자).
        - port: int, 1 ≤ port ≤ 65535.

        Raises:
            ValueError: dict 아님 / 키 부재 / 추가 키 / 검증 실패 시.
        """
        if not isinstance(entry, dict):
            raise ValueError(
                f"NetworkPolicy entry는 dict여야 함: type={type(entry).__name__}, value={entry!r}"
            )
        allowed_keys = {"namespace", "port"}
        actual_keys = set(entry.keys())
        if actual_keys != allowed_keys:
            missing = allowed_keys - actual_keys
            extra = actual_keys - allowed_keys
            raise ValueError(
                f"NetworkPolicy entry 키 불일치: missing={sorted(missing)}, "
                f"extra={sorted(extra)}, entry={entry!r}"
            )

        ns = entry["namespace"]
        if not isinstance(ns, str):
            raise ValueError(
                f"NetworkPolicy entry.namespace는 str: type={type(ns).__name__}, value={ns!r}"
            )
        _validate_dns1123_label(ns, "namespace")

        port = entry["port"]
        # bool은 int 서브클래스 → 명시 차단
        if isinstance(port, bool) or not isinstance(port, int):
            raise ValueError(
                f"NetworkPolicy entry.port는 int: type={type(port).__name__}, value={port!r}"
            )
        if not (1 <= port <= 65535):
            raise ValueError(
                f"NetworkPolicy entry.port는 [1, 65535] 범위: port={port}"
            )


def _validate_k8s_quantity(value: str) -> None:
    """K8s resource quantity 형식 검증.

    패턴: 숫자 + 단위 (Ki/Mi/Gi/Ti/Pi/Ei 또는 K/M/G/T/P/E) 또는 순수 숫자.

    Raises:
        ValueError: 형식 불일치 시.
    """
    if not _K8S_QUANTITY_RE.fullmatch(value):
        raise ValueError(
            f"storage_size가 K8s quantity 형식이 아님: {value!r}. "
            "예시: '1Gi', '500Mi', '10G'"
        )
