# devflow-k8s-deploy — 개발자 가이드

> 이 문서는 **플러그인을 이어서 개발할 사람**을 위한 설명서입니다.
> 플러그인 사용법은 루트 [README.md](../README.md)를 보세요.
>
> 기준 버전: **v0.4.0** (main `75c3426`, 2026-04-23 시점) · 테스트 **695 passed**

---

## 0. 최소 읽을 순서 (30분 컷)

이어받은 개발자라면 이 순서로 읽으면 전체 그림이 잡힙니다.

1. 본 문서 §1~§3 (개요 + 디렉토리 맵 + 5-STEP 파이프라인)
2. `scripts/_shared/types.py` — 모든 frozen dataclass가 한곳에 모여 있음. 이게 전체 데이터 계약.
3. `scripts/stacks/base.py` — `StackModule` Protocol. 스택 확장의 유일한 진입점.
4. `scripts/pipeline/orchestrator.py:205` `PipelineDependencies` — DI 묶음. 무엇이 어떻게 조립되는지.
5. `scripts/validators/registry.py` — `@register_rule` 디스패처 (30줄 짜리지만 검증 전체의 뼈대).
6. `devflow-docs/backlog.md` — 다음에 뭘 할지.

그다음에 §5~§7 (확장 가이드 / 테스트 / 릴리즈 프로세스)로 넘어가세요.

---

## 1. 프로젝트 개요

### 한 줄 요약

JVM(Kotlin/Java Spring Boot) 프로젝트를 읽어서 **보안 기본값이 주석과 함께 박힌 Dockerfile + Kubernetes manifest**를 생성하는 Claude Code 플러그인.

### 책임 경계 (설계 원칙)

| 하는 것 | 하지 않는 것 |
|---------|-------------|
| 파일 생성 (Dockerfile, k8s YAML, rationale, summary.json) | `docker push` / `kubectl apply` / 클러스터 API 호출 |
| 정적 검증 (`validate_k8s.py`) | 실제 배포 상태 확인 |
| `kubectl --dry-run=client --validate=false` (미설치 시 graceful skip) | 서버 사이드 검증 |
| 선택적 로컬 빌드 (`build.engine: auto`, opt-in) | 레지스트리 push |

**Create-only**는 이 프로젝트의 제 1원칙입니다. 이 경계를 흐리는 기능(예: `kubectl apply` 자동화)은 기본값으로 넣지 마세요.

### AIDLC 비종속

플러그인은 **aidlc-devflow 플러그인 없이도 단독으로 작동**합니다. 개발 과정은 AIDLC devflow를 썼지만, 산출물(스킬 + 스크립트)은 독립 실행 가능.

---

## 2. 디렉토리 맵

