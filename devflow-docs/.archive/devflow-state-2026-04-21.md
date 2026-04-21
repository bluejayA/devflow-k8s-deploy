# DevFlow State

## Current Phase
finished

## Current Stage
v0.1.0 Released — flow terminated (2026-04-21)

## Finishing Choice
B — PR #2 merged, v0.1.0 tagged + released

## PR URL
https://github.com/bluejayA/devflow-k8s-deploy/pull/2

## Release
https://github.com/bluejayA/devflow-k8s-deploy/releases/tag/v0.1.0

## Approved Units (2026-04-17)
**Source**: devflow-docs/inception/units.md (Standard depth)

- Phase 1: `shared`
- Phase 2: `stack_module`, `template_renderer`, `config_loader`, `atomic_writer`, `k8s_validator`, `kubectl_dry_runner`
- Phase 3: `project_analyzer`, `dockerfile_generator`, `manifest_generator`, `output_packager`, `pipeline_build_runner`, `pipeline_retry_loop`
- Phase 4: `pipeline_orchestrator`
- Phase 5: `skill_md_and_readme`
- Phase 6: `security_tests` (NFR-SEC-05 CI)

## Completed Units
- [x] Unit 1: `shared` (commits: da6108a init + 865ba2c fix) — 35 tests pass, ruff+mypy clean
- [x] Unit 2: `stack_module` (commits: 5cbe09e init + 5a02778/01aee3e/abd8d79 Crit+Imp + 2f6bef7 Minor + 22a1215 ValueError) — 96 tests pass, ruff+mypy clean. Critical 1 + Important 7 + Minor 8 + ValueError 대칭 2 = 이슈 18건 반영.
- [x] Unit 3: `template_renderer` (commits: ac31671 init + 06b9e81 Important 4) — 122 tests pass, ruff+mypy clean. Jinja2 결정론 렌더러 + identifier validation + CRLF/sanitization docstring.
- [x] Unit 4: `config_loader` (commits: c1dde0f init + 4f850ad/95e9b60 Important 5) — 156 tests pass, ruff+mypy clean. 3계층 YAML + namespace 4단계 + stack_decision. ResolvedConfig.layer_raws 필드 추가(shared 보강). YAML bomb 방어 + symlink escape + OSError 구분.
- [x] Unit 5: `atomic_writer` (commits: 97a3da2 init + 868ac9c Critical+Important 6) — 177 tests pass, ruff+mypy clean. atomic rename + SIGINT/SIGTERM 핸들러 + 7일 고아 GC + on_exists(prompt/overwrite/suffix). symlink GC 방어(Critical) + enter-failure handler 원복 + on_exists validation + suffix counter.
- [x] Unit 6: `k8s_validator` (commits: b91b841 init FAIL → ebcb0a9 F-43 재작업 → 4676e8b Important 6) — 272 tests pass, ruff+mypy clean. F-43 매트릭스 정합(SEC-001~009, RES-001, IMG-001, SA-001/002, SVC-001/002, PRB-001/002, RES-W01, IMG-W01) + CLI(--json/--skipped CSV) + 3단계 exit code. `check_yaml_refs` fileio 공용화. int 예외/None-chain 방어.
- [x] Unit 7: `kubectl_dry_runner` (commits: b4c35ff init + 84a31dd Important 5) — 298 tests pass, ruff+mypy clean. `--dry-run=client` allowlist + degraded skip + timeout 10s + manifest_dir 방어 검증(resolve/is_dir) + UnicodeDecodeError 방어(errors=replace) + kubectl_path DI 경고.
- [x] Unit 8: `project_analyzer` (commits: 50f4b46 init + 612ec6a Critical+Important 9 + 9697950 Kotlin DSL colon) — 348 tests pass, ruff+mypy clean. stack routing + multi-module(Gradle/Maven, KTS/Groovy, colon prefix) + StatefulnessSignal(HIGH/MEDIUM, multi-module 루트+모듈 양쪽 스캔) + prompt_callback DI. **Critical Path Traversal 방어**(module 이름 validation + is_within root 정정) + YAML bomb 가드 + prompt 응답 검증 + UnsupportedStackError 래핑.
- [x] Unit 9: `dockerfile_generator` (commits: 7073155 init + 030933c Important 5) — 372 tests pass, ruff+mypy clean. multi-stage(JDK builder→JRE runner) + non-root(USER appuser UID 1000) + COPY --chown + latest 차단 + digest pinning + 캐시 레이어 분기. **OCI image regex allowlist + 개행 인젝션 방어** + build_cmd/artifact_path 검증 + build_system 토큰 분해 매칭.
- [x] Unit 10: `manifest_generator` (commits: 32e6e91 init + baff9b2/0bd08ab/edb6352 Critical+Important 8) — 421 tests pass, ruff+mypy clean. Deployment/Service/SA + Pod securityContext(F-31 완전) + Container securityContext(F-32) + emptyDir sizeLimit(50Mi/100Mi) + probes http/tcp + DNS-1123 + 개행 차단. **Critical 2 수정**: 3개 메서드 공통 입력 검증 + exposure whitelist. `_validate_image_tag` → `scripts/_shared/image_ref.py` 공용화 + TemplateRenderer trim_blocks/lstrip_blocks.
- [x] Unit 11: `output_packager` (commits: 3c51dff init + 88d52c3/a86898c Critical+Important 7) — 476 tests pass, ruff+mypy clean. summary.json v1 + rationale.md 10 섹션 + troubleshoot.md. **Critical 수정**: `redact_sensitive`(Bearer/JWT/kubeconfig/token 패턴) + `_shared/text_safety.py` 공용화(Unit 9/10/11 공유) + skip_reasons pass-through + image 방어 검증 + JSON 결정성(sorted lists + trailing newline).
- [x] Unit 12: `pipeline_build_runner` (commits: d84896d init + ab08f73 Important 5) — 506 tests pass, ruff+mypy clean. detect_engine(skip/auto/docker/podman/nerdctl 우선순위) + build(shell=False argv, 7-tuple allowlist, F-102 timeout 주입+0=무제한) + `BuildResult` 확장(stdout/stderr/exit_code) + RealEngine Literal 좁힘 + is_within 재사용 + engine whitelist assert.
- [x] Unit 13: `pipeline_retry_loop` (commits: b01acbc init + 76c20a4 Minor 3) — 525 tests pass, ruff+mypy clean. 3개 loop(validation/dry_run/build) + F-56 pass-through(collect_validation_outcome) + lambda 인자 캡처. PASS (Critical/Important 0). application-design drift 교정(success_predicate `<=2` → `!=1`, F-42 정합).
- [x] Unit 14: `pipeline_orchestrator` (commits: 58281bf init + 4d3ce60 Important 6) — 559 tests pass, ruff+mypy clean. 5-STEP 전체 오케스트레이션 + PipelineDependencies DI + HelpCatalog 10 term + MessagePolicy + retry_loop + BailOutError 처리. `_safe_section`(config None-chain 방어) + prompt_callback 응답 검증 + image_tag 검증 + `_raise_bailout` 공통화 + cast + `_coerce_literal_or_default`.
- [x] Unit 15: `skill_md_and_readme` (commits: 970308e init + 6f92ccc/6c9fd9d/eec406b Critical+Important 7) — 564 tests pass, ruff+mypy clean. SKILL.md 5-STEP 프롬프트 + 10 term 카탈로그. **Critical 2 수정**: `orchestrator.py` CLI 진입점(main + argparse) + F-83 스키마 정합. README CI 안전화(set -uo pipefail) + registry.example.com + 경로 모델 통일.
- [x] Unit 16: `security_tests` (commits: 5c7b5fc init + 6ad9b90/33036e2 Important 5) — **597 tests pass**, ruff+mypy clean. NFR-SEC-05 경계 allowlist CI 테스트 (33 cases). autouse conftest + 글로벌 subprocess 패치 + 인젝션 토큰 14종(shell meta + `\n/\r/\x00`) + kubectl 7 forbidden verbs + 픽스처 자체 검증. **스펙 준수도 100%**.

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
