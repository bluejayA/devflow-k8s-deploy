"""BL-006 Phase δ — Python 프로젝트 E2E smoke (실제 orchestrator).

mock 없이 main(--project-dir, --output-dir) 호출 → Dockerfile + deployment.yaml
생성 + Python 스택 흔적(uv builder / python-slim / UID 10001 / uvicorn CMD) 확인.
"""

from __future__ import annotations

from pathlib import Path

from scripts.pipeline.orchestrator import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_fastapi_project(project_dir: Path) -> None:
    _write(
        project_dir / "pyproject.toml",
        '[project]\n'
        'name = "demo"\n'
        'requires-python = ">=3.12"\n'
        'dependencies = ["fastapi>=0.100", "uvicorn>=0.20"]\n',
    )
    _write(project_dir / "uv.lock", "version = 1\n")
    _write(project_dir / "main.py", "app = object()\n")
    _write(
        project_dir / ".devflow-k8s-deploy.yml",
        """
app:
  name: demo
  port: 8000
  exposure: ClusterIP
  resource_hint: medium
build:
  engine: skip
""".lstrip(),
    )


def test_python_project_e2e_generates_dockerfile_and_manifests(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    output_dir = tmp_path / "k8s-output"
    _make_fastapi_project(project_dir)

    exit_code = main(
        ["--project-dir", str(project_dir), "--output-dir", str(output_dir)]
    )
    assert exit_code in (0, 2), f"unexpected exit code {exit_code}"

    all_files = [p for p in output_dir.rglob("*") if p.is_file()]
    names = {p.name for p in all_files}
    assert "Dockerfile" in names, f"Dockerfile 미생성: {names}"
    assert "deployment.yaml" in names, f"deployment.yaml 미생성: {names}"

    dockerfile = next(p for p in all_files if p.name == "Dockerfile").read_text()
    assert "ghcr.io/astral-sh/uv:python3.12-bookworm-slim" in dockerfile
    assert "python:3.12-slim" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "uv sync --frozen --no-install-project --no-dev" in dockerfile  # P2-2
    assert "uvicorn" in dockerfile  # C1: framework + uvicorn + main:app → CMD

    deployment = next(p for p in all_files if p.name == "deployment.yaml").read_text()
    assert "runAsUser: 10001" in deployment


def test_python_generic_e2e_no_cmd_gap_comment(tmp_path: Path) -> None:
    # framework 미감지 → CMD 없음 + entrypoint gap 주석
    project_dir = tmp_path / "project"
    output_dir = tmp_path / "k8s-output"
    _write(
        project_dir / "pyproject.toml",
        '[project]\nname="d"\nrequires-python=">=3.11"\ndependencies=["requests"]\n',
    )
    _write(project_dir / "uv.lock", "version = 1\n")
    _write(
        project_dir / ".devflow-k8s-deploy.yml",
        "app:\n  name: d\n  port: 8000\n  exposure: ClusterIP\n"
        "  resource_hint: small\nbuild:\n  engine: skip\n",
    )

    exit_code = main(
        ["--project-dir", str(project_dir), "--output-dir", str(output_dir)]
    )
    assert exit_code in (0, 2)

    all_files = [p for p in output_dir.rglob("*") if p.is_file()]
    dockerfile = next(p for p in all_files if p.name == "Dockerfile").read_text()
    assert "entrypoint gap" in dockerfile
    assert "\nCMD " not in dockerfile


def test_python_entrypoint_override_e2e(tmp_path: Path) -> None:
    # P1-2: 자동 추론 실패(main.py/app.py 없음) + config entrypoint override → CMD 생성
    project_dir = tmp_path / "project"
    output_dir = tmp_path / "k8s-output"
    _write(
        project_dir / "pyproject.toml",
        '[project]\nname="d"\nrequires-python=">=3.11"\n'
        'dependencies=["fastapi>=0.100", "uvicorn>=0.20"]\n',
    )
    _write(project_dir / "uv.lock", "version = 1\n")
    _write(
        project_dir / ".devflow-k8s-deploy.yml",
        "app:\n  name: d\n  port: 9000\n  exposure: ClusterIP\n"
        "  resource_hint: small\n"
        "stack:\n  python:\n    entrypoint: custom.mod:application\n"
        "build:\n  engine: skip\n",
    )

    exit_code = main(
        ["--project-dir", str(project_dir), "--output-dir", str(output_dir)]
    )
    assert exit_code in (0, 2)

    all_files = [p for p in output_dir.rglob("*") if p.is_file()]
    dockerfile = next(p for p in all_files if p.name == "Dockerfile").read_text()
    # override entrypoint + user port 9000이 CMD에 반영
    assert "custom.mod:application" in dockerfile
    assert "9000" in dockerfile
    assert "--no-install-project" in dockerfile  # P2-2
