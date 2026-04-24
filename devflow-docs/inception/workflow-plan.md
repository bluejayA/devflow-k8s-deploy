# Workflow Plan

**Timestamp**: 2026-04-24T11:30:00+09:00
**Selected Approach**: A안 — 점진적 TDD, Strangler 패턴, 9 Phase (2026-04-24 승인)

## Approaches Considered

### A안 (권장) — 점진적 TDD — 불변식 우선 Strangler

- **포함 스테이지**: code-generation, build-and-test
- **깊이**: code-generation=Standard (TDD strict), build-and-test=Standard
- **적합**: Brownfield + 기존 패턴 재현 작업. BL-015 Protocol 재사용이라 신규 설계 도출 가치 낮음. F-33 요구사항이 구현 위치(파일 경로/라인)까지 구조화되어 application-design 단계가 중복 위험
- **주의**: Protocol 확장(F-24) 적용 시점을 Go 구현 착수 *전*에 배치해야 기존 JVM 테스트가 한 번에 호환 레이어로 전환됨. 마이그레이션을 Go 구현과 섞으면 회귀 원인 특정 곤란

#### 실행 순서 (9 Phase, 코드/테스트 페어링)

**Phase 1 — 불변식 안전망 확보 (JVM 골든 락)**
- NFR-04 (d-jvm) 신규: JVM `deployment.yaml` / `service.yaml` / `serviceaccount.yaml` 골든 스냅샷 테스트 작성 → 이후 refactor 안전망
- NFR-04 (o): `StackDetectResult(...)` 기존 호출부 호환성 테스트(cmd_candidates 미지정 시 `[]` 기본값)
- **성공 기준**: 695 + 신규 3종 골든 = 698 passing

**Phase 2 — 타입/예외 확장 (영향 좁은 데이터 구조부터)**
- F-25: `StackDetectResult.cmd_candidates` 필드 추가 (`field(default_factory=list)`)
- F-30: `ResourceDefaults.run_as_user` 필드 추가 — JvmStackModule.defaults()에 `run_as_user=1000` 주입
- F-20 / F-26: `GoDetectionError` + `GoBuildPlanError` 예외 클래스
- **성공 기준**: 타입 확장 후 698 passing 유지 + 신규 예외 단위 테스트

**Phase 3 — 기존 manifest 하드코딩 제거 (JVM 불변 확인)**
- F-31: `generate_deployment()` / `generate_statefulset()` runAsUser/runAsGroup/fsGroup 동적화 (`defaults.run_as_user` 기반) — JVM 기존 1000 그대로 렌더
- F-32: writable_paths 동적화 (JVM 2개 `/tmp`+`/var/log` 유지)
- **성공 기준**: Phase 1의 JVM 골든 3종 byte-identical 유지 + 695 passing

**Phase 4 — Protocol 확장 (F-24) + 기존 JVM 호출부 전수 마이그레이션**
- F-24: `scripts/stacks/base.py` `StackModule.build_plan` 시그니처 변경 (`*, inputs: UserInputs`)
- `JvmStackModule.build_plan` 구현체 시그니처 매칭 (inputs 수신, 내부 무시)
- 호출부 전수 수정 — 체크리스트 (F-24에 명시):
  - `scripts/project_analyzer.py` 호출 2곳
  - `tests/stacks/test_jvm.py` 외 `build_plan(` 호출 tests (grep 전수)
  - `tests/test_dockerfile_v0_1_1_patches.py` 포함 임시 JVM 인스턴스 호출부
- NFR-04 (j): JVM build_plan이 inputs 키워드 받아도 기존 골든 동일
- **성공 기준**: 698 passing + Protocol 확장 완료

**Phase 5 — Analyzer/Pipeline 통합 확장 (F-27)**
- F-27: `ProjectAnalyzer.analyze(project_dir, *, inputs: UserInputs)` 시그니처 확장
- `_apply_stack_overrides(detect_result, stack_config)` 헬퍼 추가 (config entrypoint override 적용 지점)
- `SkillPipeline._analyze_project_step2`에서 `analyzer.analyze(project_dir, inputs=inputs)` 호출 수정
- probe_plan에 `stack.go.probe.path` override 적용 로직 (Analyzer가 ProbeConfig 결과의 path 치환)
- F-33: `ConfigLoader`에 `stack.go.entrypoint` / `stack.go.probe.path` 파싱 추가
- **성공 기준**: 698 passing + Analyzer inputs 체인 검증 테스트 (NFR-04 (k))

