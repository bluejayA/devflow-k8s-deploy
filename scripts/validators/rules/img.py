"""IMG 규칙 — IMG-001, IMG-W01, IMG-W02."""

from __future__ import annotations

from typing import Any

from scripts._shared.types import CheckResult
from scripts.validators.registry import register_rule


@register_rule("container")
def rule_img001(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """IMG-001: latest 태그 또는 태그 누락 금지."""
    name = str(c.get("name", "unknown"))
    image = str(c.get("image", ""))
    image_no_digest = image.split("@")[0]
    has_tag = ":" in image_no_digest.split("/")[-1]
    is_latest = image_no_digest.endswith(":latest")
    if is_latest or not has_tag:
        return [
            CheckResult(
                rule_id="IMG-001",
                level="FAIL",
                container=name,
                message_ko=f"이미지 태그가 'latest'이거나 태그가 없음: {image!r}",
                message_en=f"Image tag is 'latest' or missing: {image!r}.",
                suggestion=(
                    "myregistry.io/app:v1.2.3 형식으로 명시적 버전 태그를 사용하세요. "
                    "latest 또는 무태그 이미지는 재현 불가 배포를 유발합니다."
                ),
            )
        ]
    return [
        CheckResult(
            rule_id="IMG-001",
            level="PASS",
            container=name,
            message_ko=f"이미지 태그가 명시되어 있습니다: {image!r}.",
            message_en=f"Image tag is explicitly set: {image!r}.",
            suggestion="",
        )
    ]


@register_rule("container")
def rule_img_w01(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """IMG-W01: digest pinning(@sha256:...) 미사용 시 WARN."""
    name = str(c.get("name", "unknown"))
    image = str(c.get("image", ""))
    if "@sha256:" in image:
        return []
    image_no_digest = image.split("@")[0]
    has_tag = ":" in image_no_digest.split("/")[-1]
    is_latest = image_no_digest.endswith(":latest")
    if is_latest or not has_tag:
        return []
    return [
        CheckResult(
            rule_id="IMG-W01",
            level="WARN",
            container=name,
            message_ko=f"이미지 digest pinning 미사용: {image!r}",
            message_en=f"Image digest pinning is not used: {image!r}.",
            suggestion=(
                "image: myregistry.io/app:v1.2.3@sha256:... 형식으로 "
                "digest를 고정하면 이미지 교체 공격(supply chain attack)을 방지할 수 있습니다."
            ),
        )
    ]


@register_rule("container")
def rule_img_w02(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """IMG-W02: imagePullPolicy=Always + digest 미사용 WARN."""
    name = str(c.get("name", "unknown"))
    image = str(c.get("image", ""))
    pull_policy = str(c.get("imagePullPolicy", ""))
    if pull_policy != "Always":
        return []
    if "@sha256:" in image:
        return []
    return [
        CheckResult(
            rule_id="IMG-W02",
            level="WARN",
            container=name,
            message_ko=f"imagePullPolicy=Always이지만 digest가 없음: {image!r}",
            message_en=f"imagePullPolicy=Always but no digest: {image!r}.",
            suggestion=(
                "imagePullPolicy: Always와 함께 @sha256: digest를 사용하면 "
                "레지스트리에서 항상 동일한 이미지를 pull합니다."
            ),
        )
    ]
