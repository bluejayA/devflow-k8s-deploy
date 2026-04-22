"""LIFE 규칙 — LIFE-W01."""

from __future__ import annotations

from typing import Any

from scripts._shared.types import CheckResult
from scripts.validators.registry import register_rule


@register_rule("pod_spec")
def rule_life_w01(pod_spec: dict[str, Any], **_: Any) -> list[CheckResult]:
    """LIFE-W01: terminationGracePeriodSeconds 미설정 또는 30 미만 WARN."""
    val = pod_spec.get("terminationGracePeriodSeconds")
    if val is not None:
        try:
            if int(val) >= 30:
                return []
        except (ValueError, TypeError):
            pass
    if val is None:
        reason = "terminationGracePeriodSeconds 미설정"
    elif not isinstance(val, int):
        reason = f"terminationGracePeriodSeconds={val!r} — 비정수값"
    else:
        reason = f"terminationGracePeriodSeconds={val!r} — 30 미만"
    return [
        CheckResult(
            rule_id="LIFE-W01",
            level="WARN",
            container="(pod)",
            message_ko=f"graceful shutdown 시간 부족: {reason}",
            message_en=f"Insufficient graceful shutdown period: {reason}.",
            suggestion=(
                "spec.template.spec.terminationGracePeriodSeconds: 30 이상을 설정하면 "
                "롤링 업데이트 중 진행 중인 요청이 완료될 때까지 기다릴 수 있습니다."
            ),
        )
    ]
