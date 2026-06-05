"""PythonStackModule 단위 테스트 (TDD, BL-006).

Phase α (감지 layer):
- _DJANGO_RE / _FLASK_RE / _FASTAPI_RE (F-07): PEP 503 normalize + extras + boundary
- _read_python_file_safe (F-04/08/10): symlink escape 방어 + IO 오류 흡수
- _parse_pyproject_toml (F-06): PEP 621 + optional-deps + Poetry union
- _parse_requirements_txt (F-06-1): root requirements.txt only, -r/-c/sub-dir skip
- _detect_python_framework (F-05/06/08/09/10): "Direct dependency wins" 4단계, tuple 반환
- _detect_python_version (F-11/12): requires-python 하한 + 화이트리스트 + Python 2 guard
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.stacks.python import (
    _DJANGO_RE,
    _FASTAPI_RE,
    _FLASK_RE,
    _detect_python_framework,
    _detect_python_version,
    _match_frameworks,
    _parse_pyproject_toml,
    _parse_requirements_txt,
    _read_python_file_safe,
)

# ──────────────────────────────────────────────────────────────────────────────
# 헬퍼: 픽스처 생성
# ──────────────────────────────────────────────────────────────────────────────


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_pyproject(tmp_path: Path, body: str) -> Path:
    _write(tmp_path / "pyproject.toml", body)
    return tmp_path


def _make_requirements(tmp_path: Path, body: str) -> Path:
    _write(tmp_path / "requirements.txt", body)
    return tmp_path


# ──────────────────────────────────────────────────────────────────────────────
# 정규식 (F-07) — PEP 503 normalize + extras + version boundary
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "line",
    [
        "django",
        "Django",
        "DJANGO",
        "django>=4.2",
        "Django==4.2.1",
        "django[argon2]>=4.0",
        "  django  ",
    ],
)
def test_django_re_positive(line: str) -> None:
    assert _DJANGO_RE.search(line) is not None


@pytest.mark.parametrize(
    "line",
    [
        "django-extensions",
        "djangorestframework",
        "django_filter",  # underscore 변형 sub-package
        "mydjango",
    ],
)
def test_django_re_negative(line: str) -> None:
    assert _DJANGO_RE.search(line) is None


@pytest.mark.parametrize(
    "line",
    ["flask", "Flask", "flask[async]", "Flask>=2.0", "flask==3.0.0"],
)
def test_flask_re_positive(line: str) -> None:
    assert _FLASK_RE.search(line) is not None


@pytest.mark.parametrize(
    "line",
    ["flask-restful", "flask_sqlalchemy", "flask-cors", "myflask"],
)
def test_flask_re_negative(line: str) -> None:
    assert _FLASK_RE.search(line) is None


@pytest.mark.parametrize(
    "line",
    ["fastapi", "FastAPI", "fastapi[standard]", "fastapi>=0.100", "fastapi==0.110.0"],
)
def test_fastapi_re_positive(line: str) -> None:
    assert _FASTAPI_RE.search(line) is not None


@pytest.mark.parametrize(
    "line",
    ["fastapi-utils", "fastapi_users", "myfastapi"],
)
def test_fastapi_re_negative(line: str) -> None:
    assert _FASTAPI_RE.search(line) is None


# ──────────────────────────────────────────────────────────────────────────────
# _match_frameworks
# ──────────────────────────────────────────────────────────────────────────────


def test_match_frameworks_single() -> None:
    assert _match_frameworks("django>=4.2\nrequests") == ["django"]


def test_match_frameworks_multi_sorted() -> None:
    # 알파벳 안정 순 (django, fastapi, flask)
    assert _match_frameworks("flask\nfastapi\ndjango") == ["django", "fastapi", "flask"]


def test_match_frameworks_none() -> None:
    assert _match_frameworks("requests\nnumpy") == []


# ──────────────────────────────────────────────────────────────────────────────
# _read_python_file_safe (F-04/08/10)
# ──────────────────────────────────────────────────────────────────────────────


def test_read_safe_missing_returns_empty(tmp_path: Path) -> None:
    assert _read_python_file_safe(tmp_path, "pyproject.toml") == ""


def test_read_safe_reads_content(tmp_path: Path) -> None:
    _write(tmp_path / "requirements.txt", "django>=4.2\n")
    assert "django" in _read_python_file_safe(tmp_path, "requirements.txt")


@pytest.mark.skipif(
    os.name == "nt", reason="symlink 권한이 POSIX와 다름"
)
def test_read_safe_symlink_escape_blocked(tmp_path: Path) -> None:
    # tmp_path 밖의 비밀 파일을 symlink로 노출 → is_within 가드가 차단
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("SECRET")
    project = tmp_path / "proj"
    project.mkdir()
    link = project / "pyproject.toml"
    link.symlink_to(outside)
    assert _read_python_file_safe(project, "pyproject.toml") == ""


# ──────────────────────────────────────────────────────────────────────────────
# _parse_pyproject_toml (F-06) — PEP 621 + optional + Poetry union
# ──────────────────────────────────────────────────────────────────────────────


def test_parse_pyproject_pep621() -> None:
    body = """
[project]
name = "demo"
dependencies = ["django>=4.2", "requests"]
"""
    deps = _parse_pyproject_toml(body)
    assert any("django" in d for d in deps)


def test_parse_pyproject_optional_deps() -> None:
    body = """
