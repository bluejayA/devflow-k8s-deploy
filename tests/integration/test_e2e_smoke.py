"""End-to-end smoke test — 실제 CLI 실행으로 파이프라인 전체 검증.

MagicMock 기반 unit 테스트가 catch 못한 통합 버그를 잡기 위한 layer.

테스트 범주:
  - E2E CLI 실행 + 아티팩트 생성 확인: 1건
  - namespace=None 시 project_dir.name fallback (F-70): 1건
  총 2건
"""

from __future__ import annotations

from pathlib import Path

import yaml


def _make_sample_spring_boot(project_dir: Path) -> None:
    """샘플 Spring Boot 3 (Gradle KTS) 프로젝트 생성."""
    (project_dir / "src/main/resources").mkdir(parents=True)
    (project_dir / "build.gradle.kts").write_text(
        'plugins {\n'
        '    id("org.springframework.boot") version "3.2.0"\n'
        '    kotlin("jvm") version "1.9.0"\n'
        '}\n'
        'dependencies {\n'
        '    implementation("org.springframework.boot:spring-boot-starter-web")\n'
        '    implementation("org.springframework.boot:spring-boot-starter-actuator")\n'
        '}\n'
    )
    (project_dir / "settings.gradle.kts").write_text('rootProject.name = "smoke-sample"\n')
    (project_dir / "src/main/resources/application.yml").write_text(
        'server:\n  port: 8080\n'
        'management:\n  endpoints:\n    web:\n      exposure:\n        include: health\n'
    )


def test_e2e_cli_generates_artifacts_on_spring_boot_project(tmp_path: Path) -> None:
    """실제 CLI 실행 — Spring Boot 3 샘플 프로젝트 → k8s 배포 파일 생성.

    주의: tests/integration/conftest.py의 autouse subprocess spy가 적용됨.
    kubectl dry-run 등 subprocess는 returncode=0 spy로 대체.
    """
    project_dir = tmp_path / "app"
    project_dir.mkdir()
    _make_sample_spring_boot(project_dir)

    output_dir = tmp_path / "k8s-output"

    from scripts.pipeline.orchestrator import main

    exit_code = main(["--project-dir", str(project_dir), "--output-dir", str(output_dir)])

    # smoke: exit code가 비정상(1) 아니어야 함 (0=PASS, 2=WARN 허용)
    assert exit_code in (0, 2), f"CLI 실패: exit={exit_code}"

    # 생성된 파일 존재 확인
    assert (output_dir / "Dockerfile").exists(), "Dockerfile 미생성"
    assert (output_dir / "deployment.yaml").exists(), "deployment.yaml 미생성"
    assert (output_dir / "service.yaml").exists(), "service.yaml 미생성"
    assert (output_dir / "serviceaccount.yaml").exists(), "serviceaccount.yaml 미생성"
    assert (output_dir / "rationale.md").exists(), "rationale.md 미생성"
    assert (output_dir / "summary.json").exists(), "summary.json 미생성"


def test_e2e_cli_namespace_falls_back_to_project_dir_name(tmp_path: Path) -> None:
    """namespace 미설정 시 project_dir.name으로 fallback (F-70 4단계 조회).

    BUILTIN_DEFAULTS: namespace=None — 직접 str() 변환하면 'None'이 되어
    ManifestGenerator DNS-1123 검증에 걸리는 버그를 재현한 후 수정 확인.
    """
    project_dir = tmp_path / "my-team-api"  # DNS-1123 호환 이름
    project_dir.mkdir()
    _make_sample_spring_boot(project_dir)

    output_dir = tmp_path / "out"

    from scripts.pipeline.orchestrator import main

    exit_code = main(["--project-dir", str(project_dir), "--output-dir", str(output_dir)])

    assert exit_code in (0, 2), f"CLI 실패 (namespace fallback 버그): exit={exit_code}"

    # namespace가 'my-team-api'여야 함
    deployment = yaml.safe_load((output_dir / "deployment.yaml").read_text())
    assert deployment["metadata"]["namespace"] == "my-team-api", (
        f"namespace fallback 실패: {deployment['metadata']['namespace']!r}"
    )
