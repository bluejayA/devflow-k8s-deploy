"""RES 규칙 — RES-001, RES-W01."""

from __future__ import annotations

from typing import Any

from scripts._shared.types import CheckResult
from scripts.validators.helpers import _cpu_to_milli
from scripts.validators.registry import register_rule


@register_rule("container")
def rule_res001(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """RES-001: resources.requests.{cpu,memory} + limits.{cpu,memory} 모두 존재."""
    name = str(c.get("name", "unknown"))
    resources = c.get("resources", {})
    requests = resources.get("requests", {})
    limits = resources.get("limits", {})
    missing: list[str] = []
    if "cpu" not in requests:
        missing.append("requests.cpu")
    if "memory" not in requests:
        missing.append("requests.memory")
    if "cpu" not in limits:
        missing.append("limits.cpu")
    if "memory" not in limits:
        missing.append("limits.memory")
    if missing:
        return [
            CheckResult(
                rule_id="RES-001",
                level="FAIL",
                container=name,
                message_ko=f"리소스 스펙 누락: {', '.join(missing)}",
                message_en=f"Missing resource specs: {', '.join(missing)}.",
                suggestion=(
                    "resources.requests 및 resources.limits에 cpu, memory 값을"
                    " 모두 설정하세요. "
                    "미설정 시 OOM 또는 CPU throttling이 예측 불가하게 발생합니다."
                ),
            )
        ]
    return [
        CheckResult(
            rule_id="RES-001",
            level="PASS",
            container=name,
            message_ko="resources.requests/limits이 모두 설정되어 있습니다.",
            message_en="resources.requests/limits are fully specified.",
            suggestion="",
        )
    ]


@register_rule("container")
def rule_res_w01(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """RES-W01: requests:limits CPU 비율 과도 (limit/request > 4배) 경고."""
    name = str(c.get("name", "unknown"))
    resources = c.get("resources", {})
    requests = resources.get("requests", {})
    limits = resources.get("limits", {})
    req_cpu_str = requests.get("cpu")
    lim_cpu_str = limits.get("cpu")
    if req_cpu_str is None or lim_cpu_str is None:
        return []
    req_milli = _cpu_to_milli(str(req_cpu_str))
    lim_milli = _cpu_to_milli(str(lim_cpu_str))
    if (
        req_milli is not None
        and lim_milli is not None
        and req_milli > 0
        and lim_milli / req_milli > 4
    ):
        return [
            CheckResult(
                rule_id="RES-W01",
                level="WARN",
                container=name,
                message_ko=(
                    f"CPU limit({lim_cpu_str}) / request({req_cpu_str}) 비율이 4배 초과"
                ),
                message_en=(
                    f"CPU limit ({lim_cpu_str}) / request ({req_cpu_str}) ratio exceeds 4x."
                ),
                suggestion=(
                    "CPU limit은 request의 4배 이하로 설정하세요. "
                    "과도한 비율은 노드 과부하를 유발할 수 있습니다."
                ),
            )
        ]
    return []
