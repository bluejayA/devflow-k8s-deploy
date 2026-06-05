# Application Design

**Mode**: LIST + DETAIL (R1 수정 반영)
**Depth**: Standard
**Timestamp**: 2026-05-13T23:55:00Z (R1 spec-reviewer 수정)
**Ticket**: BL-006 ([#9](https://github.com/bluejayA/devflow-k8s-deploy/issues/9))
**Predecessor**: BL-017 (Go framework 감지) — LIST 5개 컴포넌트를 본 작업에서 미러링·확장
**Primary Unit**: `scripts/stacks/python.py` (신규 단일 파일) + 외부 통합 (config/DI/analyzer + config schema + manifest renderer + SKILL.md)

**R1 spec-reviewer 수정 이력** (2026-05-13):
- **P0-1** `PythonStackModule` 5메서드 → **7메서드 + 2 ClassVar** (실제 `scripts/stacks/base.py::StackModule` Protocol 일치)
- **P0-2** `StackDetectResult` 필드명 정정: `runtime_version` → `version` / `direct_deps` 필드 추가 X (stateless 헬퍼로 재계산)
- **P0-3** `ProbePlan` → **`ProbeConfig`** (모든 출현 치환)
- **P0-4** `PipelineInputs` → **`UserInputs`** (모든 출현 치환)
- **P1-1/1-2** F-19/F-24/F-25/F-26/F-27/F-28/F-29 외부 통합 분할 (#12a/#12b)
- **P1-3** SD-1 src layout edge case 명시
- **P1-4** `sorted(candidates)` deterministic 보장 명시
- **P1-5** gap_reason `<your_app_var>` 힌트
- **P1-6** Dockerfile COPY Jinja2 분기 (lockfile_status별)
- **P1-7** Python 버전 화이트리스트 (3.9~3.12)
- **P2-1** `manifest_sources` 노출 메커니즘 명시 (`_detect_python_framework` tuple 반환)
- **P2-3** Phase α/β/γ/δ → 컴포넌트 매핑 표 (8절 신규)

## 책임 3-Layer (Final Policy Summary 직접 미러링)

```
감지 (build metadata only) → 설치 (lockfile 정책) → 실행 (dependency-conservative)
```

- **L1 감지 layer**: 매니페스트 파서 + 정규식 + `_detect_python_framework` + `_detect_python_version` + 안전 IO
- **L2 설치 layer**: `python.tmpl` Jinja2 Dockerfile + `PythonStackModule.build_plan` + `dockerfile_context` lockfile 분기
- **L3 실행 layer**: `_detect_server_command` (F-20-1 3조건 통합) + `_infer_entrypoint` (SD-1) + `ServerCmdResult` + `PythonStackModule.probe_plan` framework 분기
- **외부 통합**: `_SUPPORTED_STACKS` + `stack_registry` + project_analyzer auto-detect + `.devflow-k8s-deploy.yml` schema 확장 + manifest renderer stack-aware 주석 + SKILL.md description

## 컴포넌트 목록 (R1 수정 반영)

| # | 컴포넌트 | 책임 | 타입 | Layer | 매핑 F-ID |
|---|---------|------|------|-------|----------|
| 1 | `_DJANGO_RE` / `_FLASK_RE` / `_FASTAPI_RE` | 정규식 단일 출처. PEP 503 normalize + extras 허용 + version constraint. version-agnostic. ReDoS-free | Util (모듈 상수) | L1 | F-07 |
| 2 | `_parse_pyproject_toml` | PEP 621 + Poetry direct deps union — `tomllib`(stdlib 3.11+) 사용. 빈 set 폴백 | Util | L1 | F-06 |
| 3 | `_parse_requirements_txt` | **root `requirements.txt`만** 파서. `-r`/`-c` / sub-dir / `requirements-*.txt` 모두 skip (F-06-1 단일 출처) | Util | L1 | F-06-1 |
| 4 | `_match_frameworks` + `_detect_python_framework` | "Direct dependency wins" 4단계. **`_detect_python_framework`는 `tuple[str, frozenset[str], list[str]]` 반환** = `(framework, direct_deps, manifest_sources)`. 호출자가 direct_deps/manifest_sources 재사용 (P2-1) | Util | L1 | F-05/06/08/09/10 |
| 5 | `_detect_python_version` | `requires-python` → major.minor 하한. 부재/parse 실패 → `"3.11"`. **Python 2 explicit guard**. **버전 화이트리스트 `{3.9, 3.10, 3.11, 3.12}`** 외 → `"3.11"` fallback + rationale (P1-7) | Util | L1 | F-11/12 |
| 6 | `_read_python_file_safe` | 매니페스트 안전 read. symlink escape + IO 오류 흡수, MemoryError 비흡수 | Util | L1 | F-04/10 |
| 7 | `ServerCmdResult` | dataclass — `(cmd: list[str] \| None, requires_pkg: str \| None, gap_reason: str \| None)`. frozen | Util (dataclass) | L3 | F-20 |
| 8 | `_infer_entrypoint` | server entrypoint 휴리스틱 (SD-1 알고리즘 4절 — django wsgi 1단계 깊이, src layout 미지원→generic 폴백 / flask·fastapi main→app) | Util | L3 | F-23/SD-1 |
| 9 | `_detect_server_command` | **F-20-1 3조건 통합** 단일 출처. `(framework, project_dir, direct_deps) -> ServerCmdResult`. 자동 install 금지 (F-22-1) | Util | L3 | F-20~22 |
| 10 | `PythonStackModule` (신규) | `scripts/stacks/base.py::StackModule` Protocol 구현. **7메서드 + 2 ClassVar** (실제 Protocol 정합). 5절 인터페이스 참조 | Service (Protocol) | L1+L2+L3 | F-01/09/17/18/19 |
| 11 | `python.tmpl` (신규) | `templates/dockerfile/python.tmpl` Jinja2 multi-stage uv. builder=`uv sync` lockfile 분기 / runner=`python:{version}-slim` 비-root. **COPY 라인 Jinja2 if 분기 (lockfile_status별)** (P1-6) | Util (template asset) | L2 | F-13~F-17 |
| **12a** | 코어 통합 3건 (수정) | (a) `scripts/config_loader.py::_SUPPORTED_STACKS`에 `"python"` 추가 / (b) `scripts/pipeline/orchestrator.py::stack_registry` DI / (c) `scripts/project_analyzer.py::_detect_stack` auto-detect 분기 | Adapter (수정) | 통합 | F-02/03/04 |
| **12b** | 부가 통합 3건 (수정) | (d) `.devflow-k8s-deploy.yml` JSON Schema에 `stack.python.{probe.path, entrypoint, python_version}` 추가 / (e) manifest renderer rationale 주석 `# stack: python ({framework})` 추가 / (f) `skills/devflow-k8s-deploy/SKILL.md` description "JVM + Go" → "JVM + Go + Python" | Adapter (수정) | 통합/문서 | F-25/F-26/F-27 |
| **12c** | `text_safety` 회귀 가드 | 변경 없음. python entrypoint(`uvicorn`/`gunicorn` args 포함) + python probe.path가 shell-meta 차단 정책 통과하는지 회귀 테스트만 추가 (F-19/F-24/F-28/F-29 위임) | Adapter (테스트) | 통합 | F-19/F-24/F-28/F-29 |

총 **14개 컴포넌트** (10 신규 + 1 dataclass + 1 template + 3 통합 묶음). LIST 가독성 향상 위해 외부 통합을 12a/12b/12c로 분할 (P2-4).

## 책임 경계 (Boundaries)

- **Util 계층 (stateless)**: 정규식 + 매니페스트 파서 + 감지 알고리즘 + entrypoint 휴리스틱. `_read_python_file_safe` 단일 IO 진입, 파일 오류 흡수 (NFR-3). 다른 Util은 순수 함수.
- **Service 계층 (StackModule Protocol)**: `PythonStackModule`만 Protocol 구현체. JVM/Go와 byte-identical 회귀 (NFR-2 928 tests). `direct_deps`는 dataclass 확장 없이 `_detect_python_framework` tuple 반환으로 흘림.
- **Adapter 계층 (외부 통합)**: 12a 코어 3건 (각 1줄) / 12b 부가 3건 (config schema + manifest 주석 + SKILL.md) / 12c text_safety 회귀 가드 (테스트만).
- **Template asset**: `python.tmpl` Jinja2 — `templates/dockerfile/` 패턴 (manifest 렌더링 ADR-0001과 별도, Dockerfile은 stack 모듈이 책임).
- **변경 없는 경계**: `StackModule` Protocol(base.py), `JVMStackModule`, `GoStackModule`, `ProjectAnalyzer` 핵심 로직, `ConfigLoader.stack_decision`, `text_safety` 알고리즘 자체.

## 단일 모듈 정합성 (BL-017 패턴 미러링)

L1/L3 컴포넌트(1~9)는 **모두 `scripts/stacks/python.py` 단일 파일 내부**에 위치 (모듈 헬퍼 + 상수 + dataclass + Service 메서드).

---

# DETAIL 단계 — 상세 설계 (Standard depth)

## 4. Sub-OQ SD-1 확정 — `_infer_entrypoint` 알고리즘

### 4-1. django 분기

```
입력: project_dir
1. project_dir/manage.py 존재? 없으면 → return None
2. project_dir 직속 디렉토리(1단계 깊이) 중 <dir>/wsgi.py 후보 수집
3. 후보 0개 → return None
   (가능 원인: (a) src layout, (b) wsgi.py 부재. 둘 다 generic 폴백 + override 안내)
4. 후보 1개 → return f"{dir}.wsgi:application"
5. 후보 N>=2개 → sorted(candidates) 후 첫 매치 사용 (P1-4: locale-free codepoint order)
   + gap_reason 경고 ("multiple wsgi candidates: <a>, <b>, ... — using <a> (sorted). Set stack.python.entrypoint to disambiguate.")
```

**탐색 깊이**: 1단계만(`project_dir/*/wsgi.py`). 재귀 X. 비용 상한 O(N).

**P1-3 — src layout 명시 처리**: Django `src/myproj/wsgi.py` 같은 2단계 깊이는 본 알고리즘으로 미감지 → C2 케이스(entrypoint heuristic failed) → gap_reason: `"django: wsgi.py not found in 1-level subdirs of project root. If src layout, set stack.python.entrypoint to <pkg>.wsgi:application."`

### 4-2. flask / fastapi 분기

```
입력: framework, project_dir
1. project_dir/main.py 존재? → return "main:app"
2. project_dir/app.py  존재? → return "app:app"
3. 둘 다 없음 → return None
```

**P1-5 — 변수명 가정**: `app = Flask(...)` / `app = FastAPI(...)` 관용 변수명. 사용자가 `application = Flask(...)` 또는 `api = FastAPI(...)` 형태 사용 시 자동 추론 결과(`main:app`)는 import 시 `AttributeError` 가능. gap_reason 안내에 힌트:

> `"flask/fastapi: assumed variable name 'app' in {file}. If your app is bound to a different name (e.g. application, api), set stack.python.entrypoint to <module>:<your_app_var>."`

### 4-3. python-generic 분기

```
return None (즉시)
```

F-20-1 조건 1이 이미 실패 → 조건 3 검사 무의미.

### 4-4. 비용 보장

- 모든 FS 호출 read-only stat / `Path.exists` / `Path.iterdir`. write 없음.
- 최대 IO: django=O(N where N=top-level dir count) / flask·fastapi=O(1) (`main.py` + `app.py` exists)
- symlink escape 가드(`_read_python_file_safe`의 `is_within`) 적용

## 5. PythonStackModule Public Interface (실제 Protocol 정합)

> 모듈: `scripts/stacks/python.py`. `scripts/stacks/base.py::StackModule` Protocol 구현. 메서드 시그니처는 모두 **실제 Protocol과 일치**.

```python
from typing import ClassVar
from pathlib import Path
from scripts._shared.types import (
    BuildPlan, ProbeConfig, ProbeSpec, ResourceDefaults,
    StackDetectResult, UserInputs,
)
from scripts.stacks.base import ResourceHint, StackModule


class PythonStackModule:
    """StackModule Protocol 구현 — Python 스택 (BL-006)."""

    name: ClassVar[str] = "python"
    template_name: ClassVar[str] = "python"  # templates/dockerfile/python.tmpl 키

    # ─── 1) detect ───
    def detect(self, project_dir: Path) -> StackDetectResult | None:
        """이 스택인지 감지. 매니페스트 부재 → None.

        매니페스트 발견 시:
          framework, direct_deps, manifest_sources = _detect_python_framework(project_dir)
          version = _detect_python_version(project_dir)  # "3.11" default + 화이트리스트 보정
          entrypoint = _infer_entrypoint(framework, project_dir) or ""  # 미결정 sentinel
          → StackDetectResult(
              port=None,                  # F-22-1: port 자동화 없음
              entrypoint=entrypoint,      # "<module>:<var>" or "" (sentinel)
              framework=framework,        # "django"/"flask"/"fastapi"/"python-generic"
              version=version,            # Python major.minor (P0-2: runtime_version → version 통일)
              build_system=None,          # JVM 전용
              actuator_enabled=False,     # JVM 전용
              cmd_candidates=[],          # Go multi-binary 전용
          )

        Raises: 없음 — 모든 오류 안전 폴백 (NFR-3). 매니페스트 미존재만 None.
        """

    # ─── 2) build_plan ───
    def build_plan(
        self,
        detect_result: StackDetectResult,
        *,
        inputs: UserInputs | None = None,
    ) -> BuildPlan:
        """uv-based multi-stage Dockerfile 계획 산출.

        Returns BuildPlan(
            builder_image=f"ghcr.io/astral-sh/uv:python{detect_result.version}-bookworm-slim",
            runner_image=f"python:{detect_result.version}-slim",
            build_cmd=_resolve_uv_sync_cmd(project_dir, ...),  # lockfile 분기 (F-14)
            artifact_path="/app/.venv",
        )

        Raises: PythonBuildPlanError — uv 명령 합성 실패 (현재 시나리오 없음, future-proof)
        """

    # ─── 3) probe_plan ───
    def probe_plan(self, detect_result: StackDetectResult) -> ProbeConfig:
        """liveness / readiness ProbeConfig.

        _HEALTH_FRAMEWORKS = frozenset({"django", "flask", "fastapi"})
        _DEFAULT_PROBE_PORT: int = 8000  # 모듈 상수 — F-21 default CMD와 단일 출처 (P2-new-2)

        path = "/health" if detect_result.framework in _HEALTH_FRAMEWORKS else "/healthz"
        port = detect_result.port or _DEFAULT_PROBE_PORT
        # NOTE: Protocol 시그니처상 inputs를 받지 않음 (base.py:71). UserInputs.port와의 통일은
        # ProjectAnalyzer가 detect_result.port에 inputs.port를 합성하는 책임 (BL-001 패턴 일관).
        # 본 메서드는 detect_result.port 우선, 부재 시 모듈 상수 fallback.

        return ProbeConfig(
            liveness=ProbeSpec(kind="http", path=path, port=port),
            readiness=ProbeSpec(kind="http", path=path, port=port),
        )
        """

    # ─── 4) defaults ───
    def defaults(self, resource_hint: ResourceHint) -> ResourceDefaults:
        """tier별 리소스 + writable_paths + UID.

        tier 매핑 (JVM/Go 패턴 일관):
          small  → cpu=100m/250m, mem=128Mi/256Mi
          medium → cpu=250m/500m, mem=256Mi/512Mi
          large  → cpu=500m/1000m, mem=512Mi/1024Mi
        writable_paths = ["/tmp", "/app/.cache"]  # uv/pip 캐시
        run_as_user = 10001  # F-16 보안 디폴트
        """

    # ─── 5) artifact_locator ───
    def artifact_locator(
        self,
        detect_result: StackDetectResult,
        project_dir: Path,
    ) -> list[Path]:
        """Dockerfile COPY 소스 후보 — Python은 venv + 앱 소스 전체.

        Returns:
          [project_dir]  # 앱 소스 전체 (Dockerfile COPY . . 패턴)
          # /app/.venv는 builder stage에서 생성되므로 host 후보 아님
        """

    # ─── 6) dockerfile_context ─── (P0-1: dockerfile_build_context → dockerfile_context)
    def dockerfile_context(
        self,
        *,
        build_plan: BuildPlan,
        detect_result: StackDetectResult,
        inputs: UserInputs,
        project_dir: Path | None,
    ) -> dict[str, object]:
        """python.tmpl Jinja2 컨텍스트 매핑 (스키마는 6절).

        - direct_deps / manifest_sources는 _detect_python_framework 재호출로 취득 (stateless)
        - server_cmd = _detect_server_command(detect_result.framework, project_dir, direct_deps)
        - lockfile_status: project_dir의 uv.lock / pyproject.toml / requirements.txt 존재 여부로 결정
        """
```

## 6. python.tmpl Jinja2 Context 스키마 (P1-6 + P2-1 반영)

`PythonStackModule.dockerfile_context()` 반환 dict:

| 키 | 타입 | 값 / 예시 | 출처 |
|---|---|---|---|
| `python_version` | `str` | `"3.11"` / `"3.12"` (화이트리스트 내) | `_detect_python_version` |
| `framework` | `str` | `"fastapi"` / `"python-generic"` | `_detect_python_framework[0]` |
| `manifest_sources` | `list[str]` | `["pyproject.toml", "requirements.txt"]` | `_detect_python_framework[2]` (P2-1: tuple 반환 노출) |
| `uv_sync_cmd` | `str` | `"uv sync --frozen --no-dev"` 또는 `"uv venv .venv && uv pip install --python /app/.venv -r requirements.txt"` | F-14 lockfile 분기 |
| `lockfile_status` | `str` | `"frozen"` / `"non-frozen-warning"` / `"requirements-txt"` / `"none"` | F-14 분기 결과 |
| `has_pyproject` | `bool` | `True` / `False` | project_dir scan (P1-6: COPY 분기 Jinja2 if용) |
| `has_uvlock` | `bool` | `True` / `False` | project_dir scan |
| `has_requirements` | `bool` | `True` / `False` | project_dir scan |
| `entrypoint_cmd` | `list[str]` | `["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]` / `[]` (generic) | `_detect_server_command` |
| `entrypoint_gap` | `str \| None` | gap_reason 또는 None | `ServerCmdResult.gap_reason` |
| `port` | `int` | `inputs.port` | `UserInputs.port` |
| `app_user_uid` | `int` | `10001` | F-16 보안 디폴트 |
| `app_user_gid` | `int` | `10001` | F-16 |

**템플릿 스케치** (P1-6 COPY 분기 반영):

```dockerfile
# syntax=docker/dockerfile:1.6
# stack: python ({{ framework }})
# manifest sources: {{ manifest_sources | join(", ") }}
{%- if lockfile_status == "non-frozen-warning" %}
# WARNING: no uv.lock — reproducibility weakened. Add uv.lock for reproducible builds.
{%- endif %}

FROM ghcr.io/astral-sh/uv:python{{ python_version }}-bookworm-slim AS builder
WORKDIR /app

{%- if has_pyproject %}
COPY pyproject.toml ./
{%- endif %}
{%- if has_uvlock %}
COPY uv.lock ./
{%- endif %}
{%- if has_requirements %}
COPY requirements.txt ./
{%- endif %}

RUN {{ uv_sync_cmd }}
COPY . .

FROM python:{{ python_version }}-slim AS runner
RUN groupadd -g {{ app_user_gid }} appuser \
 && useradd  -u {{ app_user_uid }} -g {{ app_user_gid }} -m appuser \
 && apt-get clean && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder --chown={{ app_user_uid }}:{{ app_user_gid }} /app/.venv /app/.venv
COPY --from=builder --chown={{ app_user_uid }}:{{ app_user_gid }} /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER {{ app_user_uid }}:{{ app_user_gid }}
EXPOSE {{ port }}
{%- if entrypoint_cmd %}
CMD {{ entrypoint_cmd | tojson }}
{%- else %}
# entrypoint gap: {{ entrypoint_gap }}
# Configure .devflow-k8s-deploy.yml::stack.python.entrypoint to enable CMD generation
{%- endif %}
```

**P1-7 Python 버전 화이트리스트**: `_detect_python_version`이 `{3.9, 3.10, 3.11, 3.12}` 외 반환 시 → `"3.11"` fallback + rationale (예: `requires-python = ">=3.13"` 같은 신버전은 default 3.11 사용 + 사용자 경고). 화이트리스트는 모듈 상수 `_SUPPORTED_PYTHON_VERSIONS = frozenset({"3.9","3.10","3.11","3.12"})`. 신버전 추가는 후속 backlog.

## 7. F-20-1 3조건 의사결정 표 (gap_reason 톤 통일 — P2-2)

> framework ∈ supported = {django, flask, fastapi}. supported_pkg = {django:gunicorn, flask:gunicorn, fastapi:uvicorn}.

**통일 템플릿**: `"<상황 설명>. Action: <X> AND/OR <Y>."`

| 케이스 | framework | server pkg in direct_deps | entrypoint 추론 | 결과 cmd | gap_reason (통일 톤) |
|---|---|---|---|---|---|
| **C1** | supported (정확 1개) | ✅ | ✅ | **F-21 default CMD** | `None` |
| C2 | supported (정확 1개) | ✅ | ❌ | None | `"{framework}: entrypoint heuristic failed. Action: set stack.python.entrypoint to <module>:<your_app_var> (e.g. main:app, app:app)."` |
| C3 | supported (정확 1개) | ❌ | ✅ | None | `"missing inferred server package: {pkg}. Action: add {pkg} to direct dependencies AND/OR set stack.python.entrypoint."` |
| C4 | supported (정확 1개) | ❌ | ❌ | None | `"both server package ({pkg}) and entrypoint missing. Action: add {pkg} to direct dependencies AND set stack.python.entrypoint to <module>:<your_app_var>."` |
| C5 | python-generic (multi-match) | — | — | None | `"ambiguous framework match: {detected_set}. Action: keep only one of {detected_set} in direct dependencies OR set stack.python.entrypoint."` |
| C6 | python-generic (no match) | — | — | None | `"no supported framework detected (looked for django/flask/fastapi in direct dependencies). Action: add a supported framework OR set stack.python.entrypoint."` |

**핵심 불변량**: 오직 **C1**만 cmd 자동 생성. 5케이스 모두 cmd=None + override 안내. gap_reason은 `"<situation>. Action: <X> AND/OR <Y>."` 단일 톤.

## 8. Phase α/β/γ/δ → 컴포넌트 매핑 (P2-3, workflow-plan A안 정합)

| Phase | 책임 | 컴포넌트 # | 매핑 F-ID | 단위 테스트 목표 |
|---|---|---|---|---|
| **α** (감지 layer) | 매니페스트 파서 + 정규식 + framework/version 결정 + 안전 IO | 1, 2, 3, 4, 5, 6 | F-05~F-12 + F-06-1 | ≥ 15 |
| **β** (빌드 layer) | Dockerfile 템플릿 + uv_sync 분기 + Jinja2 context + probe path | 11 + `PythonStackModule.{build_plan, probe_plan, defaults, artifact_locator, dockerfile_context}` | F-13~F-19 | ≥ 10 |
| **γ** (실행 layer) | server CMD 자동 생성 (F-20-1 3조건) + entrypoint 휴리스틱 + dataclass | 7, 8, 9 + `PythonStackModule.detect`의 entrypoint 통합 | F-20~F-24 (+ SD-1) | ≥ 8 |
| **δ** (외부 통합) | config / DI / analyzer / schema / manifest renderer / SKILL.md / text_safety 회귀 | 10(ClassVar `name`/`template_name`만), 12a, 12b, 12c | F-01~F-04 + F-25~F-29 | ≥ 5 (회귀 가드) |

**컴포넌트 #10(`PythonStackModule`) Phase 분산**: 본체는 단일 클래스지만 책임이 layer를 횡단함 — `detect` 메서드는 α(L1 헬퍼 호출)와 γ(entrypoint 통합) 양쪽 / `build_plan` + `probe_plan` + `defaults` + `artifact_locator` + `dockerfile_context`는 β(빌드/probe 계획) / ClassVar `name`/`template_name`은 δ(orchestrator DI 등록 시점에 필요). 8절 표는 ClassVar만 δ로 표기. 메서드 구현은 commit-level에서 β/γ 분리.

각 Phase는 단일 PR 내에서 **commit 그룹으로 분리**(A안 정책). reviewer는 Phase α commit부터 순서대로 읽으면 책임 흐름 파악 가능.

## 9. 의존성 다이어그램 (ASCII, 단방향 무순환)

```
+-----------------------------+
| 12a 코어 통합 3건 (수정)    | config_loader / orchestrator / project_analyzer
+--------------+--------------+
               |
               v
+--------------+--------------+
|     PythonStackModule       | Service (StackModule Protocol 구현 — 7 메서드)
| (name, template_name ClassVar)|
+--+----+----+-----+----+-----+
   |    |    |     |    |
   |    |    |     |    +-----------------------+
   |    |    |     |                            v
   |    |    |     |                +-----------+--------+
   |    |    |     |                | _detect_server_cmd |  L3 (F-20-1 3조건)
   |    |    |     |                +--+-----------+-----+
   |    |    |     |                   |           |
   |    |    |     |                   v           v
   |    |    |     |        +----------+--+   +----+----------+
   |    |    |     |        | _infer_     |   | ServerCmdRes  |  dataclass
   |    |    |     |        | _entrypoint |   +---------------+
   |    |    |     |        +-------------+
   |    |    |     |
   |    |    |     +---------------+
   |    |    |                     v
   |    |    |          +----------+-----------+
   |    |    |          | 12c text_safety회귀 | F-19/24/28/29 위임
   |    |    |          +----------------------+
   |    |    v
   |    |   +-------+
   |    |   | python|   L2 (Jinja2 template asset)
   |    |   | .tmpl |
   |    |   +-------+
   |    |
   |    v
+--+---+---------------------+
|   _detect_python_framework  | L1 (tuple 반환 — framework + direct_deps + manifest_sources)
+-+---+-----------------------+
  |   |
  v   v
+-+-+---+--+   +---+--------------------+
| _parse_  |   | _parse_requirements_txt|  L1 manifest parsers
| pyproj   |   +------------------------+
+----+-----+
     |
     v
+----+----------------+   +---+-------------------+
| _detect_python_     |   | _read_python_file_safe|  L1 안전 IO
| _version            |   +-----------------------+
| (+화이트리스트 P1-7)|
+---------------------+

+--------------------+
| _DJANGO_RE etc.    |   L1 모듈 상수 (다른 모든 L1이 참조)
+--------------------+

+--------------------+
| 12b 부가 통합 3건  | config schema (F-25) / manifest 주석 (F-26) / SKILL.md (F-27)
+--------------------+   PythonStackModule과 독립 — δ Phase
```

## 10. 변경 영향 (회귀 가드)

| 외부 컴포넌트 | 변경 | 회귀 영향 |
|---|---|---|
| `scripts/config_loader.py::_SUPPORTED_STACKS` | `+"python"` (1줄) | 기존 stack_decision 분기 unchanged |
| `scripts/pipeline/orchestrator.py::stack_registry` | `+"python": PythonStackModule()` (1줄) | DI 등록만 |
| `scripts/project_analyzer.py::_detect_stack` | pyproject/requirements 감지 분기 추가 | JVM/Go 우선순위 유지 |
| `.devflow-k8s-deploy.yml` JSON Schema | `stack.python.{probe.path, entrypoint, python_version}` 추가 | 기존 stack.{jvm,go} schema unchanged |
| manifest renderer | `# stack: python ({framework})` rationale 주석 추가 (5종 모두) | BL-018 단일 경로 + BL-021 stack-aware 일관 |
| `skills/devflow-k8s-deploy/SKILL.md` | description 수정 | 사용자 향 문서만 |
| `templates/dockerfile/python.tmpl` | 신규 파일 | 기존 jvm.tmpl / go.tmpl byte-identical |
| `scripts/_shared/text_safety.py` | 변경 없음 (테스트만 추가) | python entrypoint/probe.path가 기존 정책 통과 |

**회귀 가드 카운트** (NFR-2): 외부 통합 6건 + text_safety 0건 변경. 모두 보수적 변경 → 928 기존 tests 무영향.

## 11. R1 spec-reviewer Cross-cutting Notes 반영

- **품질**: P0 4건 모두 정정 — Protocol 시그니처/dataclass 필드명/타입명 실제 코드와 일치. construction 진입 시 컴파일 OK.
- **보안**: `_read_python_file_safe` symlink escape + MemoryError 비흡수 정책은 BL-017 일관. **P1-6 Dockerfile COPY는 Jinja2 if 분기로 명시 파일만 COPY** (glob 사용 안 함 → `requirements.txt.bak` 같은 의도치 않은 파일 포함 위험 차단).

## 12. INCEPTION 완료 준비 체크리스트

- ✅ 14개 컴포넌트 (LIST 분할 — 외부 통합 12a/12b/12c)
- ✅ PythonStackModule 인터페이스 실제 Protocol 정합 (7메서드 + 2 ClassVar)
- ✅ SD-1 알고리즘 확정 (django/flask·fastapi/generic, src layout 명시, sorted deterministic)
- ✅ F-20-1 6 케이스 매트릭스 + gap_reason 통일 톤
- ✅ python.tmpl 스키마 13 keys + Jinja2 COPY 분기 + Python 버전 화이트리스트
- ✅ Phase α/β/γ/δ → 컴포넌트 매핑 (workflow-plan A안 정합)
- ✅ R1 P0 4건 + P1 7건 + P2 3건 반영 (P2-2/P2-4도 채택)
