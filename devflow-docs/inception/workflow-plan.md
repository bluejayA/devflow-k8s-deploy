# Workflow Plan

**Timestamp**: 2026-05-13T23:30:00Z
**Selected Approach**: A안 (단일 PR + 내부 3-Phase 명시) — 2026-05-13 사용자 확정. BL-001/017 패턴 일관성 + B안 PR1 placeholder 부담 회피.
**Predecessor Patterns**: BL-001/017 (Go 스택 — 모두 단일 PR + 내부 Phase 명시 패턴 채택, Codex 2~3 라운드)

## Approaches Considered

### A안) 단일 PR + 내부 3-Phase 명시 (권장)

- **포함 스테이지**: application-design (Standard, NFR Design은 nfr-requirements.md 부재로 OFF) → code-generation (Standard, TDD) → build-and-test (Standard) → 단일 PR
- **내부 Phase 구조** (PR 내부 commit/section 단위로 명시):
  - **Phase α (감지 layer)**: F-01~F-12 + F-06-1 — `scripts/stacks/python.py` 신규 + 매니페스트 파서(pyproject TOML + requirements.txt root only) + `_detect_python_framework` 4단계 + `_match_frameworks` + `requires-python` 파서 + symlink/IO 가드. 단위 테스트 ≥ 15건
  - **Phase β (빌드 layer)**: F-13~F-17 + F-19 — `templates/dockerfile/python.tmpl` Jinja2 multi-stage + `uv sync` lockfile 분기 + `dockerfile_build_context` + probe path 정책 + `.devflow-k8s-deploy.yml` schema 확장. 단위/통합 테스트 ≥ 10건
  - **Phase γ (실행 layer)**: F-20~F-24 (F-20-1 3조건 통합) + entrypoint 휴리스틱 + dependency-conservative 정책 + gap rationale. 단위 테스트 ≥ 8건
  - **Phase δ (통합/문서)**: F-02 (config_loader), F-03 (orchestrator DI), F-04 (project_analyzer auto-detect), F-26 (rationale stack-aware), F-27 (SKILL.md), F-28/F-29 (text_safety 회귀 가드). 통합 테스트 + 회귀 가드 ≥ 5건
- **목표 tests**: 928 → **≥ 960** (NFR-2)
- **외부 리뷰**: `/codex:review` 1차 + 필요 시 `agent-council` deep (BL-017 패턴 — layered_external_review)
- **적합**: BL-017 동급 작업 크기·미러링 비율 높음·review burden 단일이 효율적
- **주의**: 단일 PR이 commit ~10개로 커질 수 있음. 내부 Phase commit 분리로 reviewer 가독성 확보 필수

### B안) Phase 분리 3 PR

- **포함 스테이지**: application-design (Standard) → 3회 (code-generation + build-and-test) → 3 PR
  - **PR1 (감지 layer)**: A안 Phase α + α를 wire-up하기 위한 최소 통합 (`PythonStackModule.detect`만 노출, build/probe는 placeholder/raise NotImplementedError)
  - **PR2 (빌드 layer)**: A안 Phase β + Phase α 활용
  - **PR3 (실행 layer + 통합)**: A안 Phase γ + δ
- **목표 tests**: PR별 +15/+10/+13
- **외부 리뷰**: PR별 `/codex:review` 1회씩
- **적합**: 변경 surface 크게 분산하고 싶을 때 / PR1 머지 후 detect만 dogfooding 가능
- **주의**: NotImplementedError placeholder가 일시적으로 production code에 들어감 → 매니페스트 일관성 검증(F-26)이 PR3까지 미뤄짐. 3 PR review/CI burden 3배. BL-017과 패턴 일관성 약함 (BL-001/017 모두 단일 PR이었음)

## Recommendation

**A안 (단일 PR + 내부 3-Phase 명시)**.