```
devflow-k8s-deploy/
├── .claude-plugin/
│   └── plugin.json               # plugin name/version/skills 경로
├── skills/
│   └── devflow-k8s-deploy/
│       ├── SKILL.md              # Claude가 읽는 스킬 본체 (5-STEP 지시문 + 트리거)
│       └── references/           # help-catalog.md, roadmap.md
├── scripts/                      # 실제 로직 (Python 3.11+)
│   ├── pipeline/
│   │   ├── orchestrator.py       # SkillPipeline — 5-STEP 실행
│   │   ├── retry_loop.py         # F-50 재시도 루프 래퍼
│   │   └── build_runner.py       # 컨테이너 빌드 (opt-in)
│   ├── stacks/
│   │   ├── base.py               # StackModule Protocol (확장 경계)
│   │   └── jvm.py                # JvmStackModule — v0.1~v0.4의 유일한 구현
│   ├── validators/
│   │   ├── core.py               # K8sValidator 클래스
│   │   ├── registry.py           # @register_rule 데코레이터
│   │   ├── helpers.py            # 공용 YAML 파싱 유틸
│   │   └── rules/                # 규칙 모듈 (scope별 분리)
│   │       ├── sec.py            # SEC-001~009 (securityContext)
│   │       ├── res.py            # RES-001, RES-W01
│   │       ├── img.py            # IMG-001, IMG-W01, IMG-W02
│   │       ├── prb.py            # PRB-001, PRB-002
│   │       ├── sa.py             # SA-001, SA-002
│   │       ├── life.py           # LIFE-W01
│   │       ├── svc.py            # SVC-001, SVC-002
│   │       ├── sts.py            # STS-W01 (StatefulSet)
│   │       └── net.py            # NET-W01 (NetworkPolicy)
│   ├── _shared/
│   │   ├── types.py              # 모든 frozen dataclass + Protocol 재수출
│   │   ├── errors.py             # 도메인 예외 계층
│   │   ├── defaults.py           # 내장 기본값 YAML 로더
│   │   ├── fileio.py             # read_text_limited, check_yaml_refs
│   │   ├── image_ref.py          # OCI ref allowlist (latest 금지)
│   │   ├── text_safety.py        # 개행/NUL 주입 방어
│   │   └── retry.py              # retry_with_fix 일반화
│   ├── project_analyzer.py       # STEP 2 — StackModule 레지스트리 룩업 + 실행
│   ├── config_loader.py          # 3계층 YAML 병합 + ClusterConfig 해석
│   ├── dockerfile_generator.py   # 스택 중립 facade (보안 검증만)
│   ├── manifest_generator.py     # Deployment/Service/SA/StatefulSet/NetworkPolicy
│   ├── template_renderer.py      # Jinja2 wrapper
│   ├── kubectl_dry_runner.py     # kubectl dry-run (graceful skip 지원)
│   ├── atomic_writer.py          # tmp → rename 원자적 쓰기
│   ├── output_packager.py        # rationale.md + summary.json
│   └── validate_k8s.py           # K8sValidator 공개 엔트리 + CLI
├── templates/
│   ├── dockerfile/
│   │   ├── jvm.tmpl              # v0.1~v0.4의 유일한 Dockerfile 템플릿
│   │   └── dockerignore.tmpl
│   └── manifest/
│       ├── deployment.tmpl
│       ├── service.tmpl
│       ├── serviceaccount.tmpl
│       ├── statefulset.tmpl      # v0.4.0 신규
│       └── networkpolicy.tmpl    # v0.4.0 신규
├── tests/                        # 695 tests (pytest)
│   ├── integration/              # E2E smoke, boundary allowlist
│   ├── stacks/                   # JvmStackModule 단위 테스트
│   ├── snapshots/bl015/          # Dockerfile byte-identical 골든 4종
│   ├── _shared/                  # 공용 fixture
│   └── test_*.py                 # 컴포넌트별 단위 테스트
├── devflow-docs/                 # AIDLC 산출물 (방법론 기록)
│   ├── inception/                # workflow-plan.md, requirements.md, user-stories.md, workspace.md
│   ├── construction/bl003-bl004/ # 최근 구현 code-plan
│   ├── release/                  # v0.1.0-release-notes.md
│   ├── backlog.md                # 다음 작업 원천
│   ├── audit.md / devflow-audit.md
│   └── DEVELOPER.md              # ← 이 문서
├── scripts/                      # (중복 — 위 참조)
├── .devflow-k8s-deploy.yml.sample # 사용자가 복사해서 쓰는 설정 예시
├── pyproject.toml                # uv + ruff + mypy strict + pytest
└── README.md                     # 사용자용 readme
```

---

## 3. 아키텍처 — 5-STEP 파이프라인

전체 진입점은 `scripts/pipeline/orchestrator.py`의 `SkillPipeline` 클래스. 메인은 CLI(`python scripts/pipeline/orchestrator.py --project-dir . --output-dir k8s-output/`), 내부에서 Claude가 SKILL.md 지시를 따라 STEP마다 사용자와 상호작용합니다.

### 데이터 흐름

