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

from scripts._shared.types import (
    BuildPlan,
    ProbeConfig,
    StackDetectResult,
    UserInputs,
)
from scripts.stacks.python import (
    _DJANGO_RE,
    _FASTAPI_RE,
    _FLASK_RE,
    PythonStackModule,
    ServerCmdResult,
    _build_default_cmd,
    _detect_python_framework,
    _detect_python_version,
    _detect_server_command,
    _infer_entrypoint,
    _match_frameworks,
    _parse_pyproject_toml,
    _parse_requirements_txt,
    _read_python_file_safe,
    _resolve_uv_sync_cmd,
)


def _make_user_inputs(app_name: str = "myapp", port: int = 8000) -> UserInputs:
    return UserInputs(
        app_name=app_name,
        port=port,
        exposure="ClusterIP",
        namespace="default",
        output_dir=Path("/tmp/out"),
        resource_hint="medium",
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


# ══════════════════════════════════════════════════════════════════════════════
# Phase β — 빌드 layer
# ══════════════════════════════════════════════════════════════════════════════

# ──────────────────────────────────────────────────────────────────────────────
# _resolve_uv_sync_cmd (F-14) — lockfile 3분기
# ──────────────────────────────────────────────────────────────────────────────


def test_uv_sync_frozen_with_lock(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", '[project]\nname="d"\ndependencies=[]\n')
    _write(tmp_path / "uv.lock", "version = 1\n")
    cmd, status = _resolve_uv_sync_cmd(tmp_path)
    assert status == "frozen"
    assert "--frozen" in cmd


def test_uv_sync_non_frozen_pyproject_only(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", '[project]\nname="d"\ndependencies=[]\n')
    cmd, status = _resolve_uv_sync_cmd(tmp_path)
    assert status == "non-frozen-warning"
    assert "uv sync" in cmd
    assert "--frozen" not in cmd


def test_uv_sync_requirements_only(tmp_path: Path) -> None:
    _write(tmp_path / "requirements.txt", "fastapi>=0.100\n")
    cmd, status = _resolve_uv_sync_cmd(tmp_path)
    assert status == "requirements-txt"
    assert "uv pip install" in cmd
    assert "requirements.txt" in cmd


# ──────────────────────────────────────────────────────────────────────────────
# detect (F-09) — build metadata 기반
# ──────────────────────────────────────────────────────────────────────────────


def test_detect_pyproject_returns_result(tmp_path: Path) -> None:
    _make_pyproject(
        tmp_path,
        '[project]\nname="d"\nrequires-python=">=3.12"\ndependencies=["fastapi>=0.1"]\n',
    )
    result = PythonStackModule().detect(tmp_path)
    assert result is not None
    assert result.framework == "fastapi"
    assert result.version == "3.12"
    assert result.port is None  # F-22-1: port 자동화 없음


def test_detect_requirements_only(tmp_path: Path) -> None:
    _make_requirements(tmp_path, "django>=4.2\n")
    result = PythonStackModule().detect(tmp_path)
    assert result is not None
    assert result.framework == "django"


def test_detect_no_manifest_returns_none(tmp_path: Path) -> None:
    assert PythonStackModule().detect(tmp_path) is None


def test_detect_never_raises_on_garbage(tmp_path: Path) -> None:
    # NFR-3: 깨진 pyproject도 raise 없이 python-generic 폴백
    _write(tmp_path / "pyproject.toml", "not valid toml [[[\n")
    result = PythonStackModule().detect(tmp_path)
    assert result is not None
    assert result.framework == "python-generic"


# ──────────────────────────────────────────────────────────────────────────────
# build_plan (F-13~17)
# ──────────────────────────────────────────────────────────────────────────────


def test_build_plan_images(tmp_path: Path) -> None:
    _make_pyproject(
        tmp_path,
        '[project]\nname="d"\nrequires-python=">=3.12"\ndependencies=["fastapi>=0.1"]\n',
    )
    _write(tmp_path / "uv.lock", "version = 1\n")
    module = PythonStackModule()
    detect = module.detect(tmp_path)
    plan = module.build_plan(detect, inputs=_make_user_inputs())
    assert isinstance(plan, BuildPlan)
    assert plan.builder_image == "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"
    assert plan.runner_image == "python:3.12-slim"
    # build_cmd(uv_sync_cmd)는 project_dir 기반이라 dockerfile_context가 단일 출처
    # (Protocol build_plan에는 project_dir 부재) — 여기선 image/artifact만 검증
    assert plan.artifact_path == "/app/.venv"


# ──────────────────────────────────────────────────────────────────────────────
# probe_plan (F-18) — /health 통일 vs /healthz 폴백
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("framework", ["django", "flask", "fastapi"])
def test_probe_plan_health_for_frameworks(framework: str) -> None:
    detect = StackDetectResult(
        port=None, entrypoint="", framework=framework, version="3.11"
    )
    config = PythonStackModule().probe_plan(detect)
    assert isinstance(config, ProbeConfig)
    assert config.liveness.path == "/health"
    assert config.readiness.path == "/health"
    assert config.liveness.port == 8000


def test_probe_plan_healthz_for_generic() -> None:
    detect = StackDetectResult(
        port=None, entrypoint="", framework="python-generic", version="3.11"
    )
    config = PythonStackModule().probe_plan(detect)
    assert config.liveness.path == "/healthz"


def test_probe_plan_respects_detect_port() -> None:
    detect = StackDetectResult(
        port=9000, entrypoint="", framework="fastapi", version="3.11"
    )
    config = PythonStackModule().probe_plan(detect)
    assert config.liveness.port == 9000


# ──────────────────────────────────────────────────────────────────────────────
# defaults (F-16) — UID 10001 + writable_paths
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tier", ["small", "medium", "large"])
def test_defaults_tiers(tier: str) -> None:
    defaults = PythonStackModule().defaults(tier)
    assert defaults.run_as_user == 10001
    assert "/tmp" in defaults.writable_paths
    assert "/app/.cache" in defaults.writable_paths
    assert defaults.cpu_request.endswith("m")


# ──────────────────────────────────────────────────────────────────────────────
# artifact_locator (F) — 앱 소스 전체
# ──────────────────────────────────────────────────────────────────────────────


def test_artifact_locator_returns_project_dir(tmp_path: Path) -> None:
    detect = StackDetectResult(
        port=None, entrypoint="", framework="fastapi", version="3.11"
    )
    paths = PythonStackModule().artifact_locator(detect, tmp_path)
    assert paths == [tmp_path]


# ──────────────────────────────────────────────────────────────────────────────
# dockerfile_context (F-17) — 빌드 관련 키 (entrypoint는 γ에서 보강)
# ──────────────────────────────────────────────────────────────────────────────


def test_dockerfile_context_build_keys(tmp_path: Path) -> None:
    _make_pyproject(
        tmp_path,
        '[project]\nname="d"\nrequires-python=">=3.11"\ndependencies=["fastapi>=0.1"]\n',
    )
    _write(tmp_path / "uv.lock", "version = 1\n")
    module = PythonStackModule()
    detect = module.detect(tmp_path)
    inputs = _make_user_inputs(port=8000)
    plan = module.build_plan(detect, inputs=inputs)
    ctx = module.dockerfile_context(
        build_plan=plan, detect_result=detect, inputs=inputs, project_dir=tmp_path
    )
    assert ctx["python_version"] == "3.11"
    assert ctx["framework"] == "fastapi"
    assert ctx["lockfile_status"] == "frozen"
    assert ctx["has_pyproject"] is True
    assert ctx["has_uvlock"] is True
    assert ctx["has_requirements"] is False
    assert ctx["port"] == 8000
    assert ctx["app_user_uid"] == 10001
    assert "pyproject.toml" in ctx["manifest_sources"]


# ──────────────────────────────────────────────────────────────────────────────
# python.tmpl 렌더 (F-13~16) — Jinja2 직접 렌더 검증
# ──────────────────────────────────────────────────────────────────────────────


def _render_python_tmpl(ctx: dict) -> str:
    from jinja2 import Environment, FileSystemLoader

    templates_dir = Path(__file__).resolve().parents[2] / "templates" / "dockerfile"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("python.tmpl").render(**ctx)


def _base_ctx(**overrides: object) -> dict:
    ctx = {
        "python_version": "3.11",
        "framework": "fastapi",
        "manifest_sources": ["pyproject.toml", "uv.lock"],
        "uv_sync_cmd": "uv sync --frozen --no-dev",
        "lockfile_status": "frozen",
        "has_pyproject": True,
        "has_uvlock": True,
        "has_requirements": False,
        "entrypoint_cmd": ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
        "entrypoint_gap": None,
        "port": 8000,
        "app_user_uid": 10001,
        "app_user_gid": 10001,
    }
    ctx.update(overrides)
    return ctx


def test_python_tmpl_multistage_nonroot() -> None:
    out = _render_python_tmpl(_base_ctx())
    assert "AS builder" in out
    assert "ghcr.io/astral-sh/uv:python3.11-bookworm-slim" in out
    assert "python:3.11-slim" in out
    assert "USER 10001:10001" in out
    # 런타임에 uv 바이너리 미포함 (builder에서만 uv 사용)
    assert out.index("AS builder") < out.index("python:3.11-slim")


def test_python_tmpl_copy_branch_frozen() -> None:
    out = _render_python_tmpl(_base_ctx())
    assert "COPY pyproject.toml" in out
    assert "COPY uv.lock" in out
    assert "COPY requirements.txt" not in out


def test_python_tmpl_requirements_branch() -> None:
    ctx = _base_ctx(
        has_pyproject=False,
        has_uvlock=False,
        has_requirements=True,
        lockfile_status="requirements-txt",
        uv_sync_cmd="uv venv .venv && uv pip install --python /app/.venv -r requirements.txt",
    )
    out = _render_python_tmpl(ctx)
    assert "COPY requirements.txt" in out
    assert "COPY uv.lock" not in out


def test_python_tmpl_non_frozen_warning() -> None:
    ctx = _base_ctx(
        has_uvlock=False,
        lockfile_status="non-frozen-warning",
        uv_sync_cmd="uv sync --no-dev",
    )
    out = _render_python_tmpl(ctx)
    assert "WARNING" in out
    assert "uv.lock" in out


def test_python_tmpl_entrypoint_gap_no_cmd() -> None:
    ctx = _base_ctx(entrypoint_cmd=[], entrypoint_gap="generic Python — override required")
    out = _render_python_tmpl(ctx)
    # 실제 CMD 명령 라인은 없어야 함 (주석의 "CMD generation"은 허용)
    assert "\nCMD " not in out
    assert "entrypoint gap" in out


# ══════════════════════════════════════════════════════════════════════════════
# Phase γ — 실행 layer (CMD 3조건 + entrypoint 휴리스틱)
# ══════════════════════════════════════════════════════════════════════════════

# ──────────────────────────────────────────────────────────────────────────────
# _infer_entrypoint (SD-1)
# ──────────────────────────────────────────────────────────────────────────────


def _make_django(tmp_path: Path, wsgi_dirs: list[str]) -> Path:
    _write(tmp_path / "manage.py", "# manage\n")
    for d in wsgi_dirs:
        _write(tmp_path / d / "wsgi.py", "application = None\n")
    return tmp_path


def test_infer_entrypoint_django_single_wsgi(tmp_path: Path) -> None:
    _make_django(tmp_path, ["myproj"])
    assert _infer_entrypoint("django", tmp_path) == "myproj.wsgi:application"


def test_infer_entrypoint_django_multi_wsgi_sorted(tmp_path: Path) -> None:
    _make_django(tmp_path, ["zeta", "alpha"])
    # sorted 첫 번째 (alpha) 사용 — 결정성
    assert _infer_entrypoint("django", tmp_path) == "alpha.wsgi:application"


def test_infer_entrypoint_django_no_manage_py(tmp_path: Path) -> None:
    _write(tmp_path / "myproj" / "wsgi.py", "application = None\n")
    assert _infer_entrypoint("django", tmp_path) is None


def test_infer_entrypoint_django_src_layout_none(tmp_path: Path) -> None:
    # src/myproj/wsgi.py (2단계) — 1단계 탐색 미감지 → None
    _write(tmp_path / "manage.py", "# manage\n")
    _write(tmp_path / "src" / "myproj" / "wsgi.py", "application = None\n")
    assert _infer_entrypoint("django", tmp_path) is None


def test_infer_entrypoint_flask_main(tmp_path: Path) -> None:
    _write(tmp_path / "main.py", "app = object()\n")
    assert _infer_entrypoint("flask", tmp_path) == "main:app"


def test_infer_entrypoint_fastapi_app(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "app = object()\n")
    assert _infer_entrypoint("fastapi", tmp_path) == "app:app"


def test_infer_entrypoint_flask_main_priority(tmp_path: Path) -> None:
    # main.py 우선 (app.py보다)
    _write(tmp_path / "main.py", "app = object()\n")
    _write(tmp_path / "app.py", "app = object()\n")
    assert _infer_entrypoint("flask", tmp_path) == "main:app"


def test_infer_entrypoint_none_when_missing(tmp_path: Path) -> None:
    assert _infer_entrypoint("fastapi", tmp_path) is None


def test_infer_entrypoint_generic_none(tmp_path: Path) -> None:
    _write(tmp_path / "main.py", "app = object()\n")
    assert _infer_entrypoint("python-generic", tmp_path) is None


# ──────────────────────────────────────────────────────────────────────────────
# _detect_server_command (F-20-1 6 케이스 매트릭스)
# ──────────────────────────────────────────────────────────────────────────────


def test_server_cmd_c1_fastapi(tmp_path: Path) -> None:
    # C1: framework + server pkg + entrypoint 모두 충족 → uvicorn CMD
    _write(tmp_path / "main.py", "app = object()\n")
    result = _detect_server_command("fastapi", tmp_path, frozenset({"fastapi", "uvicorn"}))
    assert isinstance(result, ServerCmdResult)
    assert result.gap_reason is None
    assert result.cmd == ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


def test_server_cmd_c1_django(tmp_path: Path) -> None:
    _make_django(tmp_path, ["myproj"])
    result = _detect_server_command("django", tmp_path, frozenset({"django", "gunicorn"}))
    assert result.cmd == ["gunicorn", "myproj.wsgi:application", "--bind", "0.0.0.0:8000"]


def test_server_cmd_c2_pkg_ok_entry_missing(tmp_path: Path) -> None:
    # C2: pkg 있음, entrypoint 추론 실패
    result = _detect_server_command("fastapi", tmp_path, frozenset({"fastapi", "uvicorn"}))
    assert result.cmd is None
    assert "entrypoint" in result.gap_reason.lower()


def test_server_cmd_c3_pkg_missing_entry_ok(tmp_path: Path) -> None:
    # C3: entrypoint 있음, server pkg 부재 → 자동 install 금지
    _write(tmp_path / "main.py", "app = object()\n")
    result = _detect_server_command("fastapi", tmp_path, frozenset({"fastapi"}))
    assert result.cmd is None
    assert "uvicorn" in result.gap_reason


def test_server_cmd_c4_both_missing(tmp_path: Path) -> None:
    result = _detect_server_command("flask", tmp_path, frozenset({"flask"}))
    assert result.cmd is None
    assert "gunicorn" in result.gap_reason


def test_server_cmd_c5_ambiguous(tmp_path: Path) -> None:
    result = _detect_server_command(
        "python-generic", tmp_path, frozenset({"django", "flask"})
    )
    assert result.cmd is None
    assert "ambiguous" in result.gap_reason.lower()


def test_server_cmd_c6_no_framework(tmp_path: Path) -> None:
    result = _detect_server_command("python-generic", tmp_path, frozenset({"requests"}))
    assert result.cmd is None
    assert "no supported framework" in result.gap_reason.lower()


# ──────────────────────────────────────────────────────────────────────────────
# detect entrypoint 통합 + dockerfile_context entrypoint 연결
# ──────────────────────────────────────────────────────────────────────────────


def test_detect_integrates_entrypoint(tmp_path: Path) -> None:
    _make_pyproject(tmp_path, '[project]\nname="d"\ndependencies=["fastapi>=0.1"]\n')
    _write(tmp_path / "main.py", "app = object()\n")
    result = PythonStackModule().detect(tmp_path)
    assert result.entrypoint == "main:app"


def test_dockerfile_context_entrypoint_cmd_c1(tmp_path: Path) -> None:
    _make_pyproject(
        tmp_path,
        '[project]\nname="d"\ndependencies=["fastapi>=0.1", "uvicorn>=0.20"]\n',
    )
    _write(tmp_path / "main.py", "app = object()\n")
    _write(tmp_path / "uv.lock", "version = 1\n")
    module = PythonStackModule()
    detect = module.detect(tmp_path)
    inputs = _make_user_inputs()
    plan = module.build_plan(detect, inputs=inputs)
    ctx = module.dockerfile_context(
        build_plan=plan, detect_result=detect, inputs=inputs, project_dir=tmp_path
    )
    assert ctx["entrypoint_cmd"] == [
        "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"
    ]
    assert ctx["entrypoint_gap"] is None


def test_dockerfile_context_entrypoint_gap_generic(tmp_path: Path) -> None:
    _make_pyproject(tmp_path, '[project]\nname="d"\ndependencies=["requests"]\n')
    module = PythonStackModule()
    detect = module.detect(tmp_path)
    inputs = _make_user_inputs()
    plan = module.build_plan(detect, inputs=inputs)
    ctx = module.dockerfile_context(
        build_plan=plan, detect_result=detect, inputs=inputs, project_dir=tmp_path
    )
    assert ctx["entrypoint_cmd"] == []
    assert ctx["entrypoint_gap"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# Phase δ — text_safety 회귀 가드 (F-28/29, BL-019 위임 — text_safety 변경 0)
# ══════════════════════════════════════════════════════════════════════════════


def test_python_probe_path_passes_validation() -> None:
    from scripts._shared.text_safety import validate_probe_path

    # django/flask/fastapi probe path가 기존 정책 통과
    validate_probe_path("/health")
    validate_probe_path("/healthz")


def test_python_cmd_args_are_shell_meta_free() -> None:
    from scripts._shared.text_safety import reject_unsafe_chars

    # C1 생성 CMD args(exec form)에 개행/제어문자 없음 — shell 미경유 + 위생 확인
    detect = StackDetectResult(
        port=None, entrypoint="main:app", framework="fastapi", version="3.11"
    )
    cmd = _build_default_cmd("fastapi", "main:app")
    for arg in cmd:
        reject_unsafe_chars(arg, "python.cmd")
    assert detect.framework == "fastapi"


def test_probe_path_still_rejects_shell_meta() -> None:
    # 회귀: 기존 shell-meta 차단 정책 유지 (stack 무관)
    from scripts._shared.text_safety import validate_probe_path

    with pytest.raises(ValueError):
        validate_probe_path("/health\nmalicious")
