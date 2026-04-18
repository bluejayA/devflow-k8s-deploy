"""TDD: TemplateRenderer — 결정론적 Jinja2 렌더링 + _normalize.

RED → GREEN → REFACTOR 순서.
"""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

import pytest
import yaml
from jinja2 import UndefinedError

from scripts._shared.errors import TemplateNotFoundError
from scripts.template_renderer import TemplateRenderer

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_renderer(tmp_path: Path) -> TemplateRenderer:
    """tmp_path 아래에 templates/ 디렉토리를 갖는 TemplateRenderer 생성."""
    (tmp_path / "templates" / "dockerfile").mkdir(parents=True, exist_ok=True)
    (tmp_path / "templates" / "manifest").mkdir(parents=True, exist_ok=True)
    return TemplateRenderer(tmp_path / "templates")


def _write_template(tmp_path: Path, rel: str, content: str) -> None:
    """templates/{rel} 위치에 템플릿 파일 생성."""
    target = tmp_path / "templates" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. 결정론 — cksum 동일 (같은 context, 다른 키 순서)
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_context_different_order_produces_identical_sha256(
        self, tmp_path: Path
    ) -> None:
        """context 키 순서가 달라도 동일 렌더 결과 (SHA-256 일치)."""
        _write_template(tmp_path, "dockerfile/app.tmpl", "FROM {{ base }}\nRUN echo {{ cmd }}\n")
        renderer = _make_renderer(tmp_path)

        ctx_a = {"base": "alpine:3.18", "cmd": "hello"}
        ctx_b = {"cmd": "hello", "base": "alpine:3.18"}

        out_a = renderer.render_dockerfile("app", ctx_a)
        out_b = renderer.render_dockerfile("app", ctx_b)

        hash_a = hashlib.sha256(out_a.encode()).hexdigest()
        hash_b = hashlib.sha256(out_b.encode()).hexdigest()

        assert hash_a == hash_b

    def test_two_renderer_instances_same_root_produce_identical_output(
        self, tmp_path: Path
    ) -> None:
        """같은 template_root로 두 번 TemplateRenderer 생성해도 결과 동일."""
        _write_template(
            tmp_path,
            "dockerfile/app.tmpl",
            "FROM {{ image }}\nLABEL version={{ ver }}\n",
        )
        _make_renderer(tmp_path)  # 디렉토리 생성용 (이미 _write_template이 만들었지만 안전하게)

        ctx = {"image": "ubuntu:22.04", "ver": "1.0"}
        r1 = TemplateRenderer(tmp_path / "templates")
        r2 = TemplateRenderer(tmp_path / "templates")

        assert r1.render_dockerfile("app", ctx) == r2.render_dockerfile("app", ctx)


# ---------------------------------------------------------------------------
# 2. _normalize — 빈 라인 정규화
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_consecutive_blank_lines_collapsed_to_one(self, tmp_path: Path) -> None:
        """연속 빈 라인 3개 → 1개 (a\\n\\n\\n\\nb → a\\n\\nb)."""
        renderer = _make_renderer(tmp_path)
        result = renderer._normalize("a\n\n\n\nb")
        assert result == "a\n\nb\n"

    def test_trailing_whitespace_removed(self, tmp_path: Path) -> None:
        """각 라인 끝 trailing whitespace 제거."""
        renderer = _make_renderer(tmp_path)
        result = renderer._normalize("line   \nnext")
        assert result == "line\nnext\n"

    def test_eof_newline_added_when_missing(self, tmp_path: Path) -> None:
        """EOF newline 없으면 1개 추가."""
        renderer = _make_renderer(tmp_path)
        result = renderer._normalize("content")
        assert result == "content\n"

    def test_eof_multiple_newlines_collapsed_to_one(self, tmp_path: Path) -> None:
        """EOF trailing newline 여러 개 → 정확히 1개."""
        renderer = _make_renderer(tmp_path)
        result = renderer._normalize("content\n\n\n")
        assert result == "content\n"

    def test_eof_single_newline_unchanged(self, tmp_path: Path) -> None:
        """이미 EOF newline 1개이면 변경 없음."""
        renderer = _make_renderer(tmp_path)
        result = renderer._normalize("content\n")
        assert result == "content\n"

    def test_mixed_normalization(self, tmp_path: Path) -> None:
        """trailing whitespace + 연속 빈 라인 + trailing newline 복합."""
        renderer = _make_renderer(tmp_path)
        raw = "first   \n\n\n\nsecond  \n"
        result = renderer._normalize(raw)
        assert result == "first\n\nsecond\n"


# ---------------------------------------------------------------------------
# 3. finalize — None → ''
# ---------------------------------------------------------------------------


class TestFinalizeNoneToEmpty:
    def test_none_value_rendered_as_empty_string(self, tmp_path: Path) -> None:
        """context에 None 값이 있으면 템플릿에서 빈 문자열로 렌더."""
        _write_template(tmp_path, "dockerfile/nullable.tmpl", "VAR={{ value }}\n")
        renderer = _make_renderer(tmp_path)

        result = renderer.render_dockerfile("nullable", {"value": None})
        # _normalize 후에도 VAR= 라인이 그대로여야 함
        assert "VAR=\n" in result