```
 사용자 요청 ("Dockerfile 만들어줘")
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1 — 입력 수집                                              │
│   HelpCatalog + PromptCallback → UserInputs                     │
│   (app_name, port, exposure, namespace, output_dir,             │
│    resource_hint, replicas)                                     │
└─────────────────────────────────────────────────────────────────┘
      │                             .devflow-k8s-deploy.yml
      │                             ~/.claude/devflow-k8s-deploy.yml
      │                             ↓
      │         ConfigLoader.load() → ResolvedConfig (3계층 deep merge)
      │         ConfigLoader.resolve_cluster_config() → ClusterConfig
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 2 — 프로젝트 분석                                          │
│   ProjectAnalyzer.analyze(project_dir, config, resource_hint)  │
│     → StackModule.detect() → StackDetectResult                 │
│     → .build_plan() → BuildPlan                                │
│     → .probe_plan() → ProbeConfig                              │
│     → .defaults(hint) → ResourceDefaults                       │
│     → .artifact_locator() → list[Path]                         │
│   결과: AnalysisResult (+ StatefulnessSignal, gaps)             │
└─────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 3 — 아티팩트 생성 (AtomicWriter staging)                   │
│   DockerfileGenerator.generate(stack_module=...)               │
│     → stack_module.dockerfile_context() + template render       │
│   ManifestGenerator.generate_deployment/statefulset/...()       │
│   → GeneratedArtifacts(paths)                                   │
└─────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 4 — 검증 게이트 (retry_loop, max 3)                        │
│   ① K8sValidator.validate() → ValidationReport (exit 0/1/2)    │
│   ② KubectlDryRunner.dry_run() (미설치 시 skipped=True)        │
│   ③ BuildRunner.build() (opt-in, config.build.engine)          │
│   FAIL 시 _fix_* 스텁 → bail-out (v0.5+ auto-fix 예정)          │
└─────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 5 — 패키징 (AtomicWriter commit)                           │
│   OutputPackager → rationale.md + summary.json                  │
│   AtomicWriter.commit() — tmp → 최종 경로 원자적 이동           │
└─────────────────────────────────────────────────────────────────┘
      │
      ▼
 Exit code 0 / 1 / 2 (F-42)
```

### DI 조립 지점

모든 컴포넌트는 `PipelineDependencies` frozen dataclass로 주입됩니다 (`orchestrator.py:208`). 테스트에서는 MagicMock으로 쉽게 교체 가능.

```python
@dataclass(frozen=True)
class PipelineDependencies:
    config_loader: ConfigLoader
    project_analyzer: ProjectAnalyzer
    dockerfile_generator: DockerfileGenerator
    manifest_generator: ManifestGenerator
    k8s_validator: K8sValidator
    kubectl_dry_runner: KubectlDryRunner
    build_runner: BuildRunner
    output_packager: OutputPackager
    stack_registry: dict[str, StackModule]   # ← 스택 확장의 조립 지점
```

새 스택을 추가하면 `stack_registry`에 인스턴스를 등록하는 것만으로 orchestrator가 `analysis.stack` 키로 룩업합니다.

---

## 4. 핵심 추상화

### 4.1 `StackModule` Protocol — 스택 확장의 유일한 계약

`scripts/stacks/base.py`.

```python
@runtime_checkable
class StackModule(Protocol):
    name: ClassVar[str]              # "jvm", "go", ...
    template_name: ClassVar[str]     # Dockerfile 템플릿 키 → templates/dockerfile/{template_name}.tmpl

    def detect(self, project_dir: Path) -> StackDetectResult | None: ...
    def build_plan(self, detect_result: StackDetectResult) -> BuildPlan: ...
    def probe_plan(self, detect_result: StackDetectResult) -> ProbeConfig: ...
    def defaults(self, resource_hint: ResourceHint) -> ResourceDefaults: ...
    def artifact_locator(self, detect_result, project_dir: Path) -> list[Path]: ...
    def dockerfile_context(self, *, build_plan, detect_result,
                           inputs: UserInputs, project_dir: Path | None) -> dict[str, object]: ...
```

