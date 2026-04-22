# Workspace Analysis

**Detected**: Brownfield
**Timestamp**: 2026-04-22T10:25:00+09:00
**Project Root**: /Users/jay.ahn/projects/infra/devflow-k8s-deploy
**Requires Path Confirmation**: false
**Source**: 이전 분석(2026-04-15T14:55:00+09:00) 기반 + 델타 업데이트 (Greenfield → Brownfield 전환)

## Project Structure

v0.2.0 릴리스 완료된 Python 기반 K8s 배포 자동화 스킬. 스크립트 6,100+ 라인, 테스트 22개 파일(631 테스트), Claude Code 플러그인 구조.

## Key Files Found

- `pyproject.toml` — Python 3.11+, uv, pytest
- `scripts/` — 핵심 로직 (config_loader, project_analyzer, validate_k8s, manifest_generator 등)
- `scripts/pipeline/` — orchestrator, build_runner, retry_loop
- `scripts/stacks/jvm.py` — JVM 스택 구현 (709줄)
- `templates/manifest/` — deployment.tmpl, service.tmpl, serviceaccount.tmpl
- `templates/dockerfile/` — jvm.tmpl
- `tests/` — 22개 테스트 파일
- `skills/devflow-k8s-deploy/SKILL.md` — Claude Code 스킬 정의

## Pre-specified Tech Stack

- **Source**: CLAUDE.md
- **Items**: Python / uv / ruff / pytest, 타입 힌트 필수

## Technology Stack

- **Language**: Python 3.11+
- **Package Manager**: uv
- **Test Framework**: pytest
- **Linter**: ruff
- **Key Dependencies**: PyYAML, Jinja2 (템플릿), pytest-cov

## Git Activity

- **Last Commit**: 2026-04-22 — 활성 개발 중
- **Recent Focus**: `scripts/pipeline/orchestrator.py`, `scripts/stacks/jvm.py`, `scripts/validate_k8s.py`
- **Recent Commits**:
  - `0f765f4 feat(v0.2.0)`: alpine Dockerfile + deployment image wiring + resource_hint tiering
  - `e0dee25 chore(devflow)`: v0.1.0 flow 완료 아카이브
  - `34606bc docs(readme)`: v0.1.0 Released 상태 업데이트

## Existing Documentation

- `README.md` — v0.2.0 기준, 설치/사용법/제약/v0.3+ 로드맵 포함
- `devflow-docs/inception/` — 요구사항/설계/NFR 산출물 (아카이브됨)
- `devflow-docs/backlog.md` — 16개 이슈 추적 중

## Code Structure

- **Directory Layout**: `scripts/`, `scripts/pipeline/`, `scripts/stacks/`, `scripts/_shared/`, `templates/`, `tests/`, `skills/`, `devflow-docs/`
- **Entry Points**: `scripts/pipeline/orchestrator.py` (SkillPipeline), `scripts/validate_k8s.py` (K8sValidator)
- **Observed Patterns**: 레이어 구조 (pipeline → analyzer → stacks → templates)

## Coding Patterns (Sampled)

- **Source**: `scripts/stacks/jvm.py`
- **Naming**: snake_case 함수/변수, PascalCase 클래스, `_` prefix 내부 상수
- **Imports**: 절대 경로 (`from scripts._shared.types import ...`)
- **Error Handling**: 명시적 예외 클래스, Result 타입 (`BuildResult`, `AnalysisResult`)
- **Comments**: 한국어 인라인 주석, F-번호 요구사항 참조 (`# F-57: auto 모드`)
