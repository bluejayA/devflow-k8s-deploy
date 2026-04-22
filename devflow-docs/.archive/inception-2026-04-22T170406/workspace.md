# Workspace Analysis

**Detected**: Brownfield
**Timestamp**: 2026-04-22T11:45:00+09:00
**Project Root**: /Users/jay.ahn/projects/infra/devflow-k8s-deploy
**Requires Path Confirmation**: false
**Source**: 이전 분석(2026-04-22T10:25:00+09:00) 기반 + 델타 업데이트 (Git Activity 갱신)

## Project Structure

v0.3.0-p1 릴리스 완료된 Python 기반 K8s 배포 자동화 스킬. 스크립트 6,200+ 라인, 테스트 22개 파일(646 테스트), Claude Code 플러그인 구조.

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
- **Recent Focus**: `scripts/validate_k8s.py`, `scripts/_shared/defaults.py`, `scripts/pipeline/orchestrator.py`
- **Recent Commits**:
  - `c48c9f6 fix(RES-W01)`: jvm small 티어 cpu_request 50m → 125m
  - `9a39019 feat(v0.3.0-p1)`: replicas 설정화 + LIFE-W01/IMG-W02 WARN 규칙 (#20)
  - `fb31470 chore`: .worktrees/ .gitignore에 추가
  - `0f765f4 feat(v0.2.0)`: alpine Dockerfile + deployment image wiring

## Existing Documentation

- `README.md` — v0.2.0 기준, 설치/사용법/제약/v0.3+ 로드맵 포함
- `devflow-docs/inception/` — 현재 세션 산출물
- `devflow-docs/backlog.md` — 17개 이슈 추적 중 (#21 validators 모듈 분리 포함)

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