**BL-015 (v0.5 방향) 리팩토링의 핵심**: Dockerfile의 스택별 동적 힌트(JVM의 `has_gradle_dir`, Python의 `venv_path` 등)는 `dockerfile_context()`가 `project_dir`을 직접 관찰해 결정합니다. `DockerfileGenerator`는 스택 중립 facade로, 이미지 allowlist 검증과 주입 방어(`_validate_command`)만 담당합니다.

### 4.2 Validator 규칙 — `@register_rule(scope)`

`scripts/validators/registry.py`.

```python
RuleScope = Literal["container", "pod_spec", "service", "statefulset", "manifest_set"]

@register_rule("container")
def rule_sec001(c: dict, *, pod_sc: dict | None = None, **_) -> list[CheckResult]:
    ...
```

- 규칙 함수는 `list[CheckResult]`를 반환 (빈 리스트도 OK).
- `CheckResult.level`은 `PASS` / `WARN` / `FAIL`.
- `K8sValidator`는 scope별 dispatch (`run_rules("container", container_dict, pod_sc=...)`).
- 새 scope가 필요하면 `registry.py`의 `_registry` dict와 `RuleScope` Literal에 추가.
- 규칙 등록 트리거는 `scripts/validators/rules/__init__.py`의 import 라인 한 줄. 새 파일 추가 시 여기에도 추가해야 로드됩니다.

Exit code는 counts로 결정 (`validators/core.py:_compute_exit_code`):

| counts | exit_code | 의미 |
|--------|-----------|-----|
| fail=0, warn=0 | 0 | 전부 PASS |
| fail>0 | 1 | 수정 필수 |
| fail=0, warn>0 | 2 | soft-success (CI는 경고 로깅 후 계속) |

### 4.3 3계층 설정 — `ConfigLoader`

`scripts/config_loader.py`.

우선순위 (앞이 뒤를 덮어씀):

```
프로젝트 ./.devflow-k8s-deploy.yml
  > 조직 ~/.claude/devflow-k8s-deploy.yml
  > 내장 기본값 (scripts/_shared/defaults.py)
```

- **dict는 deep merge**, **scalar/list는 overwrite**.
- YAML 파싱/크기 초과는 예외가 아닌 `ResolvedConfig.warnings`(한국어)로 기록하고 해당 계층만 무시.
- `ClusterConfig`는 `resolve_cluster_config()`로 별도 해석 — `preset: orbstack` → `{storage_class: local-path, network_policy: true}`. scalar로 오는 경우(`cluster: foo`)도 `isinstance(dict)` 가드로 방어.
- `cluster.preset` 미설정 시 현재는 `orbstack` fallback. 새 preset은 `BUILTIN_CLUSTER_PRESETS` dict에 추가.

### 4.4 `AtomicWriter` — 원자적 파일 쓰기

`scripts/atomic_writer.py`.

- STEP 3에서 모든 생성 파일은 **tmp 디렉토리에 staging**.
- STEP 4 검증이 모두 통과한 경우에만 STEP 5에서 `commit()` 호출 → 최종 경로로 rename.
- 실패/bail-out 시 `rollback()` 또는 자동 정리.
- 목적: 검증 실패 시 부분 산출물이 `k8s-output/`에 남아 혼란 주는 것을 방지.

### 4.5 `retry_loop` — STEP 4 재시도

`scripts/pipeline/retry_loop.py`.

- `retry_with_fix(operation, success_predicate, fix_attempt, max_attempts=3)` 일반화.
- v0.4.0 현재 `_fix_k8s_failures` / `_fix_dry_run_failures`는 **항상 `FixOutcome(applied=False)`를 반환하는 스텁** — 즉시 bail-out 경로로 빠짐.
- **BL-002**(v0.5 예정): 이 스텁을 실제 LLM 기반 수정 루프로 교체 예정. 이미 retry 인프라는 3회 돌 준비가 되어 있음.

