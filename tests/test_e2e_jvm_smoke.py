"""BL-001 Phase 8 — JVM 스택 E2E 회귀 (NFR-04 (r)(s) JVM 측 보강).

Go E2E와 같은 main() 경로로 JVM 프로젝트를 처리해 다음 정합성 확인:
- runAsUser==1000 (JVM defaults)
- writable_paths==["/tmp", "/var/log"] (JVM defaults)
- builder=gradle:jdk21-alpine, runner=eclipse-temurin:21-jre-alpine

Phase 3에서 manifest 하드코딩을 제거한 뒤 JVM 경로가 자기 defaults를 그대로
유지하는지 확인하는 회귀 가드. Go 작업이 JVM 동작에 회귀를 일으키지 않음을 보장.
"""

from __future__ import annotations

from pathlib import Path

from scripts.pipeline.orchestrator import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_spring_boot_project(project_dir: Path) -> None:
    _write(
        project_dir / "build.gradle.kts",
        """
plugins {
    id("org.springframework.boot") version "3.2.0"
}
""".lstrip(),
    )
    _write(
        project_dir / "src/main/resources/application.yml",
        "server:\n  port: 8080\n",
    )
    _write(
        project_dir / ".devflow-k8s-deploy.yml",
        """
app:
  name: spring-app
  port: 8080
  exposure: ClusterIP
  resource_hint: medium
build:
  engine: skip
""".lstrip(),
    )


def test_jvm_e2e_uid_and_writable_paths(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    output_dir = tmp_path / "k8s-output"
    _make_spring_boot_project(project_dir)

    exit_code = main(
        ["--project-dir", str(project_dir), "--output-dir", str(output_dir)]
    )
    assert exit_code in (0, 2), f"unexpected exit code {exit_code}"

    all_files = [p for p in output_dir.rglob("*") if p.is_file()]
    dockerfile = next(p for p in all_files if p.name == "Dockerfile").read_text()
    deployment = next(p for p in all_files if p.name == "deployment.yaml").read_text()

    # NFR-04 (r): JVM defaults.run_as_user == 1000
    assert "runAsUser: 1000" in deployment
    # Go(65532)와 섞이지 않음 (JVM은 1000 유지)
    assert "65532" not in deployment

    # NFR-04 (s): writable_paths == [/tmp, /var/log]
    assert "/tmp" in deployment
    assert "/var/log" in deployment

    # JVM stack 흔적 (Phase 6/7의 Go가 JVM 경로 회귀 없음)
    assert "gradle:jdk21-alpine" in dockerfile
    assert "eclipse-temurin:21-jre-alpine" in dockerfile
    assert "USER appuser" in dockerfile
