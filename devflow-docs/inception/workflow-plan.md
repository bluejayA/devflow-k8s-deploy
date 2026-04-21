# Workflow Plan

**Timestamp**: 2026-04-17T00:10:00+09:00
**Selected Approach**: A안 (설계 우선) — 2026-04-17 사용자 승인

---

## Approaches Considered

### A안: 설계 우선 (권장)
- 포함 스테이지: application-design → units-generation → code-generation → build-and-test
- 깊이: application-design Comprehensive / units-generation Standard / code-generation Standard / build-and-test Standard
- 적합: 컴포넌트 간 인터페이스 계약(StackModule, summary.json, exit code)이 핵심인 프로젝트. NFR Design으로 보안·결정론성·atomic write 설계를 코드 전에 확정
- 주의: INCEPTION이 길어지나, 컴포넌트 간 불일치 리스크를 사전에 제거

### B안: 유닛 직행
- 포함 스테이지: units-generation → code-generation → build-and-test (application-design 스킵)
- 깊이: units-generation Standard / code-generation Standard / build-and-test Standard
- 적합: requirements.md의 F-90~F-94 확장성 제약이 이미 구조를 결정했으므로, 설계 없이 유닛 분해 후 바로 구현 가능하다고 판단할 때
- 주의: 컴포넌트 간 인터페이스(StackModule ↔ SKILL.md ↔ validate_k8s.py) 정합성을 코드 단계에서 잡아야 함

### C안: 빠른 구현
- 포함 스테이지: code-generation → build-and-test (application-design + units-generation 스킵)
- 깊이: code-generation Standard / build-and-test Standard
- 적합: 요구사항이 충분히 상세하여 설계·분해 없이 TDD로 바로 구현 가능하다고 판단할 때
- 주의: 6개 이상 독립 컴포넌트를 단일 code-generation 세션에서 처리 — 컨텍스트 크기·순서 의존성 리스크

---

## Workflow Visualization (A안 기준)

```
INCEPTION
  ✅ workspace-detection (완료)
  ✅ brainstorming (완료, side-skill)
  ✅ requirements-analysis (완료)
  ✅ user-stories (완료)
  ✅ nfr-requirements (완료)
  ✅ workflow-planning (현재)
  ➡ application-design [Comprehensive]

CONSTRUCTION
  ➡ units-generation [Standard]
  ➡ code-generation [Standard] (TDD protocol 적용)
  ➡ build-and-test [Standard]
```

---

## Approved Stages

### PRE-PLANNING
- user-stories: included — Comprehensive complexity 자동 포함. 22 stories 생성 완료
- nfr-requirements: included — Comprehensive complexity 자동 포함. 17 NFR 항목 수집 완료

### CONSTRUCTION
- application-design: included — 컴포넌트 간 인터페이스 계약(StackModule, summary.json, config schema)이 핵심. NFR Design 포함 (Comprehensive + nfr-requirements.md 존재)
- units-generation: included — 6개 이상 독립 컴포넌트 존재, 의존성 순서 관리 필요
- code-generation: included — always
- build-and-test: included — always

## Stage Depths
- application-design: Comprehensive (NFR Design 활성화)
- units-generation: Standard
- code-generation: Standard (TDD protocol 적용 — _shared/tdd-protocol.md)
- build-and-test: Standard

---

## Change Log

- 2026-04-17T00:10:00+09:00 — 최초 생성. 3개 접근법 (A: 설계 우선, B: 유닛 직행, C: 빠른 구현). A안 권장
- 2026-04-17 — 사용자가 A안(설계 우선) 선택. application-design(Comprehensive, NFR Design 활성) → units-generation(Standard) → code-generation(Standard, TDD) → build-and-test(Standard) 확정