### 4.6 보안 방어층 — `_shared/`

| 모듈 | 책임 |
|------|------|
| `image_ref.py` | OCI ref allowlist regex, `latest` 태그 거부 |
| `text_safety.py` | `reject_unsafe_chars` — 개행/NUL/제어문자 차단 (Dockerfile·YAML 주입 방어) |
| `fileio.py` | `read_text_limited` — 크기 제한, `check_yaml_refs` — YAML alias 폭탄 방어, `is_within` — path traversal 방어 |
| `errors.py` | 도메인 예외 계층 (`InvalidImageError`, `UnsupportedStackError`, `MalformedManifestError`, `UserAbort`, `BailOutError` 등) |

**새 기능을 만들 때는 반드시 이 네 가지를 먼저 확인**:
1. 외부 문자열을 템플릿/YAML에 주입? → `reject_unsafe_chars`
2. 이미지 참조? → `validate_image_reference`
3. 파일 경로를 사용자 입력에서? → `is_within`
4. 외부 YAML? → `check_yaml_refs` + `read_text_limited`

---

## 5. 개발 환경 & 워크플로우

### 5.1 로컬 셋업

```bash
git clone https://github.com/bluejayA/devflow-k8s-deploy
cd devflow-k8s-deploy
uv sync --all-extras

uv run pytest -v               # 695 tests
uv run ruff check scripts/ tests/
uv run ruff format scripts/ tests/ --check
uv run mypy scripts/           # mypy strict
```

- Python **3.11+** 고정 (`pyproject.toml`).
- `mypy strict` clean은 **머지 조건**. 변경 코드에 `Any` 남기지 말 것.
- ruff rules: `E, F, I, UP, B, ANN` (ANN401만 ignore).

### 5.2 개발 방법론 — AIDLC devflow (필수)

이 프로젝트는 aidlc-devflow 플러그인으로 개발됐고, 이어서 개발할 때도 동일한 흐름을 권장합니다.

| 상황 | 진입 스킬 |
|------|-----------|
| 새 기능/서비스 | `/aidlc:aidlc-using-devflow` |
| 단일 버그 수정 | TDD + `aidlc:aidlc-verification-before-completion` |
| 원인 불명 오류 | `/aidlc:aidlc-systematic-debugging` |

devflow 규칙 (CLAUDE.md에서 승격):

- **A/B 게이팅**: 사용자가 명시적으로 B(다음 단계)를 선택하기 전까지 다음 스테이지로 진행 금지.
- **세션 재개**: `devflow-docs/devflow-state.md`가 있으면 먼저 재개 여부를 묻는다 (현재 `.gitignore` 처리됨).
- **TDD Iron Law**: 실패 테스트 없이 프로덕션 코드 작성 금지.
- **외부 리뷰 게이트**: CONSTRUCTION 완료 후 `/codex:review` 또는 `/codex:adversarial-review` 필수. 지금까지 Codex 리뷰가 실제로 P1/P2 결함을 잡아낸 사례가 다수 (v0.4.0 릴리즈 노트 참조).
- **승인 없는 `git push` 금지**.

### 5.3 테스트 전략

695 tests가 이렇게 나뉩니다:

| 레이어 | 위치 | 역할 |
|--------|------|------|
| 단위 | `tests/test_*.py` | 컴포넌트별 isolation 테스트. MagicMock + frozen dataclass |
| 스택 | `tests/stacks/` | `JvmStackModule` 감지/빌드/프로브 |
| 스냅샷 | `tests/snapshots/bl015/` | Dockerfile **byte-identical** 골든 4종 (BL-015 불변식) |
| 통합 | `tests/integration/` | `test_e2e_smoke.py` + `test_boundary_allowlist.py` |
| 회귀 | `test_v0_2_0_runtime_fixes.py`, `test_codex_p1_p2_fixes.py`, `test_dockerfile_regression_bl015.py`, `test_dockerfile_v0_1_1_patches.py` | 과거 결함 재발 방지 |