근거:
1. **선례 일관성** — BL-001 (Phase 1-9 + Codex R2) / BL-017 (Phase 1-9 + Codex 2 라운드) 모두 단일 PR + 내부 Phase 패턴으로 성공. BL-006은 동일 카테고리 작업 (framework 감지 + 정책 미러링) → 패턴 일관 시 reviewer 인지 비용 감소.
2. **PR1 placeholder 부담** — B안 PR1은 `build_plan`/`probe_plan`에 NotImplementedError를 두어야 함 (PythonStackModule이 Protocol을 만족하지 않으면 orchestrator DI 등록도 못함 → 미등록 상태로 PR1 머지하면 dogfooding 가치도 사라짐). 단일 PR이면 이 문제가 원천 차단.
3. **3-layer 분리는 PR이 아닌 commit 단위로 표현** — Phase α/β/γ/δ를 각각 1~3 commit으로 분리하면 review 가독성은 B안과 유사 + lockfile 분기/3조건 통합 정책처럼 layer-횡단 결정이 단일 diff에서 보임.
4. **외부 리뷰 효율** — Codex/council 호출 비용도 단일.

## Workflow Visualization (A안 기준)

```
INCEPTION
  ✅ workspace-detection
  ✅ requirements-analysis (31 functional / 7 NFR / 0 open Q)
  ✅ workflow-planning (현재)
  ⏭ pre-planning (skipped — C 선택)
  ➡ application-design [Standard] — Sub-OQ SD-1 (entrypoint 추론 알고리즘) 확정

CONSTRUCTION
  ⏭ units-generation — 스킵 (application-design 컴포넌트로 충분, BL-017 동일)
  ➡ code-generation [Standard, TDD] — Phase α → β → γ → δ
  ➡ build-and-test [Standard] — 회귀 928 + 신규 ≥ 31

POST
  ➡ /codex:review 1차 (필수)
  ➡ agent-council deep (선택, layered_external_review 정책)
  ➡ PR + Closes #9
```

## Approved Stages

### PRE-PLANNING
- user-stories: skipped — Pre-Planning gate C 선택. 단일 페르소나(devflow-k8s-deploy 사용자), INVEST 분할 가치 낮음. BL-017과 동일.
- nfr-requirements: skipped — NFR-1~7이 requirements.md에 정량 명시 (테스트 ≥ 31, 928 회귀, 안전 폴백, 이미지 크기, pathlib, rationale, TDD). 별도 nfr-requirements.md 분리 이득 없음.

### CONSTRUCTION
- application-design: included — Sub-OQ SD-1(server entrypoint 추론 휴리스틱 알고리즘) 확정 필요. django wsgi 폴더 식별 + flask/fastapi main vs app 우선순위 + 실패 조건 정의. Standard depth.
- units-generation: skipped — application-design의 컴포넌트 분해로 충분. BL-017 동일.
- code-generation: included — always. TDD protocol (_shared/tdd-protocol.md) 적용. Standard depth.
- build-and-test: included — always. Standard depth.

## Stage Depths

- application-design: Standard (LIST → DETAIL. NFR Design은 nfr-requirements.md 부재로 OFF)
- units-generation: skipped
- code-generation: Standard (TDD RED→GREEN→REFACTOR cycle 강제)
- build-and-test: Standard (회귀 928 tests + 신규 ≥ 31 tests, 통합 smoke test 1회)

## Post-INCEPTION Quality Gates

(orchestrator 외 사용자 정책 — CLAUDE.md 외부 리뷰 게이트)

| Gate | When | Tool | Mandatory |
|------|------|------|-----------|
| 1차 외부 리뷰 | CONSTRUCTION 완료 후 | `/codex:review` | YES |
| 2차 deep 리뷰 | 1차 P2+ 발견 또는 큰 모듈 | `agent-council` (codex+gemini+claude) | 조건부 (layered_external_review) |
| 머지 전 회귀 | 모든 리뷰 PASS 후 | `pytest` (전수) | YES |
