"""PythonStackModule — Python 스택 감지 및 계획 생성 (BL-006).

판별 시그널:
  - 루트의 `pyproject.toml` 또는 `requirements.txt` 존재 여부

Framework 감지 (build metadata only, "Direct dependency wins" — BL-017 미러링):
  - direct dependency union: PEP 621 + optional-deps + Poetry + root requirements.txt
  - django / flask / fastapi 정규식 단일 매치 → 채택, 복수/0개 → python-generic
  - `*.py` import 라인 스캔 안 함

책임 3-Layer:
  감지 (build metadata) → 설치 (lockfile 정책) → 실행 (dependency-conservative)

보안:
  - 모든 매니페스트 접근은 read_text_limited + is_within (symlink escape 방어, F-10)
  - 파일 I/O 실패는 감지 hint이므로 raise 금지, python-generic 안전 폴백 (NFR-3)
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import ClassVar

from scripts._shared.fileio import is_within, read_text_limited
from scripts._shared.types import (
    BuildPlan,
    ProbeConfig,
    ProbeSpec,
    ResourceDefaults,
    StackDetectResult,
    UserInputs,
)
from scripts.stacks.base import ResourceHint

# ──────────────────────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_PYTHON_VERSION = "3.11"  # F-11/12: requires-python 부재/parse 실패 fallback

_DEFAULT_PROBE_PORT = 8000  # F-18/21: probe 기본 포트 (default CMD와 단일 출처)
_APP_USER_UID = 10001  # F-16: 비-root 보안 디폴트
_APP_USER_GID = 10001

# F-18: /health 경로를 채택하는 framework 집합 (version-agnostic).
_HEALTH_FRAMEWORKS: frozenset[str] = frozenset({"django", "flask", "fastapi"})

_BUILDER_IMAGE_TEMPLATE = "ghcr.io/astral-sh/uv:python{version}-bookworm-slim"
_RUNNER_IMAGE_TEMPLATE = "python:{version}-slim"
_VENV_PATH = "/app/.venv"

# F-16: Python 리소스 tier (JVM/Go 패턴 일관).
_RESOURCE_TIERS: dict[str, dict[str, str]] = {
    "small": {
        "cpu_request": "100m",
        "memory_request": "128Mi",
        "cpu_limit": "250m",
        "memory_limit": "256Mi",
    },
    "medium": {
        "cpu_request": "250m",
        "memory_request": "256Mi",
        "cpu_limit": "500m",
        "memory_limit": "512Mi",
    },
    "large": {
        "cpu_request": "500m",
        "memory_request": "512Mi",
        "cpu_limit": "1000m",
        "memory_limit": "1024Mi",
    },
}

# F-11/12 + P1-7: 지원 Python 버전 화이트리스트. 밖이면 default로 보정.
# 신버전 추가는 후속 backlog.
_SUPPORTED_PYTHON_VERSIONS: frozenset[str] = frozenset(
    {"3.9", "3.10", "3.11", "3.12"}
)

# F-07: Python 웹 framework 식별 정규식 (모듈 상수, BL-017 패턴 미러링).
#
# 각 정규식은 PEP 508 requirement 라인(또는 Poetry dependency key)에 대해:
#   - `(?im)` = case-insensitive(PEP 503 normalize) + multiline(^/$)
#   - 라인 선두 공백 허용 후 패키지명
#   - extras `[...]` 선택 허용 (예: fastapi[standard])
#   - 패키지명 직후 version operator(`<>=!~`) 또는 라인 끝(`$`)만 허용
#
# 마지막 boundary 조건이 sub-package false-match를 차단한다:
#   `flask-restful` / `django-extensions` / `fastapi-utils`는 framework 본체 직후
#   `-`(operator/EOL 아님)가 와서 매칭에서 제외된다. version-agnostic (버전 capture 안 함).
# ReDoS-free: 고정 어절 + 정량 wildcard 없음.
_DJANGO_RE = re.compile(r"(?im)^\s*django(?:\[[^\]]+\])?\s*(?:[<>=!~]|$)")
_FLASK_RE = re.compile(r"(?im)^\s*flask(?:\[[^\]]+\])?\s*(?:[<>=!~]|$)")
_FASTAPI_RE = re.compile(r"(?im)^\s*fastapi(?:\[[^\]]+\])?\s*(?:[<>=!~]|$)")

# F-11: requires-python / Poetry python 제약에서 첫 major.minor 추출.
_PY_VERSION_RE = re.compile(r"(\d+)\.(\d+)")


# ──────────────────────────────────────────────────────────────────────────────
# 안전 IO (F-04/08/10)
# ──────────────────────────────────────────────────────────────────────────────


def _read_python_file_safe(project_dir: Path, filename: str) -> str:
    """프로젝트 루트의 매니페스트를 안전하게 읽어 텍스트 반환 (BL-017 미러링).

    실패 케이스(없음/권한/디코딩/symlink escape) 모두 빈 문자열로 흡수 — 감지는
    hint(NFR-3)이므로 raise 금지.

    **흡수하지 않는 예외** (시스템 레벨):
      - ``MemoryError``: read_text_limited 5MB 통과 후에도 시스템 메모리 부족 시
        발생 가능. 정상 종료 신호이므로 흡수하지 않음.
      - ``KeyboardInterrupt`` / ``SystemExit``: 명시적 종료 의도.
    """
    target = project_dir / filename
    if not target.is_file():
        return ""
    if not is_within(project_dir, target):
        return ""
    try:
        return read_text_limited(target)
    except (OSError, UnicodeDecodeError, ValueError):
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# 매니페스트 파서 (F-06 / F-06-1)
# ──────────────────────────────────────────────────────────────────────────────


def _parse_pyproject_toml(content: str) -> set[str]:
    """pyproject.toml에서 direct dependency 집합 추출 (F-06).

    union 대상:
      - ``[project.dependencies]`` (PEP 621, PEP 508 문자열 리스트)
      - ``[project.optional-dependencies.*]`` (extras 그룹별 리스트)
      - ``[tool.poetry.dependencies]`` (Poetry, key=패키지명)

    Poetry의 ``python`` 키는 dependency가 아닌 인터프리터 제약이지만, framework
    정규식과 매칭되지 않으므로 별도 필터 없이 포함해도 무해하다.

    파싱 실패(TOMLDecodeError 등) → 빈 set (NFR-3 안전 폴백).
    """
    if not content:
        return set()
    try:
        data = tomllib.loads(content)
    except (tomllib.TOMLDecodeError, ValueError, TypeError):
        return set()

    deps: set[str] = set()

    project = data.get("project")
    if isinstance(project, dict):
        for item in project.get("dependencies", []) or []:
            if isinstance(item, str):
                deps.add(item)
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                for item in group or []:
                    if isinstance(item, str):
                        deps.add(item)

    poetry = (
        data.get("tool", {}).get("poetry", {})
        if isinstance(data.get("tool"), dict)
        else {}
    )
    poetry_deps = poetry.get("dependencies") if isinstance(poetry, dict) else None
    if isinstance(poetry_deps, dict):
        for name in poetry_deps:
            if isinstance(name, str):
                deps.add(name)

    return deps


def _parse_requirements_txt(content: str) -> set[str]:
    """root requirements.txt에서 direct dependency 라인 집합 추출 (F-06-1).

    스코프 제한 (사용자 보정 guardrail #1):
      - **root requirements.txt만** 인식.
      - ``-r other.txt`` / ``-c constraints.txt`` 참조 라인은 skip (1-depth 포함 X).
      - 주석(``#``) / 빈 줄 skip.

    각 라인은 원문 그대로 보존하여 framework 정규식이 직접 매칭한다.
    """
    deps: set[str] = set()
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # -r/-c (및 --requirement/--constraint) 참조 라인은 범위 밖
        if line.startswith("-r") or line.startswith("-c") or line.startswith("--"):
            continue
        deps.add(line)
    return deps


# ──────────────────────────────────────────────────────────────────────────────
# Framework 감지 (F-05 ~ F-10)
# ──────────────────────────────────────────────────────────────────────────────


def _match_frameworks(text: str) -> list[str]:
    """텍스트에서 매칭되는 framework 이름 목록 반환 (BL-017 헬퍼).

    알파벳 안정 순(django, fastapi, flask)으로 반환하여 테스트 결정성 보장.
    """
    matches: list[str] = []
    if _DJANGO_RE.search(text):
        matches.append("django")
    if _FASTAPI_RE.search(text):
        matches.append("fastapi")
    if _FLASK_RE.search(text):
        matches.append("flask")
    return matches


def _detect_python_framework(
    project_dir: Path,
) -> tuple[str, frozenset[str], list[str]]:
    """Python 웹 framework 식별 — "Direct dependency wins" (F-05/06/09/10).

    알고리즘:
      1. pyproject.toml / requirements.txt를 안전 읽기하여 direct dependency union.
      2. union에 django/flask/fastapi 정확히 1개 매치 → 해당 framework 채택.
      3. 복수 매치 → ``"python-generic"`` (억지 선택 금지).
      4. 0개 매치 → ``"python-generic"``.

    Returns:
        ``(framework, direct_deps, manifest_sources)`` — 호출자가 direct_deps /
        manifest_sources를 재사용 (P2-1, dataclass 확장 없이 tuple로 노출).
        framework는 ``"django"``/``"flask"``/``"fastapi"``/``"python-generic"``.
    """
    direct: set[str] = set()
    manifest_sources: list[str] = []

    pyproject_text = _read_python_file_safe(project_dir, "pyproject.toml")
    if pyproject_text:
        direct |= _parse_pyproject_toml(pyproject_text)
        manifest_sources.append("pyproject.toml")

    requirements_text = _read_python_file_safe(project_dir, "requirements.txt")
    if requirements_text:
        direct |= _parse_requirements_txt(requirements_text)
        manifest_sources.append("requirements.txt")

    # set 멤버십 대신 word-boundary 정규식 재사용을 위해 줄단위 텍스트로 합성.
    # sorted로 결정성 보장.
    blob = "\n".join(sorted(direct))
    matches = _match_frameworks(blob)
    framework = matches[0] if len(matches) == 1 else "python-generic"
    return framework, frozenset(direct), manifest_sources


# ──────────────────────────────────────────────────────────────────────────────
# Python 버전 결정 (F-11/12)
# ──────────────────────────────────────────────────────────────────────────────


def _detect_python_version(project_dir: Path) -> str:
    """pyproject.toml의 requires-python / Poetry python 제약에서 major.minor 하한 추출.

    - PEP 621 ``[project.requires-python]`` 우선, 부재 시 Poetry
      ``[tool.poetry.dependencies.python]``.
    - 첫 ``major.minor`` 토큰을 하한으로 사용 (예: ``">=3.12,<4"`` → ``"3.12"``).
    - 부재 / parse 실패 → ``"3.11"`` default.
    - 화이트리스트 ``{3.9, 3.10, 3.11, 3.12}`` 밖(신버전 또는 Python 2.x) →
      ``"3.11"`` fallback (F-12 explicit guard 포함).
    """
    content = _read_python_file_safe(project_dir, "pyproject.toml")
    if not content:
        return _DEFAULT_PYTHON_VERSION
    try:
        data = tomllib.loads(content)
    except (tomllib.TOMLDecodeError, ValueError, TypeError):
        return _DEFAULT_PYTHON_VERSION

    constraint = ""
    project = data.get("project")
    if isinstance(project, dict):
        rp = project.get("requires-python")
        if isinstance(rp, str):
            constraint = rp
    if not constraint:
        tool = data.get("tool")
        poetry_deps = (
            tool.get("poetry", {}).get("dependencies", {})
            if isinstance(tool, dict)
            else {}
        )
        if isinstance(poetry_deps, dict):
            py = poetry_deps.get("python")
            if isinstance(py, str):
                constraint = py

    match = _PY_VERSION_RE.search(constraint)
    if not match:
        return _DEFAULT_PYTHON_VERSION
    version = f"{match.group(1)}.{match.group(2)}"
    if version not in _SUPPORTED_PYTHON_VERSIONS:
        return _DEFAULT_PYTHON_VERSION
    return version


# ──────────────────────────────────────────────────────────────────────────────
# Dockerfile uv 명령 분기 (F-14)
# ──────────────────────────────────────────────────────────────────────────────


def _resolve_uv_sync_cmd(project_dir: Path) -> tuple[str, str]:
    """builder stage의 uv 명령 + lockfile_status 결정 (F-14).

    우선순위 (재현성 높은 순):
      - ``uv.lock`` 존재 → ``uv sync --frozen --no-dev`` / ``"frozen"``
      - ``pyproject.toml``만 (lock 부재) → ``uv sync --no-dev`` / ``"non-frozen-warning"``
      - ``requirements.txt``만 (pyproject 부재) →
        ``uv venv .venv && uv pip install --python /app/.venv -r requirements.txt`` /
        ``"requirements-txt"``
      - 아무 매니페스트도 없음 → ``("", "none")`` (detect가 None 반환하므로 정상 경로엔 미도달)
    """
    has_uvlock = (project_dir / "uv.lock").is_file()
    has_pyproject = (project_dir / "pyproject.toml").is_file()
    has_requirements = (project_dir / "requirements.txt").is_file()

    if has_uvlock:
        return "uv sync --frozen --no-dev", "frozen"
    if has_pyproject:
        return "uv sync --no-dev", "non-frozen-warning"
    if has_requirements:
        return (
            "uv venv .venv && uv pip install --python /app/.venv -r requirements.txt",
            "requirements-txt",
        )
    return "", "none"


# ──────────────────────────────────────────────────────────────────────────────
# PythonStackModule (StackModule Protocol 구현)
# ──────────────────────────────────────────────────────────────────────────────


class PythonStackModule:
    """Python 스택 모듈 (StackModule Protocol 구현체, BL-006)."""

    name: ClassVar[str] = "python"
    template_name: ClassVar[str] = "python"

    # ── Public: StackModule Protocol ──────────────────────────────────────────

    def detect(self, project_dir: Path) -> StackDetectResult | None:
        """pyproject.toml / requirements.txt 기반 Python 프로젝트 감지 (F-09).

        Returns:
            StackDetectResult — Python 프로젝트인 경우.
            None — 매니페스트(pyproject.toml / requirements.txt) 부재.

        Raises:
            없음 — 모든 감지 오류는 안전 폴백 (NFR-3). 매니페스트 미존재만 None.
        """
        has_pyproject = (project_dir / "pyproject.toml").is_file()
        has_requirements = (project_dir / "requirements.txt").is_file()
        if not has_pyproject and not has_requirements:
            return None

        framework, _direct_deps, _sources = _detect_python_framework(project_dir)
        version = _detect_python_version(project_dir)

        # entrypoint는 Phase γ에서 _infer_entrypoint로 통합 (현재 sentinel "").
        return StackDetectResult(
            port=None,  # F-22-1: port 자동화 없음
            entrypoint="",
            framework=framework,
            version=version,
            build_system=None,
            actuator_enabled=False,
            cmd_candidates=[],
        )

    def build_plan(
        self,
        detect_result: StackDetectResult,
        *,
        inputs: UserInputs | None = None,
    ) -> BuildPlan:
        """uv-based multi-stage Dockerfile 계획 — builder/runner 이미지 결정 (F-17).

        build_cmd(uv_sync_cmd)는 project_dir 기반 lockfile 분기가 필요하나 Protocol
        build_plan에는 project_dir이 없으므로, 실제 명령은 ``dockerfile_context``가
        단일 출처로 결정한다. 여기서는 image/artifact만 확정한다.
        """
        version = detect_result.version or _DEFAULT_PYTHON_VERSION
        return BuildPlan(
            builder_image=_BUILDER_IMAGE_TEMPLATE.format(version=version),
            runner_image=_RUNNER_IMAGE_TEMPLATE.format(version=version),
            build_cmd="",  # dockerfile_context.uv_sync_cmd가 단일 출처 (F-14)
            artifact_path=_VENV_PATH,
        )

    def probe_plan(self, detect_result: StackDetectResult) -> ProbeConfig:
        """liveness / readiness ProbeConfig (F-18).

        - django/flask/fastapi → ``/health`` (version-agnostic 통일)
        - python-generic 및 기타 → ``/healthz`` (BL-001 baseline 폴백)
        - ``.devflow-k8s-deploy.yml::stack.python.probe.path`` override는
          ProjectAnalyzer가 우선 적용 (BL-019 위임).
        """
        port = detect_result.port or _DEFAULT_PROBE_PORT
        path = (
            "/health"
            if detect_result.framework in _HEALTH_FRAMEWORKS
            else "/healthz"
        )
        spec = ProbeSpec(kind="http", path=path, port=port)
        return ProbeConfig(liveness=spec, readiness=spec)

    def defaults(self, resource_hint: ResourceHint) -> ResourceDefaults:
        """Python tier별 리소스 기본값 (F-16).

        run_as_user=10001: 비-root 보안 디폴트.
        writable_paths=["/tmp", "/app/.cache"]: uv/pip 캐시 + 임시.
        """
        tier = _RESOURCE_TIERS[resource_hint]
        return ResourceDefaults(
            cpu_request=tier["cpu_request"],
            memory_request=tier["memory_request"],
            cpu_limit=tier["cpu_limit"],
            memory_limit=tier["memory_limit"],
            writable_paths=["/tmp", "/app/.cache"],
            run_as_user=_APP_USER_UID,
        )

    def artifact_locator(
        self, detect_result: StackDetectResult, project_dir: Path
    ) -> list[Path]:
        """Dockerfile COPY 소스 후보 — Python은 앱 소스 전체 (COPY . . 패턴).

        ``/app/.venv``는 builder stage에서 생성되므로 host 후보가 아니다.
        """
        return [project_dir]

    def dockerfile_context(
        self,
        *,
        build_plan: BuildPlan,
        detect_result: StackDetectResult,
        inputs: UserInputs,
        project_dir: Path | None,
    ) -> dict[str, object]:
        """python.tmpl Jinja2 컨텍스트 매핑 (6절 스키마, 13 keys).

        - framework / manifest_sources는 _detect_python_framework 재호출로 취득 (stateless)
        - uv_sync_cmd / lockfile_status는 _resolve_uv_sync_cmd가 project_dir 기반 결정
        - entrypoint_cmd / entrypoint_gap는 Phase γ에서 _detect_server_command로 연결
          (현재 placeholder — generic 폴백)
        """
        if project_dir is None:
            framework = detect_result.framework
            manifest_sources: list[str] = []
            uv_sync_cmd, lockfile_status = "uv sync --no-dev", "non-frozen-warning"
            has_pyproject = has_uvlock = has_requirements = False
        else:
            framework, _direct, manifest_sources = _detect_python_framework(
                project_dir
            )
            uv_sync_cmd, lockfile_status = _resolve_uv_sync_cmd(project_dir)
            has_pyproject = (project_dir / "pyproject.toml").is_file()
            has_uvlock = (project_dir / "uv.lock").is_file()
            has_requirements = (project_dir / "requirements.txt").is_file()

        version = detect_result.version or _DEFAULT_PYTHON_VERSION
        return {
            "python_version": version,
            "framework": framework,
            "manifest_sources": manifest_sources,
            "uv_sync_cmd": uv_sync_cmd,
            "lockfile_status": lockfile_status,
            "has_pyproject": has_pyproject,
            "has_uvlock": has_uvlock,
            "has_requirements": has_requirements,
            "entrypoint_cmd": [],  # Phase γ에서 _detect_server_command 연결
            "entrypoint_gap": None,
            "port": inputs.port,
            "app_user_uid": _APP_USER_UID,
            "app_user_gid": _APP_USER_GID,
        }