**스냅샷 규칙**: `tests/snapshots/bl015/*.Dockerfile`은 의도적 템플릿 변경이 있을 때만 갱신. 실수로 다시 빌드된 결과를 커밋하면 JVM Dockerfile 불변식이 깨집니다.

---

## 6. 확장 가이드

### 6.1 새 스택 추가 (예: BL-001 Go)

1. `scripts/stacks/go.py` 작성 — `StackModule` Protocol 구현.
   - `name = "go"`, `template_name = "go"`.
   - `detect()` — `go.mod` 존재 시 `StackDetectResult` 반환, 아니면 `None`.
   - `build_plan()` — multi-stage (builder=`golang:1.22-alpine`, runner=`gcr.io/distroless/static` 등). `latest` 태그 금지.
   - `probe_plan()` — 기본 TCP probe (HTTP 프레임워크 감지 로직은 선택).
   - `defaults(hint)` — Go는 JVM보다 메모리 훨씬 작게. `writable_paths` 최소화 (distroless면 빈 리스트).
   - `artifact_locator()` — `/app/bin/<name>` 등.
   - `dockerfile_context()` — 템플릿 변수 dict.
2. `templates/dockerfile/go.tmpl` 작성.
3. `PipelineDependencies.stack_registry`에 `{"go": GoStackModule()}` 추가 (`orchestrator.py`의 조립 부분).
4. `scripts/config_loader.py`의 `_SUPPORTED_STACKS`에 `"go"` 추가, `_KNOWN_UNSUPPORTED_STACKS`에서 제거.
5. `tests/stacks/test_go.py` — detect/build_plan/probe_plan/defaults 단위 테스트.
6. `tests/snapshots/bl001/*.Dockerfile` 골든 등록 + 회귀 테스트 추가.
7. `skills/devflow-k8s-deploy/SKILL.md`의 "지원 스택" 섹션 업데이트.
8. `devflow-docs/backlog.md`에서 BL-001 이동 (Open → 완료).

**DockerfileGenerator는 건드리지 마세요.** BL-015 이후로 스택 중립 facade가 됐습니다. 스택별 차이는 모두 `dockerfile_context()` 안에.

### 6.2 새 validator 규칙 추가

1. 적절한 scope의 기존 모듈 선택 (예: Pod 레벨 규칙이면 `sec.py`, StatefulSet 전용이면 `sts.py`). 새 주제라면 파일 신규 생성.
2. 규칙 함수 작성:
   ```python
   @register_rule("container")
   def rule_sec010(c: dict[str, Any], **_: Any) -> list[CheckResult]:
       ...
       return [CheckResult(rule_id="SEC-010", level=..., container=name,
                           message_ko="...", message_en="...", suggestion="...")]
   ```
3. 새 파일이면 `scripts/validators/rules/__init__.py`의 import 라인에 추가 (이게 등록 트리거).
4. 단위 테스트 작성 — `tests/test_validate_k8s.py`나 주제별 파일.
5. README의 "Exit Code 가이드"에 영향이 있으면(FAIL 추가) 문서 갱신.

### 6.3 새 cluster preset 추가

`scripts/config_loader.py`의 `BUILTIN_CLUSTER_PRESETS` dict에 추가:

```python
BUILTIN_CLUSTER_PRESETS: dict[str, dict[str, object]] = {
    "orbstack": {"storage_class": "local-path", "network_policy": True},
    "eks":      {"storage_class": "gp3",        "network_policy": True},
    "gke":      {"storage_class": "standard-rwo", "network_policy": True},
}
```

`.devflow-k8s-deploy.yml`에서 `cluster.preset: eks`로 선택. 사용자가 `storage_class` / `network_policy`를 같은 섹션에서 직접 override하는 것도 가능 (현재 동작 유지).

---

## 7. 릴리즈 프로세스

