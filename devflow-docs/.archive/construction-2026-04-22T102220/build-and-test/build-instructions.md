# Build Instructions — devflow-k8s-deploy v0.1.0

## Prerequisites

- **Python 3.11+** (`.python-version` 파일 참조)
- **[uv](https://github.com/astral-sh/uv)** — Python 패키지 매니저 (권장) 또는 `pip`
- **Git** — 워크트리 / 브랜치 관리

## Dependencies (프로덕션)

`pyproject.toml` 정의:
- `pyyaml >= 6.0.1` — YAML 파싱
- `jinja2 >= 3.1.6` — 템플릿 렌더링
- `defusedxml >= 0.7.1` — Maven pom.xml 안전 파싱 (XXE 방어)

## Dev Dependencies

- `pytest` + `pytest-cov` — 테스트 실행
- `ruff` — 린트
- `mypy` — 정적 타입 검사

## Steps

```bash
# 1. 저장소 클론 및 브랜치 체크아웃 (또는 worktree)
cd /Users/jay.ahn/projects/infra/devflow-k8s-deploy-construction
git status  # 현재 브랜치: feature/v0.1.0-construction

# 2. 의존성 설치 (uv 권장)
uv sync --all-extras

# 또는 pip 사용 시
# python -m venv .venv && source .venv/bin/activate
# pip install -e ".[dev]"

# 3. 코드 품질 검사
uv run ruff check scripts/ tests/
uv run mypy scripts/

# 4. 빌드 검증 (Python은 별도 컴파일 불필요, import 경로 확인)
uv run python -c "from scripts.pipeline.orchestrator import SkillPipeline, main; print('OK')"
```

## Expected Output

```
$ uv run ruff check scripts/ tests/
All checks passed!

$ uv run mypy scripts/
Success: no issues found in 25 source files

$ uv run python -c "from scripts.pipeline.orchestrator import SkillPipeline, main; print('OK')"
OK
```

## CLI 진입점 검증

```bash
uv run python -m scripts.pipeline.orchestrator --help
```

예상 출력: `--project-dir` / `--output-dir` 인자 설명 + Exit code 가이드.

## Change Log

- 2026-04-21 — v0.1.0 초기 구축 완료 (Unit 1~16)
