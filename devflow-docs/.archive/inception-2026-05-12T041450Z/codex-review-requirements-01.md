# Codex Review — requirements.md (BL-001)

**Date**: 2026-04-24
**Reviewer**: codex (via codex:codex-rescue subagent)
**Target**: `devflow-docs/inception/requirements.md`
**Verdict**: 조건부 승인 (P1 수정 필요)

## 핵심 요약

- `inputs/config` 전달 경로가 비어 있어 핵심 계약(F-06/F-18/F-19) 일부가 구현 경로상 모순
- F-24 시그니처 확장은 타당하나, `ProjectAnalyzer/SkillPipeline` 인터페이스 변경과 JVM 회귀 검증 범위(manifest byte-identical)가 문서에 충분히 명시되지 않음
- `build_cmd` 문자열 조합 시 shell 주입 위험 / `writable_paths`-manifest 불일치가 우선 보강 포인트

## P1 (Critical)

### 1-1. Req 완결성 — `inputs` 전달 경로 부재
- 근거: `ProjectAnalyzer.analyze()`(project_analyzer.py:220, 305), `orchestrator.py:646`에 `inputs` 전달 계약 없음
- 제안: `ProjectAnalyzer.analyze(..., inputs: UserInputs)`로 시그니처 확장을 요구사항에 명시. `SkillPipeline._analyze_project_step2`에서 전체 inputs 전달 추가

### 1-2. Req 완결성 — config override 책임 경계 미정의
- 근거: F-18 `stack.go.entrypoint`, F-19 `stack.go.probe.path`를 "지원"이라고만 명시. ConfigLoader → Analyzer → StackModule 전달 흐름 없음
- 제안: ConfigLoader가 `stack.go` 구조화 dict를 Analyzer에 전달, Analyzer가 `build_plan/probe_plan` 호출 시 반영하는 흐름 명시

### 2-1. F-24 Protocol 확장 — 마이그레이션 체크리스트 부재
- 근거: `tests/stacks/test_jvm.py:354`, `test_dockerfile_v0_1_1_patches.py:171` 등 기존 JVM 테스트의 build_plan 호출부 migration 필요
- 제안: "호출부 마이그레이션 체크리스트(코드+테스트)"를 요구사항 본문에 별도 항목 추가

### 3-1. A-08 — 우선순위 규칙 F-06과 미연결
- 근거: A-08(ii)는 config 우선이라 했지만 F-06 알고리즘에는 config가 없음
- 제안: `config entrypoint > app_name 매칭 > 단일 후보 > 에러`로 F-06 재정의

### 4-1. 보안 — `build_cmd` shell 주입 위험
- 근거: `app_name`/`entrypoint`를 `go build -o {app_name} {entrypoint}` 문자열에 직접 삽입. `dockerfile_generator.py:86`, `text_safety.py:14` 패턴과 불일치
- 제안: `app_name` DNS-1123 subset 검증 + `entrypoint` 정규화 강제

### 5-1. NFR-04 — F-24 inputs 전달 테스트 누락
- 제안: `SkillPipeline → ProjectAnalyzer → stack.build_plan(inputs=...)` 호출 검증 테스트 필수 추가

### 5-2. NFR-04 — override 경로 테스트 누락
- 제안: `stack.go.entrypoint` / `stack.go.probe.path` override 경로 테스트 필수 승격

## P2 (Important)

### 2-2. NFR-02 범위 — manifest 골든 스냅샷 불일치
- 근거: "JVM Dockerfile + manifest 3종 byte-identical"이라 하지만 실제 골든 검증은 `test_dockerfile_regression_bl015.py` Dockerfile 중심
- 제안: JVM `deployment/service/serviceaccount` 골든 스냅샷 테스트 NFR-04에 추가 또는 NFR-02 범위를 Dockerfile로 한정 명시

### 2-3. Protocol — 단순 스택에 `inputs` 강제는 불필요 결합
- 제안: `inputs`를 optional로 두거나 엔트리포인트 해석 책임을 별도 메서드로 분리하는 대안 명시

### 3-2. A-08 — 루트 우선 선택 근거 기록 없음
- 제안: 선택 근거(왜 루트 main.go가 선택됐는지)를 `gaps` 또는 rationale에 남기는 요구사항 추가

### 3-3. 대규모 모노레포 — 오류 메시지 품질 저하
- 제안: 후보 목록 길이 제한/정렬/요약 규칙(예: 상위 10개 + n개 생략) 명시

### 4-2. 보안 — writable_paths가 deployment manifest에 반영 안됨
- 근거: `Go: writable_paths=["/tmp"]` 목표인데 `deployment.tmpl:75` / `manifest_generator.py:202`가 `/var/log` 고정
- 제안: manifest가 `defaults.writable_paths` 사용하도록 계약 확장 또는 Go에서도 `/var/log` 허용으로 수정

### 4-3. 보안 — UID 정책 충돌 (중요)
- 근거: Dockerfile `USER nonroot` (distroless 65532) vs K8s `runAsUser: 1000`(deployment.tmpl:21) 불일치
- 제안: UID 정책 통일(65532 또는 1000) — 운영 혼선 제거

### 5-3. 테스트 — 보안 회귀 케이스 누락
- 제안: 명령 주입/UID 정합성/writable_paths 반영 실패 케이스를 NFR-04 최소셋에 포함

## P3 (Minor)

- 설정 키 명칭 혼재: `stack.forced_stack` vs 실제 `stack` (config_loader.py:197)
- Go 모노레포 `cmd/*` vs JVM multi-module 혼동 여지 — 별개 레이어 명시 필요
- Protocol 런타임 검증(NFR-08)이 NFR-04 최소셋에 반영 안 됨 — `isinstance(GoStackModule(), StackModule)` 테스트 명시
- `StackDetectResult.cmd_candidates` 기본값/기존 호출부 호환성 테스트 없음
- digest pinning 선택 옵션 추가 제안 (공급망 리스크)

## 최종 Verdict

- [ ] 승인 가능
- [x] **조건부 승인 (P1 수정 필요)**
- [ ] 반려 (재설계)

> P1 이슈들이 모두 "요구사항 문서 내 계약 보강"으로 해결 가능한 범위. 다만 현재 상태로 착수하면 F-24/F-18/F-19의 핵심 경로가 구현 단계에서 충돌할 가능성이 높아 재작업 리스크.