현재까지의 패턴 (v0.1.0 ~ v0.4.0):

1. **backlog에서 작업 선택** — `devflow-docs/backlog.md`의 Next 섹션에서 1~2건.
2. **AIDLC devflow 진입** — `/aidlc:aidlc-using-devflow`.
   - greenfield 아님 → brownfield 경로.
   - workflow-plan에서 application-design/units-generation은 대부분 skip (설계가 대화에서 확정).
3. **TDD로 구현** — `/aidlc:aidlc-test-driven-development` + `verification-before-completion`.
4. **머지 전 게이트**:
   - `uv run pytest -v` → 전부 green
   - `uv run ruff check scripts/ tests/` → clean
   - `uv run mypy scripts/` → strict clean
   - `/codex:review` 또는 `/codex:adversarial-review` 실행 → 반환된 P1/P2 전부 반영 후 재리뷰
5. **PR 생성** — 제목에 BL ID + 한 줄. 본문은 변경 요약 + 테스트 증거.
6. **머지 후**:
   - `plugin.json` / `pyproject.toml` / SKILL.md의 version bump
   - `devflow-docs/backlog.md` 업데이트 (Open → 완료 섹션 이동, PR 번호 + 완료일 기록)
   - README의 변경사항 섹션 추가
   - `devflow-docs/release/` 에 릴리즈 노트 (v0.1.0은 템플릿)
7. **태그 + GitHub Release** — `git tag v0.X.Y` + `gh release create`.
8. **devflow-marketplace revision 업데이트** — 상위 마켓플레이스 레포 push.

**Codex 리뷰는 건너뛰지 말 것** — v0.2.0의 6건 런타임 결함, v0.4.0의 scalar cluster AttributeError 등 모두 Codex가 사전에 잡은 사례.

---

## 8. 현재 백로그 (2026-04-23 기준)

`devflow-docs/backlog.md`가 원천 — 여기 요약만 둡니다.

**Next (착수 가능)**
- **BL-001** Go 스택 지원 — BL-015 완료로 Protocol 경계 정리됨
- **BL-002** auto-fix 루프 — retry_loop 인프라 준비됨, `_fix_*` 스텁만 구현체로 교체하면 됨
- **BL-005** PodDisruptionBudget / topologySpreadConstraints

**Open**
- BL-006 Python / BL-007 React (스택)
- BL-008 Helm chart / BL-009 프리셋 프로파일 (DX)
- BL-010 CIS Kubernetes Benchmark 매핑 (검증)
- BL-011 중첩 multi-module / BL-012 stateful AST 감지 / BL-013 runAsUser 커스텀 / BL-014 Ktor·Micronaut HTTP probe (JVM 정확도)
- BL-016 SKILL.md STEP 4-1 ↔ orchestrator 검증 경로 drift (문서 일관성)

---

## 9. 자주 헷갈리는 것들

### "SKILL.md랑 orchestrator 둘 중 누가 진짜인가?"

**둘 다**. SKILL.md는 Claude가 읽고 사용자와 한국어 대화를 진행하는 스크립트, orchestrator는 실제 파일 생성을 하는 Python. 이상적으로는 SKILL.md가 orchestrator CLI를 호출하고 결과를 요약해 전달. 현재 v0.4.0 기준 SKILL.md STEP 4-1 설명과 실제 orchestrator 검증 경로가 살짝 어긋나 있음 → **BL-016**.

### "왜 `stack_registry`가 `PipelineDependencies`에 있지?"

BL-015 이전에는 `DockerfileGenerator`가 스택 문자열로 분기했는데, BL-015에서 Protocol 경계로 옮기며 orchestrator가 `analysis.stack`(예: `"jvm"`)을 키로 registry에서 `StackModule` 인스턴스를 룩업해서 `DockerfileGenerator.generate(stack_module=...)`로 주입하는 구조로 바뀌었습니다. 새 스택 추가가 한 줄 등록으로 끝나는 이유.

