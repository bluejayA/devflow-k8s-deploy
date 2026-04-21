"""TDD: text_safety 유틸리티 — reject_unsafe_chars + redact_sensitive.

RED → GREEN → REFACTOR 순서.
"""

from __future__ import annotations

import pytest

from scripts._shared.errors import InvalidImageError
from scripts._shared.text_safety import (
    redact_sensitive,
    reject_unsafe_chars,
)

# ---------------------------------------------------------------------------
# reject_unsafe_chars 테스트
# ---------------------------------------------------------------------------


class TestRejectUnsafeChars:
    """reject_unsafe_chars 단위 테스트."""

    # 1. 개행 포함 시 ValueError (기본)
    def test_newline_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="field_test"):
            reject_unsafe_chars("hello\nworld", "field_test")

    # 2. CR 포함 시 ValueError
    def test_carriage_return_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            reject_unsafe_chars("hello\rworld", "field_cr")

    # 3. NUL 포함 시 ValueError
    def test_nul_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            reject_unsafe_chars("hello\x00world", "field_nul")

    # 4. 정상 문자열 → 예외 없음
    def test_clean_string_no_exception(self) -> None:
        reject_unsafe_chars("normal-string_123", "field_ok")  # 예외 없음

    # 5. 빈 문자열 → 예외 없음
    def test_empty_string_no_exception(self) -> None:
        reject_unsafe_chars("", "field_empty")  # 예외 없음

    # 6. exc_type=InvalidImageError → InvalidImageError raise
    def test_custom_exc_type_invalid_image_error(self) -> None:
        with pytest.raises(InvalidImageError):
            reject_unsafe_chars(
                "image\nUSER root",
                "builder_image",
                exc_type=InvalidImageError,
                message_prefix="Dockerfile 주입 방어",
            )

    # 7. message_prefix가 오류 메시지에 포함되는지
    def test_message_prefix_in_error(self) -> None:
        with pytest.raises(ValueError, match="YAML 주입 방어"):
            reject_unsafe_chars(
                "value\nwith-newline",
                "namespace",
                message_prefix="YAML 주입 방어",
            )

    # 8. 탭 문자 → 예외 없음 (탭은 허용)
    def test_tab_char_allowed(self) -> None:
        reject_unsafe_chars("hello\tworld", "field_tab")  # 예외 없음


# ---------------------------------------------------------------------------
# redact_sensitive 테스트
# ---------------------------------------------------------------------------


class TestRedactSensitive:
    """redact_sensitive 단위 테스트."""

    # 9. Bearer 토큰 redact
    def test_bearer_token_redacted(self) -> None:
        text = "Authorization: Bearer eyABCDEFGHIJKLMNOPQRSTUVWXYZ12345"
        result = redact_sensitive(text)
        assert "[REDACTED]" in result
        assert "eyABCDEFGHIJKLMNOPQRSTUVWXYZ12345" not in result

    # 10. --kubeconfig 경로 redact
    def test_kubeconfig_path_redacted(self) -> None:
        text = "kubectl apply --kubeconfig=/home/user/.kube/config -f deployment.yaml"
        result = redact_sensitive(text)
        assert "[REDACTED]" in result
        assert "/home/user/.kube/config" not in result

    # 11. JWT 3-part redact
    def test_jwt_token_redacted(self) -> None:
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature_here"
        text = f"token={jwt}"
        result = redact_sensitive(text)
        assert "[REDACTED]" in result
        assert jwt not in result

    # 12. --token= 인자 redact
    def test_token_arg_redacted(self) -> None:
        text = "kubectl get pods --token=mysecrettoken123"
        result = redact_sensitive(text)
        assert "[REDACTED]" in result
        assert "mysecrettoken123" not in result

    # 13. password= redact
    def test_password_arg_redacted(self) -> None:
        text = "connect password=s3cr3tP@ssword to database"
        result = redact_sensitive(text)
        assert "[REDACTED]" in result
        assert "s3cr3tP@ssword" not in result

    # 14. secret= redact
    def test_secret_arg_redacted(self) -> None:
        text = "export secret=my-api-secret-value"
        result = redact_sensitive(text)
        assert "[REDACTED]" in result
        assert "my-api-secret-value" not in result

    # 15. 민감정보 없는 일반 텍스트 → 변경 없음
    def test_clean_text_unchanged(self) -> None:
        text = "kubectl apply -f deployment.yaml completed successfully"
        result = redact_sensitive(text)
        assert result == text

    # 16. 빈 문자열 → 빈 문자열 반환
    def test_empty_string_returned(self) -> None:
        assert redact_sensitive("") == ""

    # 17. 개행 포함 여러 줄 텍스트에서 Bearer 토큰 redact
    def test_multiline_bearer_redacted(self) -> None:
        text = "Error occurred\nAuthorization: Bearer ABCDEFGHIJKLMNOPQRSTUVWXYZ12345\nDetails: ..."
        result = redact_sensitive(text)
        assert "[REDACTED]" in result
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ12345" not in result
        # 개행은 유지되어야 함
        assert "\n" in result

    # 18. api_key= redact
    def test_api_key_redacted(self) -> None:
        text = "api_key=sk-proj-abcdefghijklmnop123"
        result = redact_sensitive(text)
        assert "[REDACTED]" in result
        assert "sk-proj-abcdefghijklmnop123" not in result
