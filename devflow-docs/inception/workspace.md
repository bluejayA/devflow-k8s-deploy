# Workspace Analysis

**Detected**: Brownfield
**Timestamp**: 2026-04-24T08:38:00+09:00
**Project Root**: /Users/jay.ahn/projects/infra/devflow-k8s-deploy
**Requires Path Confirmation**: false
**Source**: 이전 분석(2026-04-22T17:04:00+09:00) 기반 + 델타 업데이트 (v0.4.0 릴리즈 + BL-015 StackModule Protocol 확장 반영)

## Project Structure

v0.4.0 릴리스 완료된 Python 기반 K8s 배포 자동화 스킬. 스크립트 7,000+ 라인(추정), 39개 테스트 파일(**695 tests**), Claude Code 플러그인 구조. JVM 스택 단일 지원 → 다국어 확장 준비 완료(BL-015 Protocol 확장).

## Key Files Found

- `pyproject.toml` — Python 3.11+, uv, pytest, **version 0.4.0**
- `scripts/` — 핵심 로직 (config_loader, project_analyzer, validate_k8s, manifest_generator, dockerfile_generator 등)
- `scripts/pipeline/` — orchestrator, build_runner, retry_loop
- `scripts/validators/` — K8s 검증 규칙 패키지
  - `rules/`: img, life, **net**, prb, res, sa, sec, **sts**, svc (9 규칙 모듈, **+net/sts 신규**)
- `scripts/stacks/` — **base.py (Protocol 정의) + jvm.py (구현)** ← BL-015로 Protocol 확장됨
- `scripts/_shared/types.py` — frozen dataclass (UserInputs, **ClusterConfig**, AnalysisResult 등)
- `templates/manifest/` — **deployment.tmpl, service.tmpl, serviceaccount.tmpl만 존재** (StatefulSet/NetworkPolicy는 Jinja2 템플릿 없이 Python 코드 내부에서 YAML 생성)
- `templates/dockerfile/` — **jvm.tmpl, dockerignore.tmpl** (Go 추가 예정: go.tmpl)
- `tests/` — 39개 테스트 파일 (695 tests passing)
- `skills/devflow-k8s-deploy/SKILL.md` — Claude Code 스킬 정의
- `DEVELOPER.md` — **개발자 가이드 (v0.4.0 이후 신규)**

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

- **Last Commit**: 2026-04-24 — 활성 개발 중 (BL-001 착수 준비)
- **Recent Focus**: `devflow-docs/backlog.md`, `DEVELOPER.md`, `scripts/stacks/`, `scripts/validators/rules/`, `scripts/manifest_generator.py`
- **Recent Commits**:
  - `d5a4e14 docs(backlog)`: BL-001 범위 축소 + BL-017 신규 생성
  - `5fb89ae docs(dev)`: 개발자 가이드 DEVELOPER.md 추가
  - `0760286 refactor(BL-015)`: StackModule Protocol로 Dockerfile 생성 책임 이관 (#26)
  - `b8b4666 feat(bl003-bl004)`: StatefulSet/PVC + NetworkPolicy zero-trust (#11 #13) (#23)
  - `8225911 refactor(validators)`: validate_k8s.py 규칙별 모듈 분리 (#22)

## Existing Documentation

- `README.md` — 설치/사용법/제약/로드맵 (v0.4.0 상태)
- `DEVELOPER.md` — **개발자 가이드 (신규, 2026-04-23)**
- `CLAUDE.md` — 프로젝트별 Claude 지시사항
- `devflow-docs/backlog.md` — Next 3건(BL-001/002/005), Open 12건(BL-006~014, BL-016, BL-017)

## Code Structure

- **Directory Layout**: `scripts/`, `scripts/pipeline/`, `scripts/stacks/`, `scripts/_shared/`, `scripts/validators/`, `templates/`, `tests/`, `skills/`, `devflow-docs/`
- **Entry Points**: `scripts/pipeline/orchestrator.py` (SkillPipeline — 5 STEP), `scripts/validate_k8s.py` (K8sValidator re-export)
- **Observed Patterns**: 레이어 구조 (pipeline → analyzer → stacks → templates), validators 규칙 레지스트리 패턴(`@register_rule`), **StackModule Protocol(BL-015)**, **PipelineDependencies DI**

## Coding Patterns (Sampled)

- **Source**: `scripts/stacks/jvm.py`, `scripts/stacks/base.py`
- **Naming**: snake_case 함수/변수, PascalCase 클래스, `_` prefix 내부 상수
- **Imports**: 절대 경로 (`from scripts._shared.types import ...`)
- **Error Handling**: 명시적 예외 클래스, Result 타입 (`BuildResult`, `AnalysisResult`, `DetectResult`)
- **Comments**: 한국어 인라인 주석, F-번호 요구사항 참조 (`# F-57: auto 모드`)
- **Protocol Pattern (BL-015)**: `StackModule` Protocol 정의 (base.py) + 각 스택 구현 (`JvmStackModule`). 신규 스택 추가 시 Protocol 계약(`template_name`, `dockerfile_context`, `detect`, `build_plan`, `probe_plan`, `defaults`, `artifact_locator`) 준수
