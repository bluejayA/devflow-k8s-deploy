"""결정론적 Jinja2 템플릿 렌더링 중심지.

TemplateRenderer는 Dockerfile/Kubernetes manifest 템플릿을 렌더링한다.
결정론성 보장:
  - 방어적 결정론 가드: 현재 템플릿은 모두 스칼라 치환이라 dict 순서에 무관하지만,
    향후 템플릿이 ``{{ my_dict }}`` 또는 ``{% for k, v in my_dict.items() %}`` 형태로
    dict 자체를 순회/출력하게 되면 결정론성이 깨진다. 이 가드는 그 시나리오를 선제 방어한다.
  - autoescape=False (YAML/Dockerfile은 HTML escape 불필요)
  - finalize=lambda: None → '' (None 값을 빈 문자열로)
  - undefined=StrictUndefined (미정의 변수 즉시 에러)
  - 렌더 결과는 _normalize 통과 (연속 빈 라인, trailing whitespace, EOF newline)

## 보안 책임 경계 (context sanitization)

``autoescape=False`` 정책상 **context 값의 YAML/Dockerfile 구조 안전성은 렌더러가 방어하지 않는다**.
개행(``\\n``), 따옴표, ``|``, ``:``, YAML 제어 문자 등 특수 문자가 포함된 값이 인용부호 없이
템플릿에 삽입되면 YAML 구조 붕괴 또는 Dockerfile 명령 주입으로 이어질 수 있다.

**호출자 책임**: 이 렌더러를 사용하는 Generator unit(``dockerfile_generator``,
``manifest_generator``)은 context 값의 특수 문자 처리(이스케이프/인용/거부)를 보장해야 한다.
렌더러는 "주어진 context를 그대로 치환하는 순수 엔진"이다.

**템플릿 작성 규칙 (Generator 측)**: YAML 값은 ``"{{ value }}"`` 인용부호로 감싸거나
``{{ value | tojson }}`` 필터를 쓰는 것을 원칙으로 한다.
단순 ``{{ value }}``는 정적·검증된 context에만 허용.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from scripts._shared.errors import TemplateNotFoundError

_IDENTIFIER_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class TemplateRenderer:
    """Jinja2 기반 결정론적 템플릿 렌더링 중심지."""

    def __init__(self, template_root: Path) -> None:
        """Jinja2 Environment 초기화.

        Args:
            template_root: 템플릿 루트 디렉토리 (예: ${CLAUDE_PLUGIN_ROOT}/templates).
        """
        self._template_root = template_root
        self._env = Environment(
            loader=FileSystemLoader(str(template_root)),
            autoescape=False,
            finalize=lambda x: x if x is not None else "",
            keep_trailing_newline=False,
            undefined=StrictUndefined,
            trim_blocks=True,       # {% %} 블록 뒤 개행 자동 제거
            lstrip_blocks=True,     # {% %} 블록 앞 공백/탭 자동 제거
        )

    def render_dockerfile(self, stack: str, context: dict[str, object]) -> str:
        """templates/dockerfile/{stack}.tmpl 렌더링.

        context 키는 알파벳 정렬 후 전달 (결정론성).
        렌더 결과는 _normalize 통과.

        Args:
            stack: 스택 이름 (예: 'jvm', 'test'). 소문자 알파누메릭·하이픈·언더스코어만 허용.
            context: 렌더링 변수 사전.

        Returns:
            정규화된 Dockerfile 문자열.

        Raises:
            ValueError: stack 식별자가 허용 패턴에 맞지 않을 때.
            TemplateNotFoundError: 템플릿 파일이 없을 때.
            jinja2.UndefinedError: 미정의 변수 참조 시.
            jinja2.TemplateSyntaxError: 잘못된 Jinja2 구문 시.
        """
        if not _IDENTIFIER_RE.fullmatch(stack):
            raise ValueError(
                f"잘못된 stack 식별자: {stack!r} (허용: ^[a-z0-9][a-z0-9_-]{{0,63}}$)"
            )
        template_path = f"dockerfile/{stack}.tmpl"
        return self._render(template_path, context)

    def render_manifest(self, kind: str, context: dict[str, object]) -> str:
        """templates/manifest/{kind}.tmpl 렌더링.

        kind는 'deployment' | 'service' | 'serviceaccount' 중 하나.
        렌더 결과는 _normalize 통과.

        Args:
            kind: manifest 종류 (예: 'deployment', 'service', 'serviceaccount').
                  소문자 알파누메릭·하이픈·언더스코어만 허용.
            context: 렌더링 변수 사전.

        Returns:
            정규화된 YAML 문자열.

        Raises:
            ValueError: kind 식별자가 허용 패턴에 맞지 않을 때.
            TemplateNotFoundError: 템플릿 파일이 없을 때.
            jinja2.UndefinedError: 미정의 변수 참조 시.
            jinja2.TemplateSyntaxError: 잘못된 Jinja2 구문 시.
        """
        if not _IDENTIFIER_RE.fullmatch(kind):
            raise ValueError(
                f"잘못된 kind 식별자: {kind!r} (허용: ^[a-z0-9][a-z0-9_-]{{0,63}}$)"
            )
        template_path = f"manifest/{kind}.tmpl"
        return self._render(template_path, context)

    def _render(self, template_path: str, context: dict[str, object]) -> str:
        """실제 렌더링 수행 헬퍼.

        context 키를 알파벳 순 정렬하여 결정론적 렌더링 보장.

        Args:
            template_path: template_root 기준 상대 경로.
            context: 렌더링 변수 사전.

        Returns:
            _normalize 통과한 렌더 결과.

        Raises:
            TemplateNotFoundError: 템플릿 파일이 없을 때.
        """
        # 방어적 결정론 가드: 향후 dict 자체를 출력하는 템플릿 대비
        # (스칼라 치환만 있는 현재는 no-op)
        sorted_context = dict(sorted(context.items()))
        try:
            tmpl = self._env.get_template(template_path)
        except TemplateNotFound as exc:
            raise TemplateNotFoundError(
                f"템플릿 파일을 찾을 수 없습니다: {template_path}"
            ) from exc
        rendered = tmpl.render(**sorted_context)
        return self._normalize(rendered)

    def _normalize(self, content: str) -> str:
        """출력 문자열 정규화.

        1) 각 라인 끝 trailing whitespace 제거
        2) 연속 빈 라인을 1개로 축소
        3) EOF에 정확히 1개 newline

        ``\\r\\n`` (CRLF) 및 ``\\r`` (CR) 라인 종결자는 ``\\n`` (LF)로 정규화된다
        (``splitlines()`` 규약).

        Args:
            content: 정규화 대상 문자열.

        Returns:
            정규화된 문자열.
        """
        # 1) 각 라인 끝 trailing whitespace 제거
        lines = [line.rstrip() for line in content.splitlines()]

        # 2) 연속 빈 라인을 1개로 축소 (re로 처리하기 위해 join 후 적용)
        joined = "\n".join(lines)
        normalized = re.sub(r"\n{3,}", "\n\n", joined)

        # 3) EOF trailing newlines 정리 후 정확히 1개 추가
        normalized = normalized.rstrip("\n") + "\n"

        return normalized
