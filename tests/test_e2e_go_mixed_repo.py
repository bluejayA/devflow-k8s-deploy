"""BL-001 Phase 9 — mixed repo (`build.gradle` + `go.mod`) + `stack.forced_stack: go`.

Codex P1 회귀 가드: Go support 추가 후에도 `stack.forced_stack=go` 화이트리스트 누락으로
mixed repo에서 Go 강제 선택이 막혀 있던 결함을 재현/방지한다.

목표:
- build.gradle + go.mod 공존 시 auto 모드는 JVM 우선이지만, `stack.forced_stack: go` 설정
  시에는 Go 파이프라인이 선택되어 Dockerfile이 Go 템플릿으로 생성된다.
"""

from __future__ import annotations

from pathlib import Path

from scripts.pipeline.orchestrator import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_mixed_repo(project_dir: Path, *, config_yaml: str) -> None:
    """build.gradle + go.mod 공존 fixture."""
    _write(
        project_dir / "build.gradle",
        "plugins { id 'org.springframework.boot' version '3.2.0' }\n",
    )
    _write(project_dir / "go.mod", "module example.com/mixed\n\ngo 1.22\n")
    _write(
        project_dir / "main.go",
        'package main\n\nimport "fmt"\nfunc main() { fmt.Println("hi") }\n',
    )
    _write(project_dir / ".devflow-k8s-deploy.yml", config_yaml)


def test_mixed_repo_forced_go_selects_go_pipeline(tmp_path: Path) -> None:
    """build.gradle + go.mod + `stack.forced_stack: go` → Go Dockerfile 생성."""
    project_dir = tmp_path / "project"
    output_dir = tmp_path / "k8s-output"
    config = """
app:
  name: mixed-svc
  port: 8080
  exposure: ClusterIP
  resource_hint: medium
build:
  engine: skip
stack:
  forced_stack: go
""".lstrip()
    _make_mixed_repo(project_dir, config_yaml=config)

    exit_code = main(
        ["--project-dir", str(project_dir), "--output-dir", str(output_dir)]
    )
    assert exit_code in (0, 2), f"unexpected exit code {exit_code}"

    dockerfile = (output_dir / "Dockerfile").read_text()
    # Go 템플릿 시그니처 (golang/distroless multi-stage)
    assert "FROM golang:" in dockerfile, "Go builder stage missing — pipeline picked JVM"
    assert "gcr.io/distroless/static-debian12:nonroot" in dockerfile


def test_mixed_repo_forced_jvm_selects_jvm_pipeline(tmp_path: Path) -> None:
    """대조군: 같은 mixed repo + `stack: jvm` → JVM 파이프라인 선택."""
    project_dir = tmp_path / "project"
    output_dir = tmp_path / "k8s-output"
    config = """
app:
  name: mixed-svc
  port: 8080
  exposure: ClusterIP
  resource_hint: medium
build:
  engine: skip
stack: jvm
""".lstrip()
    _make_mixed_repo(project_dir, config_yaml=config)

    exit_code = main(
        ["--project-dir", str(project_dir), "--output-dir", str(output_dir)]
    )
    assert exit_code in (0, 2), f"unexpected exit code {exit_code}"

    dockerfile = (output_dir / "Dockerfile").read_text()
    # JVM 템플릿 시그니처 (eclipse-temurin)
    assert "eclipse-temurin" in dockerfile or "FROM gradle:" in dockerfile, (
        "JVM template signature missing"
    )
    assert "FROM golang:" not in dockerfile
