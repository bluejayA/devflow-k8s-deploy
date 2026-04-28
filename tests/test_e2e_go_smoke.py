"""BL-001 Phase 7 — Go 프로젝트 E2E smoke (실제 orchestrator).

mock 없이 main(--project-dir, --output-dir) 호출 → Dockerfile + deployment.yaml
생성 + Go 스택 흔적(golang/distroless/UID 65532) 확인.
"""

from __future__ import annotations

from pathlib import Path

from scripts.pipeline.orchestrator import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_go_project(project_dir: Path, *, app_name: str = "myapp") -> None:
    _write(project_dir / "go.mod", "module example.com/myapp\n\ngo 1.22\n")
    _write(
        project_dir / "main.go",
        'package main\n\nimport "fmt"\n\n'
        'func main() { fmt.Println("hello") }\n',
    )
    # 빌드/검증 스킵 + app_name 명시 (DNS-1123 정규화 분기 회피)
    _write(
        project_dir / ".devflow-k8s-deploy.yml",
        f"""
app:
  name: {app_name}
  port: 8080
  exposure: ClusterIP
  resource_hint: medium
build:
  engine: skip
""".lstrip(),
    )


def test_go_project_e2e_generates_dockerfile_and_manifests(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    output_dir = tmp_path / "k8s-output"
    _make_go_project(project_dir, app_name="myapp")

    exit_code = main(
        [
            "--project-dir",
            str(project_dir),
            "--output-dir",
            str(output_dir),
        ]
    )
    # 0 (PASS) 또는 2 (WARN soft-success) 허용 — kubectl 미설치/cluster 없어서 발생하는 WARN.
    assert exit_code in (0, 2), f"unexpected exit code {exit_code}"

    # AtomicWriter는 final_path 디렉토리 한 곳에 모든 파일 모아둠. 하위 모두 검색.
    all_files = [p for p in output_dir.rglob("*") if p.is_file()]
    names = {p.name for p in all_files}
    assert "Dockerfile" in names, f"Dockerfile 미생성: {names}"
    assert "deployment.yaml" in names, f"deployment.yaml 미생성: {names}"

    dockerfile_path = next(p for p in all_files if p.name == "Dockerfile")
    deployment_path = next(p for p in all_files if p.name == "deployment.yaml")

    dockerfile = dockerfile_path.read_text()
    assert "golang:1.22-alpine" in dockerfile
    assert "gcr.io/distroless/static-debian12:nonroot" in dockerfile
    assert 'ENTRYPOINT ["/app/myapp"]' in dockerfile
    assert "USER nonroot" in dockerfile

    deployment = deployment_path.read_text()
    # NFR-04 (r): 생성된 deployment의 runAsUser가 Go defaults(65532)와 일치
    assert "runAsUser: 65532" in deployment
    # NFR-04 (s): writable_paths /tmp만 (Go는 /var/log 불요)
    assert "/tmp" in deployment
