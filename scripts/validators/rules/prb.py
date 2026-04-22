"""PRB 규칙 — PRB-001, PRB-002."""

from __future__ import annotations

from typing import Any

from scripts._shared.types import CheckResult
from scripts.validators.registry import register_rule


@register_rule("container")
def rule_prb001(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """PRB-001: livenessProbe 존재."""
    name = str(c.get("name", "unknown"))
    if "livenessProbe" in c:
        return [
            CheckResult(
                rule_id="PRB-001",
                level="PASS",
                container=name,
                message_ko="livenessProbe가 설정되어 있습니다.",
                message_en="livenessProbe is configured.",
                suggestion="",
            )
        ]
    return [
        CheckResult(
            rule_id="PRB-001",
            level="FAIL",
            container=name,
            message_ko="livenessProbe 미설정",
            message_en="livenessProbe is not configured.",
            suggestion=(
                "livenessProbe 를 설정하세요. "
                "미설정 시 비정상 파드가 재시작되지 않아 트래픽을 계속 수신합니다."
            ),
        )
    ]


@register_rule("container")
def rule_prb002(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """PRB-002: readinessProbe 존재."""
    name = str(c.get("name", "unknown"))
    if "readinessProbe" in c:
        return [
            CheckResult(
                rule_id="PRB-002",
                level="PASS",
                container=name,
                message_ko="readinessProbe가 설정되어 있습니다.",
                message_en="readinessProbe is configured.",
                suggestion="",
            )
        ]
    return [
        CheckResult(
            rule_id="PRB-002",
            level="FAIL",
            container=name,
            message_ko="readinessProbe 미설정",
            message_en="readinessProbe is not configured.",
            suggestion=(
                "readinessProbe 를 설정하세요. "
                "미설정 시 준비되지 않은 파드에 트래픽이 전달됩니다."
            ),
        )
    ]