[project]
name = "demo"
dependencies = ["requests"]
[project.optional-dependencies]
web = ["fastapi[standard]>=0.100"]
"""
    deps = _parse_pyproject_toml(body)
    assert any("fastapi" in d for d in deps)


def test_parse_pyproject_poetry() -> None:
    body = """
[tool.poetry.dependencies]
python = "^3.11"
flask = "^3.0"
"""
    deps = _parse_pyproject_toml(body)
    # poetry key 이름이 추출되며 python 키는 framework 매칭에 무관
    assert "flask" in deps
    assert "python" not in _match_frameworks("\n".join(deps))


def test_parse_pyproject_malformed_returns_empty() -> None:
    # TOML 파싱 실패 → 빈 set (NFR-3 안전 폴백)
    assert _parse_pyproject_toml("this is = = not valid toml [[[") == set()


# ──────────────────────────────────────────────────────────────────────────────
# _parse_requirements_txt (F-06-1) — root only, -r/-c skip
# ──────────────────────────────────────────────────────────────────────────────


def test_parse_requirements_basic() -> None:
    body = "django>=4.2\nrequests==2.31\n# comment\n\n"
    deps = _parse_requirements_txt(body)
    assert any("django" in d for d in deps)


def test_parse_requirements_skips_r_and_c_refs() -> None:
    body = "-r dev-requirements.txt\n-c constraints.txt\nflask>=2.0\n"
    deps = _parse_requirements_txt(body)
    # -r / -c 참조 라인은 무시, flask만 남음
    assert any("flask" in d for d in deps)
    assert not any("dev-requirements" in d for d in deps)
    assert not any("constraints" in d for d in deps)


# ──────────────────────────────────────────────────────────────────────────────
# _detect_python_framework (F-05/06/09/10) — tuple 반환 4단계
# ──────────────────────────────────────────────────────────────────────────────


def test_detect_framework_single_pyproject(tmp_path: Path) -> None:
    _make_pyproject(
        tmp_path,
        '[project]\nname="d"\ndependencies = ["django>=4.2"]\n',
    )
    framework, direct_deps, sources = _detect_python_framework(tmp_path)
    assert framework == "django"
    assert "pyproject.toml" in sources
    assert any("django" in d for d in direct_deps)


def test_detect_framework_multi_match_generic(tmp_path: Path) -> None:
    _make_pyproject(
        tmp_path,
        '[project]\nname="d"\ndependencies = ["django>=4.2", "flask>=2.0"]\n',
    )
    framework, _deps, _sources = _detect_python_framework(tmp_path)
    assert framework == "python-generic"


def test_detect_framework_no_match_generic(tmp_path: Path) -> None:
    _make_requirements(tmp_path, "requests==2.31\nnumpy\n")
    framework, _deps, sources = _detect_python_framework(tmp_path)
    assert framework == "python-generic"
    assert "requirements.txt" in sources


def test_detect_framework_union_pyproject_and_requirements(tmp_path: Path) -> None:
    # pyproject엔 framework 없고 requirements.txt에 fastapi → union으로 감지
    _make_pyproject(tmp_path, '[project]\nname="d"\ndependencies = ["requests"]\n')
    _make_requirements(tmp_path, "fastapi>=0.100\n")
    framework, _deps, sources = _detect_python_framework(tmp_path)
    assert framework == "fastapi"
    assert set(sources) == {"pyproject.toml", "requirements.txt"}


def test_detect_framework_no_manifest(tmp_path: Path) -> None:
    framework, direct_deps, sources = _detect_python_framework(tmp_path)
    assert framework == "python-generic"
    assert sources == []
    assert direct_deps == frozenset()


# ──────────────────────────────────────────────────────────────────────────────
# _detect_python_version (F-11/12) — 하한 + 화이트리스트 + Python 2 guard
# ──────────────────────────────────────────────────────────────────────────────


def test_version_from_requires_python_lower_bound(tmp_path: Path) -> None:
    _make_pyproject(
        tmp_path,
        '[project]\nname="d"\nrequires-python = ">=3.12,<4"\ndependencies=[]\n',
    )
    assert _detect_python_version(tmp_path) == "3.12"


def test_version_default_when_absent(tmp_path: Path) -> None:
    _make_pyproject(tmp_path, '[project]\nname="d"\ndependencies=[]\n')
    assert _detect_python_version(tmp_path) == "3.11"


def test_version_whitelist_fallback_for_newer(tmp_path: Path) -> None:
    # 3.13은 화이트리스트 밖 → 3.11 fallback
    _make_pyproject(
        tmp_path,
        '[project]\nname="d"\nrequires-python = ">=3.13"\ndependencies=[]\n',
    )
    assert _detect_python_version(tmp_path) == "3.11"


def test_version_python2_guard(tmp_path: Path) -> None:
    # Python 2.x는 화이트리스트 밖 → 3.11 fallback (explicit guard)
    _make_pyproject(
        tmp_path,
        '[project]\nname="d"\nrequires-python = "==2.7"\ndependencies=[]\n',
    )
    assert _detect_python_version(tmp_path) == "3.11"


def test_version_poetry_python_constraint(tmp_path: Path) -> None:
    _make_pyproject(
        tmp_path,
        '[tool.poetry.dependencies]\npython = "^3.10"\n',
    )
    assert _detect_python_version(tmp_path) == "3.10"
