# Requirements Analysis

**Depth**: Standard
**Timestamp**: 2026-05-13T23:30:00Z
**Ticket**: BL-006 ([#9](https://github.com/bluejayA/devflow-k8s-deploy/issues/9))
**Predecessor Patterns**: BL-001 (Go 스택 최소 스코프, #29/#30) + BL-017 (Go gin/echo/fiber framework 자동 감지, #39)
**Sibling Pattern**: BL-014 (#7 — JVM Ktor/Micronaut probe 자동 감지, 동일 카테고리)

## User Intent

devflow-k8s-deploy는 v0.5.0 시점에 **JVM + Go 듀얼 스택**을 지원한다. BL-006은 **Python 스택을 3번째 1급 스택으로 추가**하여 django/flask/fastapi 3대 Python 웹 프레임워크를 build metadata로 자동 감지하고, framework별 production-grade Dockerfile + 매니페스트를 zero-config로 생성한다. BL-001(Go 최소 스코프) + BL-017(Go 프레임워크 감지)에서 확립된 **StackModule Protocol + "Direct dependency wins" + version-agnostic + 단일 probe path** 패턴을 Python 생태계에 미러링한다.

### 스코프 제한 (사용자 확정 — Q1/Q2 응답 + OQ default 안 승인)

- **감지 소스는 build metadata 한정** — `pyproject.toml`의 `[project.dependencies]`(PEP 621) + `[tool.poetry.dependencies]`(Poetry) + `requirements.txt` 모두 **direct evidence**로 간주. `*.py` 소스 import 라인 스캔은 하지 않음 (BL-017 정책 일관).
- **"Direct dependency wins" 정책** (BL-017 미러링) — direct 단일 매치 → 해당 framework 채택 / direct 복수 매치 → `python-generic` 폴백 + rationale 기록 / direct 없음 → `python-generic` 폴백.
- **3개 프레임워크 모두 `/health` 통일 (version-agnostic)** — django/flask/fastapi 일관성. probe path override는 `.devflow-k8s-deploy.yml::stack.python.probe.path`(BL-001 패턴).
- **Dockerfile은 multi-stage uv 단일 정책** — uv 의존을 명시적 정책으로 수용. builder=`uv sync`(lockfile 분기), runner=`/app/.venv` + 앱 소스만 복사. pip 기반 conservative 모드는 backlog.
- **서버 CMD는 framework별 분기 + dependency-conservative** — 추론 서버 패키지(gunicorn/uvicorn)가 매니페스트에 **없으면 자동 install 금지** (gap 기록 + entrypoint override 안내). 컨테이너 내 multi-worker는 채택하지 않고 k8s replica로 수평 확장.
- **포트 자동화 없음** — framework별 기본 포트 임의 설정 안 함. 기존 port 결정 경로(`StackDetectResult.port` → `inputs.port`) 그대로 유지. CMD 내 포트는 `${PORT:-8000}` env-var 패턴.

## Functional Requirements

### Stack 등록 (StackModule Protocol 확장)

| ID | 요구사항 |
|----|---------|
| F-01 | `scripts/stacks/python.py` 신규 모듈 추가. `PythonStackModule` 클래스가 `scripts/stacks/base.py::StackModule` Protocol을 구현 (`detect`, `build_plan`, `probe_plan`, `dockerfile_template_path`, `dockerfile_build_context` 메서드 — BL-015 + BL-001 패턴) |
| F-02 | `scripts/config_loader.py`의 `_SUPPORTED_STACKS = frozenset({"auto", "jvm", "go"})`에 `"python"` 추가. stack_decision 로직 분기 확장 |
| F-03 | `scripts/pipeline/orchestrator.py`의 `stack_registry` DI에 `"python": PythonStackModule()` 등록 |
| F-04 | `scripts/project_analyzer.py`의 auto-detect 분기에 Python 매니페스트(`pyproject.toml` / `requirements.txt`) 발견 시 `python` 스택 결정 추가. JVM(`build.gradle*` `pom.xml`)/Go(`go.mod`)와의 우선순위는 **명시 stack 지정 > 매니페스트 발견 순서 > 폴백 generic** 기존 정책 그대로 |

### Framework 감지 (build metadata 기반 — BL-017 미러링)

| ID | 요구사항 |
|----|---------|
| F-05 | `scripts/stacks/python.py`에 `_detect_python_framework(project_dir: Path) -> str` 모듈 레벨 헬퍼 추가. 반환값: `"django"`, `"flask"`, `"fastapi"`, `"python-generic"` 중 하나 (literal string) |
| F-06 | **"Direct dependency wins"** 4단계 감지 알고리즘:<br>1. `pyproject.toml`을 파싱 — `[project.dependencies]`(PEP 621 list) + `[project.optional-dependencies.*]` + `[tool.poetry.dependencies]`(Poetry table) 모두 direct로 union<br>2. **root `requirements.txt`만** 추가 union (라인 단위 `package[extras]==ver`/`package>=ver` 형태). **F-06-1 스코프 제한 적용**<br>3. **1**, **2**에서 모은 direct 집합에 framework 정규식이 정확히 1개 매칭 → 해당 framework 채택<br>4. 2개 이상 매칭 → `"python-generic"` + rationale `"ambiguous: django+flask direct deps"` 기록 (manifest 주석/로그). 0개 매칭 → `"python-generic"`<br>5. **`*.py` import 라인 스캔 안 함** |
| **F-06-1** | **requirements 파일 스코프 제한** (사용자 보정 2026-05-13 — guardrail #1):<br>인식 대상은 다음으로 한정:<br>• `pyproject.toml::[project.dependencies]` (PEP 621)<br>• `pyproject.toml::[project.optional-dependencies.*]`<br>• `pyproject.toml::[tool.poetry.dependencies]` (Poetry)<br>• **root `requirements.txt`만**<br>**범위 밖** (본 작업에서 스캔 금지 — 추후 명시 config 옵션 도입은 후속 backlog):<br>• `requirements-dev.txt`, `requirements-prod.txt`, `requirements-test.txt` 등 suffix 변형<br>• `requirements/base.txt`, `requirements/*.txt` 디렉토리 구조<br>• `constraints.txt` (constraint file)<br>• `requirements.txt` 내부 `-r other.txt` / `-c constraints.txt` 참조 (1-depth 포함 X — 모두 무시)<br>• `Pipfile`, `setup.py` install_requires, Hatch metadata, PDM 등 (A-3 명시)<br>이 정책은 매니페스트 fan-out으로 인한 정책 번짐(`requirements-dev.txt`까지 따라가야 하나? `requirements/*.txt` 어디까지?)을 차단하기 위함. 누락된 framework가 dev/prod 변형 파일에만 있는 경우 → `python-generic` 폴백 + 사용자 override 안내 (NFR-6 rationale 주석에 명시) |
| F-07 | 정규식 (`re.compile` 모듈 상수, **BL-017 패턴 적용** — 패키지명 boundary + extras 허용):<br>• `_DJANGO_RE = re.compile(r"(?im)^\s*[Dd]jango(?:\[[^\]]+\])?(?:\s*[<>=!~]|$)")`<br>• `_FLASK_RE = re.compile(r"(?im)^\s*[Ff]lask(?:\[[^\]]+\])?(?:\s*[<>=!~]|$)")`<br>• `_FASTAPI_RE = re.compile(r"(?im)^\s*[Ff]astapi(?:\[[^\]]+\])?(?:\s*[<>=!~]|$)")`<br>패키지명 case-insensitive(PEP 503 normalize) + extras(`[standard]` 등) 허용 + version constraint 또는 라인 끝 검증. **하이픈/언더스코어 변형은 PEP 503 normalize 적용**(`flask-restful` 등 sub-package false-match 차단). 메이저 버전 capture 안 함 (version-agnostic) |
| F-08 | 파일 I/O: `pyproject.toml`/`requirements.txt` 읽기 실패(없음/권한 오류/UnicodeDecodeError/TOML 파싱 오류) 시 **에러 raise 금지** — 해당 소스를 빈 매핑으로 간주하고 다음 우선순위로 진행. 감지는 hint (NFR-3) |
| F-09 | `PythonStackModule.detect(project_dir)` 내부에서 `_detect_python_framework` 호출 후 `StackDetectResult.framework` 필드에 결과 기록 |
| F-10 | symlink escape 방어: `_detect_python_framework`가 매니페스트 경로를 읽기 전에 BL-001/017 `is_within(project_dir, target)` 가드 적용. 가드 실패 시 해당 파일은 미존재로 간주 |

### Python 버전 결정

| ID | 요구사항 |
|----|---------|
| F-11 | `pyproject.toml::requires-python` 값(예: `">=3.11,<4"`) 파싱 → SemVer-like 하한(major.minor) 추출. 부재 시 `3.11` default. 결과는 `StackDetectResult.runtime_version`(또는 동등 필드)에 기록되어 Dockerfile 템플릿 `python:{version}-slim` 베이스 이미지 태그로 전달 |
| F-12 | `requires-python` 파싱 실패(빈 문자열/형식 오류) 시 default `3.11` + rationale 경고 기록. 메이저 버전이 `2`로 추론되면 `python-generic` + 에러 (Python 2는 지원 안 함 — explicit guard) |

### Dockerfile 생성 (multi-stage uv)

| ID | 요구사항 |
|----|---------|
| F-13 | `templates/dockerfile/python.tmpl` 신규 추가. Jinja2 템플릿, multi-stage 구조:<br>• **stage 1 (builder)**: `ghcr.io/astral-sh/uv:python{{ python_version }}-bookworm-slim` 또는 동등 base. `uv sync` 실행 (아래 F-14 분기). 작업 디렉토리 `/app`<br>• **stage 2 (runner)**: `python:{{ python_version }}-slim` base. 비-root user(`appuser` uid=10001 — BL-001 패턴), `/app/.venv` + 앱 소스 `COPY --chown` 복사. `ENV PATH="/app/.venv/bin:$PATH"`. `EXPOSE {{ port }}`. `CMD {{ entrypoint_cmd }}` |
| F-14 | builder의 `uv sync` 명령 분기 (입력에 따라 템플릿 변수 `uv_sync_cmd` 또는 조건부 블록):<br>• `uv.lock` 존재 → `uv sync --frozen --no-dev`<br>• `pyproject.toml` 존재 + `uv.lock` 부재 → `uv sync --no-dev` (non-frozen) + Dockerfile rationale 주석에 `# WARNING: no uv.lock — reproducibility weakened` 삽입<br>• `requirements.txt` only (pyproject 부재) → `uv venv .venv && uv pip install --python /app/.venv -r requirements.txt` |
| F-15 | runner stage의 최종 이미지에 **uv/build deps 포함 금지**. `/app/.venv` + 앱 소스 + `python:slim` runtime만. 이미지 크기 검증은 NFR-4 위임 |
| F-16 | 보안 디폴트 (BL-001/017 + 기존 K8s 검증과 일치):<br>• `USER 10001:10001` 비-root<br>• `apt-get clean && rm -rf /var/lib/apt/lists/*` (apt 사용 시)<br>• `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1` env-var 명시<br>• `ENTRYPOINT` 사용 시 exec form(`["...", "..."]`) — shell form 금지 |
| F-17 | `PythonStackModule.dockerfile_template_path()` → `"templates/dockerfile/python.tmpl"` 반환. `dockerfile_build_context()` → `{python_version, uv_sync_cmd, lockfile_status, entrypoint_cmd, port, ...}` Jinja2 컨텍스트 매핑 |

### Probe path 정책 (BL-017 미러링)

| ID | 요구사항 |
|----|---------|
| F-18 | `_HEALTH_FRAMEWORKS = frozenset({"django", "flask", "fastapi"})` 모듈 상수. `PythonStackModule.probe_plan(stack_detect_result)` 내부에서 `framework in _HEALTH_FRAMEWORKS` → probe path `/health` 반환 / 외 → BL-001 generic 폴백 (`/healthz`) |
| F-19 | `.devflow-k8s-deploy.yml::stack.python.probe.path` override 지원. 기존 `text_safety::validate_probe_path` 정책 그대로 위임 (BL-019) |

### 서버 entrypoint 자동 생성 (framework별 분기 + dependency-conservative)

| ID | 요구사항 |
|----|---------|
| F-20 | `_detect_server_command(framework, project_dir, direct_deps) -> ServerCmdResult` 헬퍼. `ServerCmdResult`는 `(cmd: list[str] \| None, requires_pkg: str \| None, gap_reason: str \| None)` 형태 dataclass |
| **F-20-1** | **CMD 생성 3조건 정책** (사용자 보정 2026-05-13 — guardrail #2). `_detect_server_command`는 다음 **3조건이 모두 충족될 때에만** framework별 default CMD를 반환한다:<br>1. **정확히 1개의 supported framework가 감지되었음** (F-06 결과가 `django`/`flask`/`fastapi` 중 하나, `python-generic` 아님)<br>2. **추론 서버 패키지가 direct dependencies(F-06 union 집합)에 존재** (django→`gunicorn` / flask→`gunicorn` / fastapi→`uvicorn`)<br>3. **app entrypoint(`<module>:<app_var>`)가 휴리스틱으로 추론됨** (F-23 알고리즘 — application-design에서 정밀화)<br>한 조건이라도 실패 → 다음 모두 적용:<br>• `cmd=None` 반환 (`python-generic` 동등 거동으로 폴백)<br>• `gap_reason`에 실패 조건과 권고 액션 기록 (예: `"missing inferred server package: gunicorn. Add to dependencies or set stack.python.entrypoint."`)<br>• 매니페스트 rationale 주석에 gap 명시 (NFR-6 일관)<br>• `.devflow-k8s-deploy.yml::stack.python.entrypoint` override 가이드 안내<br>이 정책은 복수 프레임워크 감지·서버 패키지 누락·entrypoint 추론 실패를 **단일 원칙**으로 통합한다 (이전 F-22 + F-23 + F-24를 본 항목으로 흡수). |
| F-21 | framework별 default CMD (3조건 모두 통과 시. exec form list):<br>• **django** → `["gunicorn", "<project>.wsgi:application", "--bind", "0.0.0.0:8000"]`<br>• **flask** → `["gunicorn", "<module>:app", "--bind", "0.0.0.0:8000"]`<br>• **fastapi** → `["uvicorn", "<module>:app", "--host", "0.0.0.0", "--port", "8000"]`<br>• **python-generic** → `cmd=None`, `gap_reason="generic Python stack — entrypoint override required"` |
| F-22 | **dependency-conservative 정책** (사용자 codex 권장 직접 인용):<br>• 추론 서버 패키지(django→gunicorn / flask→gunicorn / fastapi→uvicorn)가 매니페스트(F-06 union 집합)에 있으면 → F-20-1 조건 2 통과<br>• 없으면 → 조건 2 실패 → cmd=None (자동 install **금지** — F-22-1) |
| F-22-1 | 자동 install 금지 정책 (default). 미래 `auto_install_server=true` opt-in 옵션은 backlog (Sub-OQ SD-2 → 별도 BL) |
| F-23 | entrypoint module/app 추론 = F-20-1 조건 3 (best-effort heuristic, application-design 단계에서 알고리즘 확정 — SD-1):<br>• django: `manage.py` 인접 폴더 중 `wsgi.py`를 포함한 첫 폴더명 → `<folder>.wsgi:application`<br>• flask/fastapi: `main.py` → `main:app` / `app.py` → `app:app` 우선순위 휴리스틱<br>• 감지 실패 → 조건 3 실패 → cmd=None |
| F-24 | F-20-1 모든 폴백 분기에서 `text_safety::validate_entrypoint`(BL-019) 정책 그대로 위임. shell-meta 차단 일관 |

### Config / 매니페스트 통합

| ID | 요구사항 |
|----|---------|
| F-25 | `.devflow-k8s-deploy.yml` 스키마 확장: `stack.python.{probe.path, entrypoint, python_version}` override 키. JSON Schema 갱신 (있을 경우) |
| F-26 | 매니페스트 5종(deployment/service/serviceaccount/statefulset/networkpolicy) 모두 BL-018 Jinja2 단일 렌더 경로 + BL-021 stack-aware rationale 주석 적용. python stack 시 주석에 `# stack: python ({framework})` 추가 |
| F-27 | `skills/devflow-k8s-deploy/SKILL.md` description 업데이트 — "JVM + Go" → "**JVM + Go + Python**" (BL-020 패턴 미러링) |

### Validation 통합 (BL-019 위임)

| ID | 요구사항 |
|----|---------|
| F-28 | `text_safety::validate_entrypoint`가 python 스택 CMD(uvicorn/gunicorn args 포함)를 통과시키는지 회귀 가드. shell-meta(`;`, `&`, `\``, `$()`, `|`)는 기존대로 거부 |
| F-29 | `text_safety::validate_probe_path`는 stack에 무관하게 동작 — 변경 불필요. 신규 테스트만 추가 |

## Non-Functional Requirements

| ID | 요구사항 |
|----|---------|
| NFR-1 | **테스트 커버리지**: BL-017 비례 — 신규 단위 테스트 ≥ 30건 (framework regex, 매니페스트 파서, _detect_python_framework 4단계, requires-python 파싱, server_command 감지, Dockerfile 템플릿 렌더 분기, probe_plan 분기, PythonStackModule.detect 통합) |
| NFR-2 | **회귀 가드**: 기존 928 tests 그대로 통과. 신규 31+건 추가 → 약 960+ tests 목표 |
| NFR-3 | **감지 실패 안전 폴백**: 파일 I/O 오류·TOML 파싱 오류·symlink escape·MemoryError(흡수 금지) 모두 `python-generic`으로 안전 폴백, exception leak 없음 |
| NFR-4 | **이미지 크기 검증**: runner 최종 이미지에 uv 바이너리 / build deps / `~/.cache/uv` 부재 검증 (통합 테스트 또는 manual smoke test) |
| NFR-5 | **이식성**: `_detect_python_framework`는 `os.path` 아닌 `pathlib.Path` 사용 (BL-017 정책 일관) |
| NFR-6 | **명시 가능성**: framework 감지 결과·gap·warning을 매니페스트/Dockerfile rationale 주석에 모두 기록 (BL-021 stack-aware 일관) |
| NFR-7 | **TDD**: RED → GREEN → REFACTOR 사이클 강제 (CLAUDE.md TDD Iron Law) |

## Technology Stack

(devflow-k8s-deploy 자체 스택 — workspace.md `## Pre-specified Tech Stack`에서 확정, 변경 없음. 본 표는 BL-006으로 *지원 대상*에 추가되는 Python 스택을 별도 명시.)

| 계층 | 선택 | 소스 | 비고 |
|------|------|------|------|
| (devflow-k8s-deploy 자체) Language | Python 3.11+ | CLAUDE.md | 변경 없음 |
| (devflow-k8s-deploy 자체) Package Manager | uv | CLAUDE.md | 변경 없음 |
| (지원 대상 추가) Python framework 감지 | django / flask / fastapi | BL-006 신규 | 정규식 + Direct dependency wins |
| (지원 대상 추가) Python 빌드 도구 | uv (multi-stage Dockerfile) | Q1 응답 (사용자 확정) | 명시적 정책. pip 모드는 backlog |
| (지원 대상 추가) WSGI 서버 | gunicorn (django/flask) | Q2 응답 (codex 권장) | dependency-conservative — 매니페스트에 있을 때만 자동 CMD |
| (지원 대상 추가) ASGI 서버 | uvicorn (fastapi) | Q2 응답 (codex 권장) | 컨테이너 내 multi-worker 없음, k8s replica로 수평 확장 |

## Assumptions

- A-1: `uv` 바이너리는 빌드 환경(builder stage)에서 항상 사용 가능 (공식 `ghcr.io/astral-sh/uv` 이미지 또는 동등 base).
- A-2: Python 3.11이 default 버전 — devflow-k8s-deploy 자체 최소 버전과 일치, 보안 패치 LTS 범위.
- A-3: `pyproject.toml` 외 매니페스트 (Pipfile, setup.py, Hatch metadata-version, PDM PEP 582) 는 **본 작업 범위 밖**. 사용자가 명시 지원 요청 시 별도 backlog로 분리.
- A-4: Python 2.x 명시 지원 안 함 — F-12 explicit guard.
- A-5: WSGI/ASGI 외 서버 (예: hypercorn, daphne) 자동 선택 안 함. fastapi=uvicorn 단일 정책. 사용자 요청 시 entrypoint override로 처리.
- A-6: pip-tools (`requirements.in` → `requirements.txt` 컴파일) 워크플로우는 결과물(`requirements.txt`) 기준으로만 인식.

## Open Questions

(없음 — Q1/Q2 사용자 응답 + OQ #1/#2/#4 default 안 승인으로 모두 확정)

## Sub-OQ (Detail Design로 이관)

| ID | 항목 | 처리 단계 |
|----|------|----------|
| SD-1 | 서버 entrypoint module/app name 추론 알고리즘 정밀화 (django wsgi 폴더 식별, flask/fastapi main vs app 우선순위, 휴리스틱 실패 시 generic 폴백 조건) | application-design |
| SD-2 | `auto_install_server=true` opt-in 옵션 도입 여부 | 후속 backlog (BL-006 머지 후 별도 ticket) |

## Final Policy Summary

(사용자 최종 요약 — 본 작업의 정책 1-pager. 구현 시 docstring/README/skill description 카피용)

```text
Python deployment support follows build-metadata-only detection.

Framework detection:
- Union direct dependencies from PEP 621, Poetry, and root requirements.txt.
- No source import scanning.
- Additional requirements files (requirements-dev.txt, requirements/*.txt,
  constraints.txt, -r/-c references) are out of scope.

Build:
- Multi-stage uv Dockerfile.
- Use frozen sync only when lockfile exists; non-frozen with warning otherwise.
- Copy /app/.venv into the runtime image; no uv or build deps in runtime.

Runtime:
- Default probe path is /health for django, flask, and fastapi.
- CMD is generated only when framework, server dependency, and entrypoint
  are all clear (single framework detected + server pkg in direct deps +
  entrypoint inferable).
- Generic Python requires stack.python.entrypoint override.
- Server dependency is never auto-installed (default; opt-in flag is backlog).
```

이 요약은 책임 분리를 명시: **감지(direct metadata) → 설치(lockfile 정책) → 실행(dependency-conservative)** 3-layer.

## Change Log

- `2026-05-13T23:30:00Z` — INITIAL: Standard depth, Q1(Dockerfile=uv multi-stage)/Q2(서버=framework별 분기 + uvicorn) 사용자 확정, OQ #1/#2/#4 default 안 승인. BL-017 패턴 미러링 명시.
- `2026-05-13T23:45:00Z` — UPDATE: 사용자 보정 2개 반영. (1) **F-06-1 신규** — requirements 파일 스코프를 root `requirements.txt`로 한정, suffix/디렉토리/constraints/`-r`·`-c` 참조 모두 범위 밖 명시. (2) **F-20-1 신규** — CMD 생성 3조건(framework 1개 + server pkg in direct + entrypoint 추론) 통합 정책 도입, 기존 F-22/F-23/F-24를 본 항목으로 흡수. **Final Policy Summary 섹션 신규** 추가.
