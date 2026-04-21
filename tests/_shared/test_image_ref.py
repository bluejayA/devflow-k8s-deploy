"""TDD: image_ref — 공용 이미지 참조 검증 유틸.

scripts/_shared/image_ref.py의 validate_image_reference 함수 단위 테스트.
"""

from __future__ import annotations

import pytest

from scripts._shared.errors import InvalidImageError
from scripts._shared.image_ref import validate_image_reference

# ---------------------------------------------------------------------------
# 1. 정상 태그 통과
# ---------------------------------------------------------------------------


def test_valid_tag_passes() -> None:
    validate_image_reference("eclipse-temurin:21-jdk-alpine")  # no raise


def test_valid_tag_with_repo_passes() -> None:
    validate_image_reference("myrepo/my-app:1.0.0")  # no raise


def test_valid_semver_tag_passes() -> None:
    validate_image_reference("alpine:3.19")  # no raise


# ---------------------------------------------------------------------------
# 2. digest pinning 허용
# ---------------------------------------------------------------------------


def test_digest_pinning_allowed() -> None:
    digest = "a" * 64
    validate_image_reference(f"alpine@sha256:{digest}")  # no raise


def test_tag_with_digest_allowed() -> None:
    digest = "a" * 64
    validate_image_reference(f"eclipse-temurin:21-jdk-alpine@sha256:{digest}")  # no raise


# ---------------------------------------------------------------------------
# 3. latest 태그 거부
# ---------------------------------------------------------------------------


def test_latest_tag_raises() -> None:
    with pytest.raises(InvalidImageError, match="latest"):
        validate_image_reference("alpine:latest")


def test_latest_with_digest_bypass_rejected() -> None:
    """latest+digest 우회 시도도 거부."""
    digest = "a" * 64
    with pytest.raises(InvalidImageError, match="latest"):
        validate_image_reference(f"alpine:latest@sha256:{digest}")


# ---------------------------------------------------------------------------
# 4. 태그/digest 모두 없으면 거부
# ---------------------------------------------------------------------------


def test_no_tag_or_digest_raises() -> None:
    with pytest.raises(InvalidImageError):
        validate_image_reference("alpine")


# ---------------------------------------------------------------------------
# 5. 개행 포함 이미지 참조 거부
# ---------------------------------------------------------------------------


def test_newline_in_image_raises() -> None:
    with pytest.raises(InvalidImageError):
        validate_image_reference("alpine:3.19\nUSER root\n")


# ---------------------------------------------------------------------------
# 6. 짧은 digest 거부 (64 hex 미달)
# ---------------------------------------------------------------------------


def test_short_digest_raises() -> None:
    with pytest.raises(InvalidImageError):
        validate_image_reference("alpine@sha256:abc123")


# ---------------------------------------------------------------------------
# 7. 유효하지 않은 형식 (공백 포함) 거부
# ---------------------------------------------------------------------------


def test_space_in_image_raises() -> None:
    with pytest.raises(InvalidImageError):
        validate_image_reference("alpine: 3.19")