# ---------------------------------------------------------------------------
# 4. StrictUndefined — 미정의 변수 에러
# ---------------------------------------------------------------------------


class TestStrictUndefined:
    def test_undefined_variable_raises_undefined_error(self, tmp_path: Path) -> None:
        """템플릿에 {{ missing_var }}이 있고 context에 없으면 UndefinedError."""
        _write_template(tmp_path, "dockerfile/strict.tmpl", "FROM {{ missing_var }}\n")
        renderer = _make_renderer(tmp_path)

        with pytest.raises(UndefinedError):
            renderer.render_dockerfile("strict", {})

    def test_undefined_variable_in_manifest_raises_undefined_error(
        self, tmp_path: Path
    ) -> None:
        """manifest 렌더에서도 동일하게 UndefinedError."""
        _write_template(tmp_path, "manifest/deploy.tmpl", "name: {{ undefined_key }}\n")
        renderer = _make_renderer(tmp_path)

        with pytest.raises(UndefinedError):
            renderer.render_manifest("deploy", {})


# ---------------------------------------------------------------------------
# 5. TemplateNotFoundError
# ---------------------------------------------------------------------------


class TestTemplateNotFound:
    def test_dockerfile_not_found_raises_template_not_found_error(
        self, tmp_path: Path
    ) -> None:
        """존재하지 않는 dockerfile 템플릿 → TemplateNotFoundError."""
        renderer = _make_renderer(tmp_path)

        with pytest.raises(TemplateNotFoundError):
            renderer.render_dockerfile("nonexistent", {})

    def test_manifest_not_found_raises_template_not_found_error(
        self, tmp_path: Path
    ) -> None:
        """존재하지 않는 manifest 템플릿 → TemplateNotFoundError."""
        renderer = _make_renderer(tmp_path)

        with pytest.raises(TemplateNotFoundError):
            renderer.render_manifest("nonexistent", {})


# ---------------------------------------------------------------------------
# 6. 기본 Dockerfile 렌더 — 미니 템플릿
# ---------------------------------------------------------------------------


class TestRenderDockerfile:
    def test_basic_dockerfile_render(self, tmp_path: Path) -> None:
        """간단한 Dockerfile 템플릿 렌더링."""
        _write_template(
            tmp_path,
            "dockerfile/test.tmpl",
            "FROM {{ base_image }}\nUSER appuser\n",
        )
        renderer = _make_renderer(tmp_path)

        result = renderer.render_dockerfile("test", {"base_image": "alpine:3.18"})

        assert "FROM alpine:3.18" in result
        assert "USER appuser" in result

    def test_dockerfile_render_normalize_applied(self, tmp_path: Path) -> None:
        """render_dockerfile 결과는 _normalize 통과 — EOF newline 보장."""
        _write_template(
            tmp_path,
            "dockerfile/eoftest.tmpl",
            "FROM {{ base_image }}",  # EOF newline 없음
        )
        renderer = _make_renderer(tmp_path)

        result = renderer.render_dockerfile("eoftest", {"base_image": "alpine:3.18"})

        assert result.endswith("\n")
        assert result.count("\n") == 1  # 정확히 1개 newline만


# ---------------------------------------------------------------------------
# 7. 기본 manifest 렌더 — 미니 템플릿 + yaml.safe_load 파싱 가능
# ---------------------------------------------------------------------------


class TestRenderManifest:
    def test_basic_manifest_render_is_valid_yaml(self, tmp_path: Path) -> None:
        """manifest 렌더 결과를 yaml.safe_load로 파싱 가능해야 함."""
        template_content = textwrap.dedent(
            """\
            apiVersion: v1
            kind: ConfigMap
            metadata:
              name: {{ name }}
              namespace: {{ namespace }}
            """
        )
        _write_template(tmp_path, "manifest/test.tmpl", template_content)
        renderer = _make_renderer(tmp_path)

        result = renderer.render_manifest("test", {"name": "my-config", "namespace": "default"})

        parsed = yaml.safe_load(result)
        assert parsed["apiVersion"] == "v1"
        assert parsed["kind"] == "ConfigMap"
        assert parsed["metadata"]["name"] == "my-config"
        assert parsed["metadata"]["namespace"] == "default"

    def test_manifest_render_normalize_applied(self, tmp_path: Path) -> None:
        """render_manifest 결과도 _normalize 통과."""
        _write_template(tmp_path, "manifest/norm.tmpl", "kind: Pod\n\n\nspec: {}")
        renderer = _make_renderer(tmp_path)

        result = renderer.render_manifest("norm", {})

        # 연속 빈 라인이 1개로 줄어야 함
        assert "\n\n\n" not in result
        assert result.endswith("\n")
