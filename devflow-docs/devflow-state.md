# DevFlow State

## Current Phase
INCEPTION

## Current Stage
application-design (DETAIL 완료, INCEPTION 종료 게이트)

## Complexity
Comprehensive

## Selected Approach
A안 (설계 우선) — application-design(Comprehensive, NFR Design) → units-generation(Standard) → code-generation(Standard, TDD) → build-and-test(Standard)

## Completed Stages
- [x] workspace-detection (Greenfield, scaffolding only)
- [x] brainstorming (side-skill, v0.1.0 scope locked — JVM stack only)
- [x] requirements-analysis (Comprehensive; **71 F-*** (자동 집계, F-09 reserved), **17 NFR** (NFR-09 제거, NFR-SEC-05 추가), 13 assumptions, 0 open questions)
- [x] user-stories (22 stories: Must 17, Should 4, Could 1; 4 actors; 8 tech requirements; US-001/009/012/017 확장)
- [x] nfr-requirements (GENERATE, 개발자 도구/CLI + MVP, 17 NFR항목, 2건 조정 + NFR-SEC-05 신규)
- [x] workflow-planning (A안 선택: 설계 우선, Comprehensive application-design 포함)
- [x] application-design — **DETAIL 완료 + 외부 검토 8건 반영** (Comprehensive). 12개 컴포넌트 상세 설계 + 5-STEP ASCII 시퀀스 다이어그램 + 도움말 카탈로그 10개(step 라벨) + retry/allowlist 시그니처 강화 + types.py 카탈로그 + SkillPipeline 서브유닛 매핑 + 테스트 경계 매트릭스. **두 리뷰(spec-reviewer GO-WITH-CHANGES + Codex No-Go) 모두 GO 상태로 해소.** INCEPTION 종료 게이트 대기 중

## Key Decisions
- Greenfield workspace confirmed. Existing artifacts: README, plugin.json, LICENSE, .gitignore only.
- Complexity: Comprehensive (architecture decisions + 3-layer config schema + extensibility constraints)
- v0.1.0 scope: JVM-only backend (Kotlin + Java Spring), generate-only boundary, validate_k8s.py hardened, 5-STEP SKILL structure
- Brainstorming artifact: devflow-docs/inception/2026-04-15-brainstorming-v0.1.0-scope.md
- Container build engine: docker/podman/nerdctl auto-detect. buildah/kaniko v0.2+.
- Template engine: Jinja2
- AIDLC integration: summary.json + exit code contract only in v0.1.0
- Output policy: `output.on_exists` config (prompt/overwrite/suffix, default prompt)
- Requirements artifact: devflow-docs/inception/requirements.md
- **2026-04-17 application-design 리뷰 반영 (3-페르소나 + Codex)**:
  - 컴포넌트 15 → 12 (NamespaceResolver/AutoFixLoop/ContainerBuildRunner 흡수)
  - 비개발자/AI-assisted 사용자 친화 확대: F-02a/b + NFR-17 전 STEP 한국어 메시지 정책
  - 안전 계약 강화: F-83 `validation.skipped[]`, F-42 exit code 2 가이드, F-103 SIGINT 핸들러, F-32 `/var/log` 자동 emptyDir, F-52 troubleshoot 한국어 요약
  - 신규 NFR-SEC-05: 경계 allowlist CI 감지 테스트
  - v0.2+ 백로그 확장 (NetworkPolicy/PDB/Stateful 신뢰도/LB 비용/BuildPlan 일반화/도움말 외부화)
- **2026-04-17 application-design DETAIL 외부 검토 8건 반영 (spec-reviewer + Codex)**:
  - NFR-SEC-05 픽스처 보안 강화 (shell=True/문자열/인젝션 토큰 차단)
  - 시그니처 통일 (SkillPipeline.dry_run, ProjectAnalyzer DI, HelpCatalog 인터페이스 노출, _detect_statefulness 오타 수정)
  - retry.py FixOutcome 구조체 + success_predicate 필수
  - F-56 pass-through 경로 (skipped 사유 → summary.json + rationale.md)
  - 도움말 카탈로그 step 라벨, types.py 카탈로그, SkillPipeline 서브유닛 매핑
  - F-* 카운트 정정: 73 → 71 (F-09 reserved). NFR 17개 (NFR-09 제거, NFR-SEC-05 추가)
