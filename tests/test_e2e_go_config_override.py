"""BL-001 Phase 8 — Go 스택 config override 통합 회귀 (NFR-04 (l)(m)(k)).

`.devflow-k8s-deploy.yml`의 `stack.go.entrypoint` / `stack.go.probe.path`가
ConfigLoader → ProjectAnalyzer → build_plan/probe_plan 체인을 통과해
최종 Dockerfile + deployment.yaml에 반영되는지 mock 없이 검증.
"""

from __future__ import annotations

from pathlib import Path

from scripts.pipeline.orchestrator import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_multi_cmd_go_project(project_dir: Path, *, config_yaml: str) -> None:
    """multi-cmd Go 모노레포 fixture (api/worker 두 후보).

    config 미지정 시 `_resolve_entrypoint`가 모호성으로 GoBuildPlanError.
    config 지정 시 entrypoint override가 그 경로를 사용.
    """
    _write(project_dir / "go.mod", "module example.com/multi\n\ngo 1.22\n")
    _write(
        project_dir / "cmd" / "api" / "main.go",
        'package main\n\nimport "fmt"\nfunc main() { fmt.Println("api") }\n',
    )
    _write(
        project_dir / "cmd" / "worker" / "main.go",
        'package main\n\nimport "fmt"\nfunc main() { fmt.Println("worker") }\n',
    )
    _write(project_dir / ".devflow-k8s-deploy.yml", config_yaml)


def test_go_entrypoint_override_flows_through_pipeline(tmp_path: Path) -> None:
    """NFR-04 (l): stack.go.entrypoint config가 build_cmd에 반영."""
    project_dir = tmp_path / "project"
    output_dir = tmp_path / "k8s-output"
    config = """
app:
  name: api-svc
  port: 8080
  exposure: ClusterIP
  resource_hint: medium
build:
  engine: skip
stack:
  go:
    entrypoint: ./cmd/api
""".lstrip()
    _make_multi_cmd_go_project(project_dir, config_yaml=config)

    exit_code = main(
        ["--project-dir", str(project_dir), "--output-dir", str(output_dir)]
    )
    assert exit_code in (0, 2), f"unexpected exit code {exit_code}"

    all_files = [p for p in output_dir.rglob("*") if p.is_file()]
    dockerfile_path = next(p for p in all_files if p.name == "Dockerfile")
    dockerfile = dockerfile_path.read_text()

    # build_cmd가 override된 entrypoint로 합성됐는지
    assert "./cmd/api" in dockerfile, (
        f"override된 entrypoint './cmd/api'가 build_cmd에 미반영: {dockerfile}"
    )
    # worker 후보는 선택되지 않아야 함
    assert "./cmd/worker" not in dockerfile


def test_go_probe_path_override_flows_through_pipeline(tmp_path: Path) -> None:
    """NFR-04 (m): stack.go.probe.path config가 deployment.yaml의 probe path에 반영."""
    project_dir = tmp_path / "project"
    output_dir = tmp_path / "k8s-output"
    config = """
app:
  name: api-svc
  port: 8080
  exposure: ClusterIP
  resource_hint: medium
build:
  engine: skip
stack:
  go:
    entrypoint: ./cmd/api
    probe:
      path: /custom-health
""".lstrip()
    _make_multi_cmd_go_project(project_dir, config_yaml=config)

    exit_code = main(
        ["--project-dir", str(project_dir), "--output-dir", str(output_dir)]
    )
    assert exit_code in (0, 2), f"unexpected exit code {exit_code}"

    deployment = next(
        p for p in output_dir.rglob("*") if p.is_file() and p.name == "deployment.yaml"
    ).read_text()

    # probe path가 override된 값으로 반영
    assert "/custom-health" in deployment, (
        "override된 probe path '/custom-health'가 deployment에 미반영"
    )
    # 기본값은 미사용
    assert "/healthz" not in deployment


def test_go_inputs_chain_no_override_uses_defaults(tmp_path: Path) -> None:
    """NFR-04 (k) baseline.

    override 없으면 기본값 — entrypoint=./cmd/api(app_name 매칭) + path=/healthz.
    """
    project_dir = tmp_path / "project"
    output_dir = tmp_path / "k8s-output"
    config = """
app:
  name: api  # cmd/api와 매칭 → ./cmd/api 자동 선택
  port: 9090
  exposure: ClusterIP
  resource_hint: medium
build:
  engine: skip
""".lstrip()
    _make_multi_cmd_go_project(project_dir, config_yaml=config)

    exit_code = main(
        ["--project-dir", str(project_dir), "--output-dir", str(output_dir)]
    )
    assert exit_code in (0, 2), f"unexpected exit code {exit_code}"

    all_files = [p for p in output_dir.rglob("*") if p.is_file()]
    dockerfile = next(p for p in all_files if p.name == "Dockerfile").read_text()
    deployment = next(p for p in all_files if p.name == "deployment.yaml").read_text()

    # app_name=api → ./cmd/api 자동 선택 (F-06 2-a)
    assert "./cmd/api" in dockerfile
    # 기본 probe path
    assert "/healthz" in deployment
    # P1 회귀 — probe.port가 inputs.port(9090) 따라가는지 (containerPort/probe 정합)
    assert "9090" in deployment
