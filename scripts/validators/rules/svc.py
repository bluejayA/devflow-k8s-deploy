"""SVC 규칙 — SVC-001, SVC-002."""

from __future__ import annotations

from typing import Any

from scripts._shared.types import CheckResult
from scripts.validators.helpers import _as_dict
from scripts.validators.registry import register_rule


@register_rule("service")
def rule_svc001(doc: dict[str, Any], **_: Any) -> list[CheckResult]:
    """SVC-001: Service 리소스가 존재하면 PASS."""
    svc_name = str(doc.get("metadata", {}).get("name", "unknown"))
    return [CheckResult(rule_id="SVC-001", level="PASS", container=f"svc/{svc_name}",
                        message_ko=f"Service 리소스가 존재합니다: {svc_name!r}.",
                        message_en=f"Service resource exists: {svc_name!r}.", suggestion="")]


@register_rule("service")
def rule_svc002(
    doc: dict[str, Any],
    *,
    context_docs: list[dict[str, Any]] | None = None,
    **_: Any,
) -> list[CheckResult]:
    """SVC-002: targetPort ↔ containerPort 교차 검증."""
    svc_name = str(doc.get("metadata", {}).get("name", "unknown"))
    svc_ports: list[dict[str, Any]] = doc.get("spec", {}).get("ports", [])
    if not context_docs:
        return []

    container_ports: set[int] = set()
    named_ports: dict[str, int] = {}
    for ctx_doc in context_docs:
        if ctx_doc.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        pod_spec = _as_dict(_as_dict(_as_dict(ctx_doc.get("spec")).get("template")).get("spec"))
        containers: list[dict[str, Any]] = pod_spec.get("containers", [])
        init_containers: list[dict[str, Any]] = pod_spec.get("initContainers", [])
        for c in containers + init_containers:
            for p in c.get("ports", []):
                cp = p.get("containerPort")
                if cp is not None and isinstance(cp, int):
                    container_ports.add(cp)
                elif cp is not None:
                    try:
                        container_ports.add(int(cp))
                    except (ValueError, TypeError):
                        pass
                port_name = p.get("name")
                if port_name and cp is not None:
                    try:
                        named_ports[str(port_name)] = int(cp)
                    except (ValueError, TypeError):
                        pass

    if not container_ports and not named_ports:
        return []

    results: list[CheckResult] = []
    for svc_port in svc_ports:
        target = svc_port.get("targetPort")
        if target is None:
            continue
        if isinstance(target, int):
            if target not in container_ports:
                results.append(CheckResult(
                    rule_id="SVC-002", level="FAIL", container=f"svc/{svc_name}",
                    message_ko=(f"targetPort {target}가 컨테이너 containerPort 목록과 불일치"),
                    message_en=(f"targetPort {target} does not match any container containerPort."),
                    suggestion=(f"Service의 targetPort를 컨테이너의 containerPort 중 하나로 "
                                f"설정하세요. 가용 포트: {sorted(container_ports)}")))
            else:
                results.append(CheckResult(
                    rule_id="SVC-002", level="PASS", container=f"svc/{svc_name}",
                    message_ko=(f"targetPort {target}가 컨테이너 containerPort와 일치합니다."),
                    message_en=(f"targetPort {target} matches container containerPort."),
                    suggestion=""))
        else:
            target_str = str(target)
            if target_str in named_ports:
                results.append(CheckResult(
                    rule_id="SVC-002", level="PASS", container=f"svc/{svc_name}",
                    message_ko=(f"named targetPort {target_str!r}가 컨테이너 포트와 일치합니다."),
                    message_en=(f"Named targetPort {target_str!r} matches container port."),
                    suggestion=""))
            else:
                results.append(CheckResult(
                    rule_id="SVC-002", level="FAIL", container=f"svc/{svc_name}",
                    message_ko=(f"named targetPort {target_str!r}가 컨테이너 포트 이름과 불일치"),
                    message_en=(f"Named targetPort {target_str!r} does not match any port."),
                    suggestion=(f"컨테이너 ports[].name 중 하나로 targetPort를 설정하세요. "
                                f"등록된 포트 이름: {sorted(named_ports.keys())}")))
    return results