### "테스트 695개 전부 실행하는 데 얼마나 걸리나?"

로컬 M 시리즈 Mac 기준 **약 10~15초**. `tests/integration/test_e2e_smoke.py`가 가장 오래 걸리지만 여전히 초 단위. 느려지면 병렬화보다 fixture 공유를 먼저 의심.

### "auto-fix는 왜 아직 없나?"

`retry_loop` 자체는 3회 돌 준비가 돼 있는데, `_fix_k8s_failures` / `_fix_dry_run_failures`가 항상 `applied=False`를 반환해 즉시 bail-out. BL-002에서 실제 LLM 호출 기반 수정 로직으로 교체 예정. 현재 UX는 "검증 실패 → troubleshoot.md + 한국어 사유 안내 → 수동 수정".

### "Dockerfile에 `latest` 썼더니 왜 터지나?"

`scripts/_shared/image_ref.py`의 OCI allowlist regex가 `latest`를 명시 거부합니다 (F-23). 이미지 태그는 semver 또는 digest 필수. 테스트는 `test_dockerfile_generator.py`와 `test_v0_2_0_runtime_fixes.py`에 있음.

### "`.devflow-k8s-deploy.yml`을 어디서 관리하나?"

프로젝트 루트에 커밋하는 게 기본(팀 공유). 조직 기본값은 `~/.claude/devflow-k8s-deploy.yml` — 커밋 대상 아님. 샘플은 `.devflow-k8s-deploy.yml.sample` 참조. 시크릿 들어가면 안 되지만, 혹시 `image.repository`에 사내 레지스트리 이름이 민감하면 `.gitignore` 처리하고 sample만 커밋.

---

## 10. 참고 문서 맵

| 문서 | 용도 |
|------|------|
| [README.md](../README.md) | 플러그인 **사용자** readme |
| `skills/devflow-k8s-deploy/SKILL.md` | Claude가 읽는 **스킬 지시문** |
| `skills/devflow-k8s-deploy/references/help-catalog.md` | STEP 1 "?" 도움말 원본 |
| `skills/devflow-k8s-deploy/references/roadmap.md` | 로드맵 요약 |
| `devflow-docs/inception/workflow-plan.md` | 가장 최근(BL-003/004) workflow 결정 |
| `devflow-docs/inception/requirements.md` | F-XX / NFR-XX 요구사항 원본 |
| `devflow-docs/inception/user-stories.md` | INVEST 사용자 스토리 |
| `devflow-docs/inception/workspace.md` | brownfield 분석 |
| `devflow-docs/construction/bl003-bl004/code-plan.md` | 최근 CONSTRUCTION 계획 |
| `devflow-docs/release/v0.1.0-release-notes.md` | 초기 여정 회고 (읽으면 설계 결정의 맥락이 잡힘) |
| `devflow-docs/backlog.md` | **다음에 뭘 할지** — 가장 자주 보게 될 문서 |
| `devflow-docs/audit.md`, `devflow-docs/devflow-audit.md` | 초기 품질 감사 로그 |

---

## 11. 마지막 팁

- **처음 이어받는다면 BL-016(문서 drift)을 warm-up 과제로** 추천. 범위가 작고, SKILL.md와 orchestrator를 모두 읽게 되어 전체 그림이 빨리 잡힙니다.
- **BL-001(Go 스택)은 가장 큰 검증** — `StackModule` Protocol이 실제로 JVM 외에도 잘 동작하는지 확인하는 과제. 여기서 Protocol에 부족한 게 발견되면 BL-015 후속으로 보완.
- **695 tests 중 snapshot 실패는 "의도한 변경"일 때만 갱신.** 그냥 새 결과를 커밋하는 순간 JVM Dockerfile 불변식이 무너집니다.
- **새 기능 넣기 전에 `README.md` / `SKILL.md`의 "하지 않는 것" 목록을 다시 읽어보세요.** create-only 경계를 지키는 것이 이 프로젝트의 정체성.
