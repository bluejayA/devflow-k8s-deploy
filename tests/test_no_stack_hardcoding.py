"""BL-001 Phase 8 — NFR-EXT-01 회귀 가드.

Phase 3에서 manifest 하드코딩을 제거하고 defaults.run_as_user / defaults.writable_paths
기반으로 동적화했다. 이 테스트는 그 결정이 깨지지 않도록 락다운한다.

검증 대상:
- templates/manifest/*.tmpl: runAsUser/fsGroup이 Jinja 변수로 렌더되어야 함
- scripts/manifest_generator.py: 코드 경로에 runAsUser/fsGroup의 stack-specific
  literal 값(1000, 65532)이 직접 등장하지 않아야 함 (docstring/주석은 허용)
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# 코드 경로(런타임 분기/파라미터)에 등장하면 회귀로 판정할 패턴.
# `runAsUser` 또는 `fsGroup` 키 뒤에 stack-specific 정수 리터럴이 직접 붙은 형태.
_HARDCODED_UID_RE = re.compile(
    r"""(?ix)
    runAsUser \s*[:=]\s* (1000|65532) \b
    | fsGroup  \s*[:=]\s* (1000|65532) \b
    """
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_deployment_template_uses_dynamic_run_as_user() -> None:
    """deployment.tmpl의 runAsUser/fsGroup이 Jinja 변수로 치환되어야 함."""
    tmpl = _read(PROJECT_ROOT / "templates" / "manifest" / "deployment.tmpl")
    # Jinja 변수 사용 확인
    assert "{{ run_as_user }}" in tmpl, (
        "deployment.tmpl이 {{ run_as_user }} 변수를 사용해야 함 (F-31)"
    )
    # 하드코딩된 UID literal 부재 (1000 또는 65532를 'runAsUser:' / 'fsGroup:' 직후 사용 금지)
    matches = _HARDCODED_UID_RE.findall(tmpl)
    assert not matches, (
        f"deployment.tmpl에 stack-specific UID 하드코딩 발견: {matches}"
    )


def test_statefulset_template_uses_dynamic_run_as_user() -> None:
    sts_path = PROJECT_ROOT / "templates" / "manifest" / "statefulset.tmpl"
    if not sts_path.exists():
        return  # statefulset 템플릿은 BL-003 단계에 추가된 후속이므로 부재 시 건너뜀
    tmpl = _read(sts_path)
    if "runAsUser" in tmpl:
        assert "{{ run_as_user }}" in tmpl
        matches = _HARDCODED_UID_RE.findall(tmpl)
        assert not matches, f"statefulset.tmpl 하드코딩: {matches}"


def test_manifest_generator_has_no_runtime_uid_literal() -> None:
    """scripts/manifest_generator.py 코드 경로(런타임 분기)에 hardcoded UID 부재.

    docstring/주석/lookup 키에 등장하는 것은 허용. assignment/return/dict literal에서
    `runAsUser: 1000` 또는 `fsGroup=65532` 같은 직접 사용은 회귀.
    """
    src = _read(PROJECT_ROOT / "scripts" / "manifest_generator.py")

    # 줄 단위로 보고, `#` 주석이나 docstring 가능성이 높은 라인은 제외
    offending: list[str] = []
    in_docstring = False
    for line in src.splitlines():
        stripped = line.strip()
        # 단순 docstring 토글 (정확하진 않지만 보수적)
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        if stripped.startswith("#"):
            continue
        if _HARDCODED_UID_RE.search(line):
            offending.append(line)
    assert not offending, (
        "manifest_generator.py 코드 경로에 stack-specific UID 하드코딩:\n  "
        + "\n  ".join(offending)
    )


def test_jvm_template_for_runner_image_string_not_in_manifest_generator() -> None:
    """manifest_generator는 stack 이름이나 stack-specific 이미지 이름을 알지 않아야 함.

    NFR-EXT-01: stack 결정은 StackModule이, manifest는 stack 중립이어야 함.
    """
    src = _read(PROJECT_ROOT / "scripts" / "manifest_generator.py")
    # 코드 라인에서 "jvm" / "spring" 단어가 stack 결정용으로 등장하면 회귀
    for token in ("jvm", "spring-boot", "eclipse-temurin", "gradle:jdk", "golang:"):
        # 주석/docstring 제외하기 위해 단순 grep + 핵심 패턴
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            if token in line:
                # 추가 검사: 변수명이나 식별자에 우연히 포함되었는지 더 엄격히는
                # AST 분석이 필요하나, 현 단계에선 "literal string에 토큰 포함"이 위험 신호.
                if f'"{token}' in line or f"'{token}" in line:
                    raise AssertionError(
                        f"manifest_generator.py가 stack-specific 토큰 '{token}'을 "
                        f"literal로 참조: {line.strip()}"
                    )
