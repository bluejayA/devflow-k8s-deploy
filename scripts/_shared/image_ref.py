"""이미지 참조 검증 공용 유틸 (F-23, NFR-SEC).

DockerfileGenerator / ManifestGenerator 양쪽이 사용.
Unit 9(dockerfile_generator)에서 이동된 로직.
"""

from __future__ import annotations

import re

from scripts._shared.errors import InvalidImageError

# OCI image reference allowlist — 개행/공백/제어문자 완전 차단 (NFR-SEC)
# - repo: [a-z0-9][a-z0-9._/-]{0,253}
# - tag (선택): [A-Za-z0-9_][A-Za-z0-9_.-]{0,127}
# - digest (선택): @sha256:<64 hex>
# - 태그 또는 digest 중 최소 하나 필수 (validate 단계에서 추가 검증)
_IMAGE_REF_RE = re.compile(
    r"^(?P<repo>[a-z0-9][a-z0-9._/\-]{0,253})"
    r"(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}))?"
    r"(?:@sha256:(?P<digest>[0-9a-f]{64}))?$"
)


def validate_image_reference(image: str) -> None:
    """OCI 이미지 참조를 엄격 allowlist로 검증 (Unit 9에서 이동된 로직).

    허용:
      - ``alpine:3.19`` (태그)
      - ``alpine:3.19@sha256:<64 hex>`` (태그 + digest)
      - ``alpine@sha256:<64 hex>`` (digest only)

    거부 (InvalidImageError):
      - ``alpine`` (태그/digest 둘 다 없음)
      - ``alpine:latest`` (latest 태그 — 명시 거부)
      - ``alpine:latest@sha256:...`` (digest 우회 시도)
      - ``alpine\\nUSER root`` (개행 — 인젝션 시도)
      - digest가 64 hex가 아닌 값 (예: ``alpine@sha256:abc``)
      - 정규식 allowlist 위반 (공백/제어문자/비허용 문자)

    Args:
        image: 검증할 이미지 레퍼런스 문자열.

    Raises:
        InvalidImageError: 형식 위반, latest 태그, 태그/digest 누락 시.
    """
    # NFR-SEC: 개행/제어문자는 fullmatch 정규식이 차단
    match = _IMAGE_REF_RE.fullmatch(image)
    if not match:
        raise InvalidImageError(
            f"이미지 참조 형식이 유효하지 않음: {image!r}. "
            f"예: 'eclipse-temurin:21-jre-alpine' 또는 '<repo>@sha256:<64 hex digest>'"
        )
    tag = match.group("tag")
    digest = match.group("digest")
    # 태그 또는 digest 최소 하나 필수
    if tag is None and digest is None:
        raise InvalidImageError(
            f"이미지 태그 또는 digest 중 하나는 필수: {image!r}. "
            "F-23 재현성/공급망 보안 — latest 태그 대신 고정 태그 또는 digest pinning 사용."
        )
    # latest 태그 명시 거부 (digest 존재 여부와 무관)
    if tag == "latest":
        raise InvalidImageError(
            f"이미지 태그 'latest' 사용 금지 (F-23): {image!r}. "
            "구체 태그(예: ':3.19') 또는 digest pinning 사용."
        )
