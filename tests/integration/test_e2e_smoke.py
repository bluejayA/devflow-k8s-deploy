"""End-to-end smoke test — 실제 CLI 실행으로 파이프라인 전체 검증.

MagicMock 기반 unit 테스트가 catch 못한 통합 버그를 잡기 위한 layer.

테스트 범주:
  - E2E CLI 실행 + 아티팩트 생성 확인: 1건
  - namespace=None 시 project_dir.name fallback (F-70): 1건
  - BL-022 출력 디렉토리 구조 가드 (manifest vs meta 분리): 1건
  총 3건
"""

from __future__ import annotations

import json
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

    # 생성된 파일 존재 확인 (BL-022: manifest는 manifests/ 서브디렉토리)
    manifests = output_dir / "manifests"
    assert (output_dir / "Dockerfile").exists(), "Dockerfile 미생성"
    assert (manifests / "deployment.yaml").exists(), "manifests/deployment.yaml 미생성"
    assert (manifests / "service.yaml").exists(), "manifests/service.yaml 미생성"
    assert (manifests / "serviceaccount.yaml").exists(), "manifests/serviceaccount.yaml 미생성"
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
    deployment = yaml.safe_load((output_dir / "manifests" / "deployment.yaml").read_text())
    assert deployment["metadata"]["namespace"] == "my-team-api", (
        f"namespace fallback 실패: {deployment['metadata']['namespace']!r}"
    )


def test_e2e_cli_output_layout_separates_manifests_from_meta(tmp_path: Path) -> None:
    """BL-022 (#34) 출력 디렉토리 구조 가드.

    `kubectl apply -f manifests/` 단일 명령으로 적용 가능하도록 K8s 자원
    YAML은 `manifests/` 서브디렉토리에, 메타데이터(summary.json/rationale.md)와
    Dockerfile은 root에 배치. summary.json `files` 목록도 manifests/ prefix
    반영.
    """
    project_dir = tmp_path / "app"
    project_dir.mkdir()
    _make_sample_spring_boot(project_dir)
    output_dir = tmp_path / "k8s-output"

    from scripts.pipeline.orchestrator import main

    exit_code = main(["--project-dir", str(project_dir), "--output-dir", str(output_dir)])
    assert exit_code in (0, 2), f"CLI 실패: exit={exit_code}"

    # K8s 자원 YAML은 manifests/ 서브디렉토리에 있어야 함
    manifests_dir = output_dir / "manifests"
    assert manifests_dir.is_dir(), "manifests/ 서브디렉토리 미생성"
    manifest_files = sorted(p.name for p in manifests_dir.iterdir() if p.is_file())
    expected_manifests = {"deployment.yaml", "service.yaml", "serviceaccount.yaml"}
    assert expected_manifests.issubset(set(manifest_files)), (
        f"manifests/ 누락: 기대 {expected_manifests}, 실제 {manifest_files}"
    )

    # root 레벨에는 manifest 자원 YAML이 없어야 함 (kubectl apply 혼선 방지)
    root_yaml_files = [p.name for p in output_dir.iterdir() if p.is_file() and p.suffix == ".yaml"]
    assert root_yaml_files == [], (
        f"root에 manifest YAML 잔재: {root_yaml_files} — manifests/ 안으로 이동돼야 함"
    )

    # 메타/Dockerfile은 root 그대로
    assert (output_dir / "Dockerfile").is_file(), "Dockerfile은 root에 있어야 함"
    assert (output_dir / "summary.json").is_file(), "summary.json은 root에 있어야 함"
    assert (output_dir / "rationale.md").is_file(), "rationale.md는 root에 있어야 함"

    # summary.json files 목록은 manifests/ prefix 반영
    summary = json.loads((output_dir / "summary.json").read_text())
    files = summary.get("files", [])
    manifest_entries = [f for f in files if f.endswith(".yaml")]
    assert all(f.startswith("manifests/") for f in manifest_entries), (
        f"summary.json files manifest entry는 manifests/ prefix 필요: {manifest_entries}"
    )
