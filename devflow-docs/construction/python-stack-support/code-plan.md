# Code Plan — BL-006 Python 스택 지원

**Ticket**: BL-006 ([#9](https://github.com/bluejayA/devflow-k8s-deploy/issues/9))
**Depth**: Standard (TDD RED→GREEN→REFACTOR 강제)
**Worktree**: `feature/python-stack-support` (base `45b0a72`, baseline **928 passed**)
**Approach**: A안 — 단일 PR + 내부 Phase α/β/γ/δ commit 분리
**미러링 source**: `scripts/stacks/go.py` (BL-017) + `tests/stacks/test_go.py`

---

## 신규/수정 파일

| 파일 | 종류 | Phase |
|------|------|-------|
| `scripts/stacks/python.py` | 신규 | α/β/γ |
| `tests/stacks/test_python.py` | 신규 | α/β/γ |
| `templates/dockerfile/python.tmpl` | 신규 | β |
| `scripts/_shared/errors.py` | 수정 (`PythonBuildPlanError` 추가) | β |
| `scripts/config_loader.py` | 수정 (`_SUPPORTED_STACKS += "python"`) | δ |
| `scripts/pipeline/orchestrator.py` | 수정 (`stack_registry += python`) | δ |
| `scripts/project_analyzer.py` | 수정 (detect 예외 catch 일관성, cosmetic) | δ |
| `.devflow-k8s-deploy.yml` JSON Schema | 수정 (`stack.python.*`) | δ |
| manifest renderer (rationale 주석) | 수정 | δ |
| `skills/devflow-k8s-deploy/SKILL.md` | 수정 (description) | δ |
| text_safety 회귀 테스트 | 신규 (테스트만) | δ |

---

## Phase α — 감지 layer (목표 단위 테스트 ≥ 15)

`scripts/stacks/python.py` 모듈 헬퍼 (순수 함수, stateless). go.py 4단계 알고리즘 미러링.

### 구현 순서 (TDD)

1. **모듈 상수 정규식** (F-07) — `_DJANGO_RE` / `_FLASK_RE` / `_FASTAPI_RE`
   - PEP 503 normalize (case-insensitive) + extras `[...]` 허용 + version constraint/EOL 검증
   - `flask-restful` 같은 sub-package false-match 차단 (boundary)
   - RED: 각 정규식 positive/negative 매칭 테스트 (django/Django/flask[async]/fastapi==0.1 vs flask-restful/django-extensions)
2. **`_read_python_file_safe`** (F-04/F-08/F-10) — `_read_go_file_safe` 미러링. symlink escape (`is_within`) + IO 오류 흡수, `MemoryError` 비흡수
3. **`_parse_pyproject_toml`** (F-06) — `tomllib`(stdlib 3.11+). `[project.dependencies]` + `[project.optional-dependencies.*]` + `[tool.poetry.dependencies]` union. 파싱 실패 → 빈 set
4. **`_parse_requirements_txt`** (F-06-1) — **root `requirements.txt`만**. `-r`/`-c`/sub-dir/`requirements-*.txt` 모두 skip
5. **`_match_frameworks`** + **`_detect_python_framework`** (F-05/06/08/09/10)
   - `_detect_python_framework -> tuple[str, frozenset[str], list[str]]` = `(framework, direct_deps, manifest_sources)` (P2-1)
   - "Direct dependency wins": union 단일 매치 → 채택 / 복수 → `python-generic` / 0개 → `python-generic`
6. **`_detect_python_version`** (F-11/12) — `requires-python` → major.minor 하한. 부재/실패 → `"3.11"`. **Python 2 explicit guard**. 화이트리스트 `_SUPPORTED_PYTHON_VERSIONS = {"3.9","3.10","3.11","3.12}` 외 → `"3.11"` fallback

### 핵심 테스트 케이스 (α)
- 정규식 6+ (positive: django/Django/flask[async]/fastapi[standard]==0.1 / negative: flask-restful/django-rest-framework/fastapi-utils)
- pyproject PEP 621 / Poetry / optional-deps union / 파싱 실패 폴백
- requirements.txt root only / `-r dev.txt` 무시 / `requirements-dev.txt` 무시
- `_detect_python_framework` tuple 반환 4단계 (single/multi→generic/none→generic/manifest_sources 정확)
- version: `>=3.11,<4`→3.11 / 부재→3.11 / `>=3.13`→화이트리스트 밖 3.11 fallback / `==2.7`→python-generic guard
- `_read_python_file_safe` symlink escape → "" / 미존재 → ""

---

## Phase β — 빌드 layer (목표 ≥ 10)

`PythonStackModule` 클래스 골격 + Dockerfile 계획. `errors.py`에 `PythonBuildPlanError` 추가.

1. **`PythonStackModule(name/template_name ClassVar)`** + `detect` (build metadata만, entrypoint=γ에서 통합 — β에선 `entrypoint=""` placeholder)
2. **`templates/dockerfile/python.tmpl`** (F-13~16) — multi-stage uv. builder=`ghcr.io/astral-sh/uv:python{ver}-bookworm-slim` / runner=`python:{ver}-slim` 비-root(10001). COPY Jinja2 if 분기 (has_pyproject/has_uvlock/has_requirements) — glob 미사용 (P1-6)
3. **`_resolve_uv_sync_cmd`** (F-14) — lockfile 분기: uv.lock→`uv sync --frozen --no-dev` / pyproject only→`uv sync --no-dev`(+warning) / requirements.txt only→`uv venv .venv && uv pip install --python /app/.venv -r requirements.txt`
4. **`build_plan`** (F-17) — `BuildPlan(builder_image, runner_image, build_cmd=uv_sync_cmd, artifact_path="/app/.venv")`
5. **`probe_plan`** (F-18) — `_HEALTH_FRAMEWORKS={django,flask,fastapi}` → `/health`, 외 → `/healthz`. `_DEFAULT_PROBE_PORT=8000`
6. **`defaults`** (F-16) — tier별 리소스 + `writable_paths=["/tmp","/app/.cache"]` + `run_as_user=10001`
7. **`artifact_locator`** → `[project_dir]`
8. **`dockerfile_context`** (F-17, 13 keys) — 6절 스키마. lockfile_status + has_* + manifest_sources 노출

### 핵심 테스트 (β)
- detect: pyproject 있음→StackDetectResult(version/framework) / 없음→None
- python.tmpl 렌더: frozen/non-frozen-warning/requirements-txt COPY 분기 byte 검증
- build_plan 이미지 태그 / probe_plan /health vs /healthz / defaults UID 10001 / dockerfile_context 13 keys

---

## Phase γ — 실행 layer (목표 ≥ 8)

CMD 자동 생성 (F-20-1 3조건) + entrypoint 휴리스틱 (SD-1).

1. **`ServerCmdResult`** dataclass (F-20) — frozen `(cmd: list[str]|None, requires_pkg: str|None, gap_reason: str|None)`
2. **`_infer_entrypoint`** (F-23/SD-1) — django(manage.py + 1단계 wsgi.py, sorted) / flask·fastapi(main.py→`main:app` / app.py→`app:app`) / generic→None
3. **`_detect_server_command`** (F-20~22, 3조건 통합) — C1만 CMD 생성, C2~C6 cmd=None + gap_reason 통일 톤 `"<situation>. Action: <X>."`
4. **`detect` entrypoint 통합** — `_infer_entrypoint` 결과를 `StackDetectResult.entrypoint`에 (sentinel "")
5. **`dockerfile_context`에 `entrypoint_cmd`/`entrypoint_gap` 연결** (β 보완)

### 핵심 테스트 (γ)
- `_infer_entrypoint`: django wsgi 1개/복수 sorted/src layout None / flask main:app / fastapi app:app / 없음 None
- `_detect_server_command` 6 케이스 매트릭스 (C1 CMD 생성 / C2~C6 None+gap_reason)
- dependency-conservative: gunicorn/uvicorn 부재 시 cmd=None (자동 install 금지)

---

## Phase δ — 외부 통합 (목표 회귀 가드 ≥ 5)

1. **config_loader** `_SUPPORTED_STACKS += "python"` (F-02)
2. **orchestrator** `stack_registry["python"] = PythonStackModule()` (F-03)
3. **project_analyzer** detect 예외 catch 일관성 (Python은 안전폴백이라 raise 없음 — cosmetic 확인만, F-04)
4. **`.devflow-k8s-deploy.yml` JSON Schema** `stack.python.{probe.path, entrypoint, python_version}` (F-25)
5. **manifest renderer** rationale 주석 `# stack: python ({framework})` (F-26)
6. **SKILL.md** description "JVM + Go" → "JVM + Go + Python" (F-27)
7. **text_safety 회귀 가드** (F-28/29) — python entrypoint(uvicorn/gunicorn args) + probe.path가 기존 정책 통과, shell-meta 거부 유지 (text_safety 변경 0)

### 핵심 테스트 (δ)
- config_loader python stack 허용 / orchestrator DI 등록 / e2e: pyproject 프로젝트 → python 감지 → manifest 생성
- text_safety: `["uvicorn","main:app","--host","0.0.0.0","--port","8000"]` 통과 / shell-meta 포함 거부

---

## 회귀 가드 (NFR-2)

- 기존 **928 tests byte-identical 유지**. JVM/Go 골든 무영향 (보수적 변경: 통합 6건 각 1~수줄)
- 목표: 928 → **≥ 960** (신규 ≥ 31)
- `_detect_stack` stack_registry 순회 — Python detect는 pyproject/requirements 부재 시 None → JVM/Go 충돌 없음

## 외부 리뷰 게이트 (CONSTRUCTION 후)
1. `/codex:review` 1차 (필수)
2. P2+ 발견 또는 큰 모듈 시 `agent-council` deep (layered_external_review)
3. 머지 전 `pytest` 전수 회귀
