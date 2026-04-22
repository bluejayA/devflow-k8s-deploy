"""STS 규칙 — STS-W01."""

from __future__ import annotations

from typing import Any

from scripts._shared.types import CheckResult
from scripts.validators.registry import register_rule


@register_rule("statefulset")
def rule_sts_w01(doc: dict[str, Any], **_: Any) -> list[CheckResult]:
    """STS-W01: StatefulSet에 volumeClaimTemplates 없으면 WARN."""
    vcts = doc.get("spec", {}).get("volumeClaimTemplates")
    if not vcts:
        return [
            CheckResult(
                rule_id="STS-W01",
                level="WARN",
                container="(statefulset)",
                message_ko="StatefulSet에 volumeClaimTemplates 없음 — 영구 스토리지 미설정",
                message_en=(
                    "StatefulSet has no volumeClaimTemplates"
                    " — persistent storage not configured."
                ),
                suggestion=(
                    "StatefulSet은 상태 저장 앱을 위한 리소스입니다. "
                    "spec.volumeClaimTemplates를 추가하여 PVC를 자동 생성하거나, "
                    "Deployment 사용을 검토하세요."
                ),
            )
        ]
    return []
