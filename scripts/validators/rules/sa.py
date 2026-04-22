"""SA 규칙 — SA-001, SA-002."""

from __future__ import annotations

from typing import Any

from scripts._shared.types import CheckResult
from scripts.validators.registry import register_rule


@register_rule("pod_spec")
def rule_sa001(pod_spec: dict[str, Any], **_: Any) -> list[CheckResult]:
    """SA-001: automountServiceAccountToken: false 필수."""
    val = pod_spec.get("automountServiceAccountToken")
    if val is False:
        return [
            CheckResult(
                rule_id="SA-001",
                level="PASS",
                container="(pod)",
                message_ko="automountServiceAccountToken이 false로 설정되어 있습니다.",
                message_en="automountServiceAccountToken is set to false.",
                suggestion="",
            )
        ]
    return [
        CheckResult(
            rule_id="SA-001",
            level="FAIL",
            container="(pod)",
            message_ko=f"automountServiceAccountToken 미설정 (현재: {val!r})",
            message_en=(
                f"automountServiceAccountToken is not false (current: {val!r})."
            ),
            suggestion=(
                "spec.automountServiceAccountToken: false 를 설정하세요. "
                "자동 마운트된 토큰은 API server 접근에 악용될 수 있습니다."
            ),
        )
    ]


@register_rule("pod_spec")
def rule_sa002(pod_spec: dict[str, Any], **_: Any) -> list[CheckResult]:
    """SA-002: Pod에 serviceAccountName 명시 (default SA 방지)."""
    sa_name = pod_spec.get("serviceAccountName")
    if sa_name and str(sa_name).strip():
        return [
            CheckResult(
                rule_id="SA-002",
                level="PASS",
                container="(pod)",
                message_ko=f"serviceAccountName이 명시되어 있습니다: {sa_name!r}.",
                message_en=f"serviceAccountName is explicitly set: {sa_name!r}.",
                suggestion="",
            )
        ]
    return [
        CheckResult(
            rule_id="SA-002",
            level="FAIL",
            container="(pod)",
            message_ko="spec.serviceAccountName 미설정",
            message_en="spec.serviceAccountName is not set.",
            suggestion=(
                "spec.serviceAccountName을 명시하세요. 미설정 시 default ServiceAccount가"
                " 자동 마운트되어 불필요한 권한이 부여될 수 있습니다."
            ),
        )
    ]
