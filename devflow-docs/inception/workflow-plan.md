# Workflow Plan

**Timestamp**: 2026-05-12T18:45:00+09:00
**Ticket**: BL-017 ([#27](https://github.com/bluejayA/devflow-k8s-deploy/issues/27))
**Complexity**: Standard
**Selected Approach**: A안 (직접 구현) + application-design Minimal 포함 (하이브리드)

## Approaches Considered

### A안) 직접 구현 (권장)
- **포함 스테이지**: code-generation, build-and-test
- **스킵 스테이지**: application-design, units-generation
- **깊이**: Standard (TDD 사이클 + Codex 외부 리뷰 게이트)
- **적합**:
  - 단일 모듈 내부 확장 (`scripts/stacks/go.py`). 외부 컴포넌트/Protocol 변경 없음
  - 기존 모범 패턴(`scripts/stacks/jvm.py::_detect_framework_and_version`) 직접 미러링 가능 → 설계 발산 위험 낮음
  - F-02 "Direct dependency wins" 알고리즘이 requirements 단계에서 이미 충분히 정교화됨 (4단계 분기 + fallback)
  - BL-014/BL-001 선례에 따라 외부 리뷰 게이트(Codex)가 ambiguity/ReDoS/false-positive를 충분히 잡아냄
- **주의**:
  - go.mod `require` 블록 텍스트 파서(F-06a)가 신규 — `(...)` 블록 파싱과 라인 단위 require 두 형식 모두 커버 필수
  - 정규식 `\b...(?:/v\d+)?\b` 경계 검증 — `github.com/gin-gonic/ginX` 같은 false-positive 회피 가드 테스트 포함
  - JVM 골든 byte-identical (NFR-4) + Go-generic byte-identical (NFR-5) 회귀 0 보장

### B안) 안전 + 경량 설계 검증
- **포함 스테이지**: application-design (Minimal), code-generation, build-and-test
- **스킵 스테이지**: units-generation
- **깊이**: Standard (application-design은 Minimal)
- **적합**:
  - F-02 알고리즘(direct vs sum 우선순위 + 복수 매치 fallback)을 별도 design 문서로 검토하고 싶을 때
  - BL-006 Python 스택에서 본 패턴을 재활용할 예정이므로 설계 문서가 후속 작업의 참고 자료가 될 수 있음
- **주의**:
  - 설계 표면이 작아(단일 헬퍼 + 단일 메서드 분기) 별도 design 문서의 비용 대비 가치 낮음
  - requirements.md F-02/F-06a가 이미 알고리즘 4단계까지 명세하고 있어 application-design Minimal이 중복 우려

---

## 권장: A안 (직접 구현)

**근거**:
1. **변경 표면이 작음** — 단일 파일(`scripts/stacks/go.py`) 내부에 헬퍼 1개 + 정규식 3개 + 파서 1개 + 메서드 2개 분기 수정. 신규 외부 인터페이스 0건.
2. **기존 모범 패턴 존재** — `scripts/stacks/jvm.py`의 `_detect_framework_and_version` + `_SPRING_BOOT_RE` 패턴을 직접 미러링. 설계 발산 위험 낮음.
3. **Requirements가 이미 정교함** — F-02의 "Direct dependency wins" 4단계 알고리즘 + F-06a 파서 명세 + NFR-6 테스트 13건이 application-design 산출물 수준의 정밀도를 이미 보유.
4. **외부 리뷰 게이트로 충분** — NFR-7의 Codex review 1차 + 필요 시 council 1라운드가 ambiguity/ReDoS/false-positive 검증을 담당. BL-001 Phase 9 R2 사례에서 이미 검증된 운영 방식.

---

## Workflow Visualization (A안 + application-design Minimal 하이브리드)

```
INCEPTION
  ✅ workspace-detection — Brownfield delta (BL-001/018/019/020/021/022 반영)
  ✅ complexity-declaration — Standard
  ✅ requirements-analysis — F:15, NFR:7, A:7, OQ:0
  ⏭ pre-planning — 스킵 (Standard C: 바로 워크플로우)
  ✅ workflow-planning — 현재 단계
  ➡ application-design [Minimal] — 컴포넌트 LIST 수준 (단일 모듈 내부 헬퍼/메서드 책임 분리만 확인)

CONSTRUCTION
  ⏭ units-generation — 스킵 (A안 기준, 단일 unit)
  ➡ code-generation [Standard] — TDD 사이클, phase 분해
  ➡ build-and-test [Standard] — 골든 회귀 + 외부 리뷰 게이트
```

---

## Approved Stages

### PRE-PLANNING
- **user-stories**: skipped — Standard C 선택 (내부 헬퍼 확장, 외부 사용자 페르소나/시나리오 추가 가치 낮음)
- **nfr-requirements**: skipped — Standard C 선택 (requirements.md NFR-1~7이 이미 측정 가능 기준 포함)

### CONSTRUCTION
- **application-design**: included (Minimal) — 사용자 선택. 단일 모듈 내부지만 헬퍼/파서/메서드 책임 분리를 컴포넌트 LIST 수준으로 명시. BL-006 Python 후속에 참고 자료로도 활용 가능
- **units-generation**: skipped — 단일 unit(`scripts/stacks/go.py`)으로 충분, 작업 분해는 phase로 처리
- **code-generation**: included — always
- **build-and-test**: included — always

## Stage Depths

- **application-design**: Minimal (LIST 수준 컴포넌트 책임 분리 — DETAIL 인터페이스 명세는 requirements.md F-02/F-06a로 충분)
- **units-generation**: skipped (n/a)
- **code-generation**: Standard (TDD protocol 적용 — `_shared/tdd-protocol.md`)
- **build-and-test**: Standard (JVM/Go-generic 골든 byte-identical 회귀 가드 + Codex 외부 리뷰 게이트)

## Phase 제안 (code-generation 내부)

A안 채택 시 code-generation을 아래 phase로 분해 권장 (BL-001 사례 미러링):

| Phase | 범위 | TDD 가드 | 산출물 |
|-------|------|---------|--------|
| **P1** | `_parse_go_mod_require` 파서 + 정규식 3종(`_GIN_RE`/`_ECHO_RE`/`_FIBER_RE`) | 파서 라인 형식 2종 + 정규식 매칭/비매칭 + 메이저 버전 호환 | go.py 헬퍼 추가, 단독 테스트 6건 |
| **P2** | `_detect_go_framework` "Direct dependency wins" 4단계 알고리즘 | direct 단일/복수, sum 단일/복수, 파일 없음, symlink escape | 헬퍼 통합, 단위 테스트 6건 |
| **P3** | `GoStackModule.detect/probe_plan` 통합 + framework별 분기 | 4 framework × probe_plan 분기 4건 + Go-generic byte-identical 회귀 | 메서드 수정 |
| **P4** | JVM 골든 byte-identical 회귀 검증 + E2E 회귀 | 기존 골든 4종 + Go 샘플 E2E 회귀 | 검증 완료, 외부 리뷰 게이트 진입 |

총 신규 테스트: 13건+ (NFR-6 충족).

## Branch / Worktree

- 권장 브랜치명: `feature/go-framework-probe-detection`
- 베이스: `main` @ `bc1f9b8` (현재 HEAD, 897 tests passing)
- 워크트리 경로: `.worktrees/feature-go-framework-probe-detection`
