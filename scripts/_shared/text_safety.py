"""텍스트 안전 유틸리티 — 주입 방어 + 민감정보 redact.

개행/제어문자 차단 (reject_unsafe_chars) 및
subprocess stderr 등 자유 텍스트의 민감정보 치환 (redact_sensitive) 제공.

DockerfileGenerator, ManifestGenerator, OutputPackager 세 곳이 공유한다.
"""

from __future__ import annotations

import re

# 개행/CR/NUL — Markdown·YAML·Dockerfile 컨텍스트 모두 위험
_UNSAFE_CHARS = ("\n", "\r", "\x00")

# Go entrypoint 정규식: '.' 또는 './seg(/seg)*'. seg 문자셋은 [a-zA-Z0-9._-] (F-29).
# `..` 세그먼트는 정규식만으로 거부할 수 없어 별도 검사로 처리한다.
_GO_ENTRYPOINT_RE = re.compile(r"^\.(/[a-zA-Z0-9._-]+)*$")

# 민감정보 redact 패턴 목록 (kubectl stderr / kubeconfig 경로 / JWT 등)
_REDACT_PATTERNS: list[re.Pattern[str]] = [
    # Bearer tokens (Authorization 헤더, k8s API 토큰)
    re.compile(r"Bearer\s+[A-Za-z0-9._\-+/=]{20,}", re.IGNORECASE),
    # --token=... / token: ... (kubectl/CLI 인자)
    re.compile(r"--?token[=:]\s*[A-Za-z0-9._\-+/=]{8,}", re.IGNORECASE),
    # --kubeconfig=... (경로)
    re.compile(r"--?kubeconfig[=:]\s*\S+", re.IGNORECASE),
    # JWT 3-part (eyJ로 시작하는 base64 URL-safe)
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    # password=/secret=/apikey= 인자
    re.compile(r"(?i)(?:password|passwd|secret|api[_-]?key|auth[_-]?key)[=:]\s*\S+"),
]

_REDACTED_PLACEHOLDER = "[REDACTED]"


def reject_unsafe_chars(
    value: str,
    field_name: str,
    *,
    exc_type: type[Exception] = ValueError,
    message_prefix: str = "필드에 제어문자 포함 금지",
) -> None:
    """개행/CR/NUL 포함 시 예외 raise. 호출자는 exc_type 지정 가능.

    Args:
        value: 검증할 문자열.
        field_name: 오류 메시지에 포함될 필드명.
        exc_type: raise할 예외 타입 (기본 ValueError, InvalidImageError 등 지정 가능).
        message_prefix: 오류 메시지 앞에 붙일 접두어.

    Raises:
        exc_type: 개행 또는 NUL 문자가 포함된 경우.
    """
    for ch in _UNSAFE_CHARS:
        if ch in value:
            raise exc_type(f"{message_prefix}: {field_name}={value!r}")


def validate_go_entrypoint(value: str) -> None:
    """Go `build_plan`이 build_cmd에 삽입하기 전 entrypoint 문자열 안전 검증 (F-29).

    허용:
      - "." (루트 main.go)
      - "./cmd/<name>" 형태 (필요 시 깊은 경로)

    거부 (공백/세미콜론/$/백틱/따옴표/개행 등 shell 메타문자, 절대경로, `..` 세그먼트):
      이는 `build_cmd = f'go build -o {app_name} {entrypoint}'` 문자열 합성 시
      shell 토큰 분리/명령 분리/path traversal로 이어질 수 있다.

    Args:
        value: 검증할 entrypoint 문자열.

    Raises:
        ValueError: 정규식 불일치 또는 `..` 세그먼트 포함 시.
    """
    if not _GO_ENTRYPOINT_RE.fullmatch(value):
        raise ValueError(f"Go entrypoint 형식 오류: entrypoint={value!r}")
    # 정규식이 [a-zA-Z0-9._-]를 허용하므로 `..` 세그먼트가 통과 가능 — 별도 차단.
    for segment in value.split("/"):
        if segment == "..":
            raise ValueError(
                f"Go entrypoint path traversal 금지: entrypoint={value!r}"
            )


def redact_sensitive(text: str) -> str:
    """subprocess stderr/에러 메시지의 민감정보 패턴을 [REDACTED]로 치환.

    개행은 허용하되, Bearer 토큰·JWT·kubeconfig 경로·secret 인자를 마스킹한다.

    Args:
        text: 처리할 자유 텍스트 (stderr 원문 등).

    Returns:
        민감정보가 [REDACTED]로 치환된 문자열. 입력이 빈 문자열이면 그대로 반환.
    """
    if not text:
        return text
    result = text
    for pattern in _REDACT_PATTERNS:
        result = pattern.sub(_REDACTED_PLACEHOLDER, result)
    return result
