"""결정론적 Jinja2 템플릿 렌더링 중심지.

TemplateRenderer는 Dockerfile/Kubernetes manifest 템플릿을 렌더링한다.
결정론성 보장:
  - context 키는 알파벳 순 정렬 후 전달 (키 순서 의존 제거)
  - autoescape=False (YAML/Dockerfile은 HTML escape 불필요)
  - finalize=lambda: None → '' (None 값을 빈 문자열로)
  - undefined=StrictUndefined (미정의 변수 즉시 에러)
  - 렌더 결과는 _normalize 통과 (연속 빈 라인, trailing whitespace, EOF newline)
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from scripts._shared.errors import TemplateNotFoundError


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
        )

    def render_dockerfile(self, stack: str, context: dict[str, object]) -> str:
        """templates/dockerfile/{stack}.tmpl 렌더링.

        context 키는 알파벳 정렬 후 전달 (결정론성).
        렌더 결과는 _normalize 통과.

        Args:
            stack: 스택 이름 (예: 'jvm', 'test').
            context: 렌더링 변수 사전.

        Returns:
            정규화된 Dockerfile 문자열.

        Raises:
            TemplateNotFoundError: 템플릿 파일이 없을 때.
            jinja2.UndefinedError: 미정의 변수 참조 시.
            jinja2.TemplateSyntaxError: 잘못된 Jinja2 구문 시.
        """
        template_path = f"dockerfile/{stack}.tmpl"
        return self._render(template_path, context)

    def render_manifest(self, kind: str, context: dict[str, object]) -> str:
        """templates/manifest/{kind}.tmpl 렌더링.

        kind는 'deployment' | 'service' | 'serviceaccount' 중 하나.
        렌더 결과는 _normalize 통과.

        Args:
            kind: manifest 종류 (예: 'deployment', 'service', 'serviceaccount').
            context: 렌더링 변수 사전.

        Returns:
            정규화된 YAML 문자열.

        Raises:
            TemplateNotFoundError: 템플릿 파일이 없을 때.
            jinja2.UndefinedError: 미정의 변수 참조 시.
            jinja2.TemplateSyntaxError: 잘못된 Jinja2 구문 시.
        """
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
