# Workspace Analysis

**Detected**: Brownfield
**Timestamp**: 2026-05-12T04:35:00+09:00
**Project Root**: /Users/jay.ahn/projects/infra/devflow-k8s-deploy
**Requires Path Confirmation**: false
**Source**: 이전 분석(2026-04-24T08:38:00+09:00) 기반 + 델타 업데이트 (BL-001 Go 스택 완료 + BL-018 Jinja2 일원화 + BL-019 검증 정책 일원화 + BL-020/021/022 UX 일관성 반영)

## Project Structure

v0.4.0 릴리스 + 5개 BL(BL-001/018/019/020/021/022) 완료된 Python 기반 K8s 배포 자동화 스킬. 42개 테스트 파일(**897 tests**), Claude Code 플러그인 구조. **JVM + Go 듀얼 스택 지원** 상태. 매니페스트 렌더링 단일 경로(Jinja2)로 통합됨(ADR-0001).

## Key Files Found

- `pyproject.toml` — Python 3.11+, uv, pytest, **version 0.4.0** (유지)
- `scripts/` — 핵심 로직 (config_loader, project_analyzer, validate_k8s, manifest_generator, dockerfile_generator 등)
- `scripts/pipeline/` — orchestrator, build_runner, retry_loop
- `scripts/validators/` — K8s 검증 규칙 패키지
  - `rules/`: img, life, net, prb, res, sa, sec, sts, svc (9 규칙 모듈)
- `scripts/stacks/` — **base.py + jvm.py + go.py** (BL-001로 Go 추가)
- `scripts/_shared/types.py` — frozen dataclass + **text_safety**(BL-019: entrypoint/probe.path 검증 위임)
- `templates/manifest/` — **deployment / service / serviceaccount / statefulset / networkpolicy** (BL-018: 5종 모두 Jinja2 템플릿화)
- `templates/dockerfile/` — **jvm.tmpl + go.tmpl + dockerignore.tmpl** (BL-001로 go.tmpl 추가)
- `tests/` — 42개 테스트 파일 (897 tests passing)
- `skills/devflow-k8s-deploy/SKILL.md` — Claude Code 스킬 정의 (BL-020: stack-aware description)
- `DEVELOPER.md` — 개발자 가이드
- `devflow-docs/adr/0001-manifest-rendering-strategy.md` — **신규(BL-018) Jinja2 단일 경로 결정**

## Pre-specified Tech Stack

- **Source**: CLAUDE.md
- **Items**: Python / uv / ruff / pytest, 타입 힌트 필수

## Technology Stack

- **Language**: Python 3.11+
- **Package Manager**: uv
- **Test Framework**: pytest
- **Linter**: ruff
- **Key Dependencies**: PyYAML, Jinja2 (템플릿), pytest-cov
- **Version**: 0.4.0

## Git Activity

- **Last Commit**: 2026-05-11 — BL-018 완료 처리 (활성 개발 중)
- **Recent Focus**: `scripts/manifest_generator.py`, `templates/manifest/`, `scripts/stacks/go.py`, `scripts/_shared/text_safety.py`, `skills/devflow-k8s-deploy/SKILL.md`
- **Recent Commits**:
  - `bc1f9b8 docs(backlog)`: BL-018 완료 처리 — PR #38 머지 (Codex adversarial 3 라운드)
  - `08a5c38 refactor(BL-018)`: manifest 렌더링 단일 경로(Jinja2) 통일 — ADR-0001 (#38)
  - `db82c25 refactor(BL-019)`: entrypoint/probe.path 검증 정책 일원화 — text_safety로 위임 (#37)
  - `dd28279 feat(BL-022)`: k8s-output 디렉토리 구조 — manifests/ 서브디렉토리 분리 (#36)
  - `2620c47 docs(BL-020 + BL-021)`: stack-aware UX 일관성 — SKILL.md + manifest/rationale 주석 (#35)
  - `e1e4c60 refactor(BL-001 Phase 1-5)`: Go 스택 도입 사전 정비 (#29)

## Existing Documentation

- `README.md` — 설치/사용법/제약/로드맵 (v0.4.0 상태)
- `DEVELOPER.md` — 개발자 가이드
- `CLAUDE.md` — 프로젝트별 Claude 지시사항
- `devflow-docs/backlog.md` — Next 4건(BL-017/006/002/005), Open 8건
- `devflow-docs/adr/0001-manifest-rendering-strategy.md` — **신규** Jinja2 단일 경로 결정

## Code Structure

- **Directory Layout**: `scripts/`, `scripts/pipeline/`, `scripts/stacks/`, `scripts/_shared/`, `scripts/validators/`, `templates/`, `tests/`, `skills/`, `devflow-docs/`, `devflow-docs/adr/`
- **Entry Points**: `scripts/pipeline/orchestrator.py` (SkillPipeline — 5 STEP), `scripts/validate_k8s.py` (K8sValidator re-export)
- **Observed Patterns**: 레이어 구조 (pipeline → analyzer → stacks → templates), validators 규칙 레지스트리 패턴(`@register_rule`), **StackModule Protocol(BL-015) — JVM + Go 듀얼 구현**, **PipelineDependencies DI**, **Jinja2 단일 렌더링 경로(ADR-0001)**, **text_safety 검증 위임(BL-019)**

## Coding Patterns (Sampled)

- **Source**: `scripts/stacks/jvm.py`, `scripts/stacks/go.py`, `scripts/stacks/base.py`
- **Naming**: snake_case 함수/변수, PascalCase 클래스, `_` prefix 내부 상수, `_SPRING_BOOT_RE` 형태 정규식 상수
- **Imports**: 절대 경로 (`from scripts._shared.types import ...`)
- **Error Handling**: 명시적 예외 클래스(`GoDetectionError`, `GoBuildPlanError`), Result 타입(`BuildResult`, `AnalysisResult`, `StackDetectResult`)
- **Comments**: 한국어 인라인 주석, F-번호 요구사항 참조 (`# F-29: shell-safe 검증`)
- **Protocol Pattern (BL-015 + BL-001)**: `StackModule` Protocol 정의 + JVM/Go 구현. probe_plan은 framework별 분기 패턴(JVM: spring-boot/ktor/micronaut 감지 → 향후 BL-014에서 확장 예정 / Go: net/http 기본만 → **BL-017 대상**)
- **Framework Detection Pattern (jvm.py 참고)**: build 파일 정규식 매칭 → `_detect_framework_and_version()` 헬퍼 → `framework` 문자열 + version 반환. Go도 동일 패턴 적용 가능 (go.sum/go.mod import 라인 매칭).
