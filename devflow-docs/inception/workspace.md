# Workspace Analysis

**Detected**: Brownfield
**Timestamp**: 2026-05-13T22:55:00Z
**Project Root**: /Users/jay.ahn/projects/infra/devflow-k8s-deploy
**Requires Path Confirmation**: false
**Source**: 이전 분석(2026-05-12T04:35:00+09:00) 기반 + 델타 업데이트 (BL-017 머지 + v0.5.0 릴리스 반영, BL-006 진입 준비)

## Project Structure

v0.5.0 릴리스(plugin.json 정합 fix) + BL-017 머지 완료된 Python 기반 K8s 배포 자동화 스킬. 48개 테스트 파일(**928 tests passing**, BL-017 +31), Claude Code 플러그인 구조. **JVM + Go 듀얼 스택**(go는 BL-017로 gin/echo/fiber 프레임워크 자동 감지까지 지원). 매니페스트 렌더링 단일 경로(Jinja2)로 통합됨(ADR-0001). 다음 작업 BL-006(Python 스택)으로 **3-stack 전환** 예정.

## Key Files Found

- `pyproject.toml` — Python 3.11+, uv, pytest, **version 0.4.0** (release commit이 .claude-plugin/plugin.json만 0.5.0 동기화)
- `.claude-plugin/plugin.json` — **0.5.0** (marketplace 정합)
- `scripts/` — 핵심 로직 (config_loader, project_analyzer, validate_k8s, manifest_generator, dockerfile_generator 등)
- `scripts/pipeline/` — orchestrator, build_runner, retry_loop
- `scripts/validators/` — K8s 검증 규칙 패키지 (rules/: img, life, net, prb, res, sa, sec, sts, svc — 9 규칙 모듈)
- `scripts/stacks/` — **base.py + jvm.py + go.py** (BL-017로 go.py에 framework 감지 헬퍼 추가 — `_GIN_RE`/`_ECHO_RE`/`_FIBER_RE`, `_parse_go_mod_require`, `_detect_go_framework`)
- `scripts/_shared/types.py` — frozen dataclass + **text_safety**(BL-019: entrypoint/probe.path 검증 위임)
- `scripts/config_loader.py` — `_SUPPORTED_STACKS = frozenset({"auto", "jvm", "go"})` (BL-006에서 `"python"` 추가 대상)
- `templates/manifest/` — **deployment / service / serviceaccount / statefulset / networkpolicy** (BL-018: 5종 모두 Jinja2)
- `templates/dockerfile/` — **jvm.tmpl + go.tmpl + dockerignore.tmpl** (BL-006에서 `python.tmpl` 신규 추가 대상)
- `tests/` — 48개 테스트 파일 (928 tests passing)
- `skills/devflow-k8s-deploy/SKILL.md` — Claude Code 스킬 정의 (BL-020: stack-aware description — BL-006 시 Python 언급 추가 필요)
- `DEVELOPER.md` — 개발자 가이드
- `devflow-docs/adr/0001-manifest-rendering-strategy.md` — Jinja2 단일 경로 결정 (BL-018)

## Pre-specified Tech Stack

- **Source**: CLAUDE.md
- **Items**: Python / uv / ruff / pytest, 타입 힌트 필수

## Technology Stack

- **Language**: Python 3.11+
- **Package Manager**: uv
- **Test Framework**: pytest
- **Linter**: ruff
- **Key Dependencies**: PyYAML, Jinja2 (템플릿), pytest-cov
- **Version**: 0.4.0 (pyproject) / 0.5.0 (plugin.json)

## Git Activity

- **Last Commit**: 2026-05-14 — v0.5.0 release (chore)
- **Recent Focus**: `scripts/stacks/go.py`, `tests/stacks/test_go.py`, `devflow-docs/backlog.md`, `.claude-plugin/plugin.json`, `scripts/manifest_generator.py`
- **Recent Commits**:
  - `45b0a72 chore(release): v0.5.0` — 28 commits 누적분 통합 + plugin.json 정합 fix(0.2.0→0.5.0)
  - `87868e1 docs(backlog)`: BL-017 완료 처리 — PR #39 머지 (Codex 2 라운드)
  - `27a9235 Merge pull request #39` — BL-017 머지
  - `bb27832 fix(BL-017)`: Codex P2 회귀 — indirect skip + path boundary 정밀화
  - `09a15a1 fix(BL-017)`: R1 리뷰 minor 권고 반영 — 가독성/이식성 보강
  - `c187eb3 feat(BL-017)`: Go 프레임워크 probe 자동 감지 — gin/echo/fiber

## Existing Documentation

- `README.md` — 설치/사용법/제약/로드맵 (v0.4.0 상태 — v0.5.0 동기화 미반영)
- `DEVELOPER.md` — 개발자 가이드
- `CLAUDE.md` — 프로젝트별 Claude 지시사항
- `devflow-docs/backlog.md` — Next 3건 (BL-006/002/005), Open 9건
- `devflow-docs/adr/0001-manifest-rendering-strategy.md` — Jinja2 단일 경로 결정

## Code Structure

- **Directory Layout**: `scripts/`, `scripts/pipeline/`, `scripts/stacks/`, `scripts/_shared/`, `scripts/validators/`, `templates/`, `tests/`, `skills/`, `devflow-docs/`, `devflow-docs/adr/`
- **Entry Points**: `scripts/pipeline/orchestrator.py` (SkillPipeline — 5 STEP), `scripts/validate_k8s.py` (K8sValidator re-export)
- **Observed Patterns**: 레이어 구조 (pipeline → analyzer → stacks → templates), validators 규칙 레지스트리 패턴(`@register_rule`), **StackModule Protocol(BL-015) — JVM + Go 듀얼 구현 → BL-006으로 Python 합류 예정**, **PipelineDependencies DI**, **Jinja2 단일 렌더링 경로(ADR-0001)**, **text_safety 검증 위임(BL-019)**

## Coding Patterns (Sampled)

- **Source**: `scripts/stacks/jvm.py`, `scripts/stacks/go.py`, `scripts/stacks/base.py`
- **Naming**: snake_case 함수/변수, PascalCase 클래스, `_` prefix 내부 상수, `_SPRING_BOOT_RE`/`_GIN_RE` 형태 정규식 상수
- **Imports**: 절대 경로 (`from scripts._shared.types import ...`)
- **Error Handling**: 명시적 예외 클래스(`GoDetectionError`, `GoBuildPlanError`), Result 타입(`BuildResult`, `AnalysisResult`, `StackDetectResult`)
- **Comments**: 한국어 인라인 주석, F-번호 요구사항 참조 (`# F-29: shell-safe 검증`)
- **Protocol Pattern (BL-015 + BL-001 + BL-017)**: `StackModule` Protocol 정의 + JVM/Go 구현. probe_plan은 framework별 분기 패턴 — JVM(spring-boot 감지), Go(net/http + gin/echo/fiber 4-way 감지 with "Direct dependency wins" + version-agnostic + `/health` 통일). **BL-006 Python은 이 패턴을 그대로 미러링**: pyproject.toml/requirements.txt → direct dependency 우선 → django/flask/fastapi 4-way 감지.
- **Framework Detection Pattern (go.py 확립)**: regex 정규식 상수(non-capturing version suffix + `(?![\w/-])` negative lookahead) + `_parse_<manifest>` 파서 (indirect skip) + `_match_frameworks` 헬퍼 + 4단계 의사결정 (direct single → direct multi go-generic → sum single → sum multi/none go-generic) + `_read_<file>_safe` (symlink escape 가드, MemoryError 비흡수). 모든 단계가 BL-006에 재활용 가능.