**Phase 6 — Go 스택 신규 모듈 구현**
- F-23: `_DEFAULT_GO_VERSION = "1.22"` 상수
- F-01~F-10: `scripts/stacks/go.py::GoStackModule` 전체 구현 (Protocol 7 메서드 + ClassVar)
- F-21: `_parse_go_mod` 헬퍼 (defusedxml 대신 정규식)
- F-22: `_collect_cmd_candidates` 헬퍼 (symlink escape 방어)
- F-28: `_build_multi_cmd_error_message` 헬퍼 (상위 10개 + 생략 요약)
- F-29: `scripts/_shared/text_safety.py::validate_go_entrypoint` 헬퍼 (shell 주입 방어)
- **TDD 전략**: 각 메서드마다 RED(실패 테스트) → GREEN(최소 구현) → REFACTOR. NFR-04 (a)(b)(c)(e)(f)(g)(h)(i)(n)(p)(q) 케이스 페어링
- **성공 기준**: 698 + Go 단위 테스트 신규 (예상 15~20개)

**Phase 7 — Dockerfile 템플릿 + 레지스트리 통합**
- F-11~F-14: `templates/dockerfile/go.tmpl` 작성 (2-stage multi-stage, distroless nonroot)
- NFR-04 (d): Go Dockerfile 골든 스냅샷
- F-15: `PipelineDependencies.stack_registry`에 `GoStackModule()` 등록
- F-16: `ProjectAnalyzer._detect_stack` auto-선택 순회 로직 (JVM 우선 → Go)
- F-17: 전 스택 detect 실패 시 기존 에러 플로우
- **성공 기준**: Go 프로젝트 fixture로 orchestrator 실행 → Dockerfile + deployment.yaml 생성 성공

**Phase 8 — 통합 회귀 + 정합성 테스트**
- NFR-04 (l) / (m): config override 경로 테스트 (entrypoint + probe.path)
- NFR-04 (r) / (s): UID 정합성 / writable_paths 정합성 (생성된 deployment가 defaults와 일치)
- 전체 695+신규 테스트 통과, ruff clean, mypy clean (있다면)
- **성공 기준**: 720+ passing, NFR-EXT-01(JVM 하드코딩 0건) grep 검증

**Phase 9 — 외부 리뷰 게이트**
- `/codex:review` 또는 `/codex:adversarial-review` 실행 (CONSTRUCTION 완료 후 필수 게이트 — CLAUDE.md 규칙)
- 리뷰 P1 이슈 반영 후 PR 생성

#### 불변식 유지 전략 (NFR-02 핵심)

- **Phase 1**에서 JVM 매니페스트 골든을 *먼저* 락다운 → 이후 Phase 3/4/5의 refactor가 골든 위반하면 즉시 fail
- Phase 3/4/5는 **JVM 영향만 있는 단계** → 각 phase 완료 후 `pytest` 전체 실행으로 JVM 골든 불변 확인
- Phase 6~7의 Go 구현은 JVM과 격리된 신규 파일 (scripts/stacks/go.py, templates/dockerfile/go.tmpl) → 교차 영향 최소

#### Protocol 확장(F-24) 적용 시점

- **Phase 4에 단일 PR로 원자적 적용** — Go 구현(Phase 6) 직전
- Go 구현부터 시작하면 Protocol 확장 없이 build_plan 호출 불가 → 순서 역전 금지
- 기존 JVM 테스트 마이그레이션도 Phase 4에 포함 → 회귀 원인 특정 용이

#### 위험 요소

