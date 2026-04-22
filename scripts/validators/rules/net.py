"""NET 규칙 — NET-W01."""

from __future__ import annotations

from typing import Any

from scripts._shared.types import CheckResult
from scripts.validators.registry import register_rule


@register_rule("manifest_set")
def rule_net_w01(_target: dict[str, Any], **kwargs: Any) -> list[CheckResult]:
    """NET-W01: manifest 집합에 NetworkPolicy 없으면 WARN."""
    docs: list[dict[str, Any]] = kwargs.get("docs") or []
    has_netpol = any(
        str(doc.get("kind", "")) == "NetworkPolicy" for doc in docs if doc
    )
    if not has_netpol:
        return [
            CheckResult(
                rule_id="NET-W01",
                level="WARN",
                container="(manifest_set)",
                message_ko="NetworkPolicy 없음 — 네트워크 격리 미설정",
                message_en="No NetworkPolicy found — network isolation not configured.",
                suggestion=(
                    "네임스페이스에 NetworkPolicy를 추가하여 불필요한 트래픽을 차단하세요. "
                    "cluster.network_policy: false로 설정하면 이 경고는 의도된 것입니다."
                ),
            )
        ]
    return []