- **R1**: Phase 4 Protocol 변경 시 `build_plan(` 호출부 누락 → mypy/런타임 에러. 완화: F-24 체크리스트 grep 전수 조사
- **R2**: Phase 3 manifest 하드코딩 제거 시 StatefulSet(BL-003)도 동반 변경 — 골든 스냅샷 있음에도 간과 가능. 완화: generate_statefulset도 NFR-04 (r)(s)에 포함
- **R3**: ConfigLoader stack.go 파싱이 기존 stack.forced_stack와 충돌 가능성. 완화: A-07 + F-33 명시로 네임스페이스 분리
- **R4**: distroless:nonroot 이미지 pull 실패 (네트워크) → 통합 테스트 환경 의존. 완화: 단위 테스트는 이미지 실행 없이 Dockerfile 문자열 렌더만 검증

#### PR 전략

- **PR 1**: Phase 1~5 (불변식 refactor — JVM 영향만)
- **PR 2**: Phase 6~8 (Go 스택 신규 + 통합)
- 두 PR 분리 이유: 리뷰 단위 명확화 + 불변식 위반 원인 격리

---

### B안 — 설계 우선 — application-design 포함

- **포함 스테이지**: application-design, code-generation, build-and-test
- **깊이**: application-design=Standard, code-generation=Standard, build-and-test=Standard
- **적합**: Protocol 확장의 파급 효과를 ADR/diagram으로 사전 문서화하고 싶을 때. Python/React 추가 스택 확장 로드맵을 이번 기회에 명시화
- **주의**: F-33 요구사항이 이미 구현 위치(파일:라인)까지 구조화돼 application-design 산출물과 중복 가능성. 문서 작성 overhead가 실제 구현 시간을 초과할 수 있음

#### 추가 스테이지

- **application-design (Standard)**: `StackModule Protocol v2` 구조도 + `ProjectAnalyzer inputs 흐름 시퀀스` + Python/React 스택 확장 선언 — 산출물 `application-design.md`
- 이후 Phase 1~9는 A안과 동일

#### 장단점

- **장점**: Protocol 진화 방향(BL-017, 미래 Python/React) 문서화로 설계 안정성 ↑. 신규 기여자 onboarding에 도움
- **단점**: requirements.md F-번호와 중복, ~2시간 추가 overhead, 이 규모의 단일 스택 추가엔 과함

---

## Approved Stages

### PRE-PLANNING
- user-stories: skipped — BL-001은 단일 actor(Go 배포자)로 수렴, F-번호가 기능 측면 충분 구조화
- nfr-requirements: skipped — requirements.md 내 NFR 8개로 충분, 추가 항목 부재

### CONSTRUCTION
- application-design: skipped — Brownfield + 기존 패턴 재현, 신규 설계 없음, F-33 구현 위치까지 구조화됨
- units-generation: skipped — 단일 기능 추가(Go 스택 모듈), 유닛 분해 가치 낮음
- code-generation: included — always
- build-and-test: included — always

## Stage Depths
- application-design: skipped
- units-generation: skipped
- code-generation: Standard (TDD protocol 적용 — _shared/tdd-protocol.md). Phase 1~9 순서대로 RED-GREEN-REFACTOR
- build-and-test: Standard

## Workflow Visualization (A안 기준)

```
INCEPTION
  ✅ workspace-detection (완료)
  ✅ requirements-analysis (완료, Codex P1+P2 반영)
  ⏭ pre-planning (스킵 — Standard C)
  🔵 workflow-planning (현재)
  ⏭ application-design — 스킵 (A안 기준)

CONSTRUCTION
  ⏭ units-generation — 스킵 (A안 기준)
  ➡ code-generation [Standard, TDD strict]
     ├─ Phase 1: JVM 골든 락 (안전망)
     ├─ Phase 2: 타입/예외 확장
     ├─ Phase 3: manifest 하드코딩 제거
     ├─ Phase 4: Protocol F-24 확장 + JVM 호출부 마이그레이션
     ├─ Phase 5: Analyzer/Pipeline 통합
     ├─ Phase 6: GoStackModule 구현
     ├─ Phase 7: Dockerfile 템플릿 + 레지스트리
     └─ Phase 8: 통합 회귀
  ➡ build-and-test [Standard]
     └─ Phase 9: 외부 리뷰 게이트 (/codex:review)

FINISHING
  ➡ aidlc-finishing-a-development-branch — PR 2건 생성 (PR 1: Phase 1-5 / PR 2: Phase 6-8)
```
