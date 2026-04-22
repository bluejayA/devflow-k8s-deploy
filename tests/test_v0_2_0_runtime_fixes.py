"""v0.2.0 패치: 런타임 배포 이슈 수정 검증.

v0.1.0 릴리즈는 샘플 배포 검증 중 2건의 런타임 결함 추가 발견:

- B1 (Critical): deployment.yaml의 `image:`가 builder runner 이미지를 그대로 받음
                 (예: `eclipse-temurin:21-jre-alpine`) → 배포 시 CrashLoopBackOff 확정.
                 `config.build.image_tag`(app 이미지 태그, default `app:0.2.0`)를
                 deployment 및 OutputPackager에 전달해야 함.
- B2 (Critical): deployment.tmpl에 `imagePullPolicy` 미지정 → 태그 재푸시 시 갱신 이슈.
- B3 (Important): `UserInputs.resource_hint`가 수집되기만 하고 `ResourceDefaults`에
                  반영되지 않음 (`StackModule.defaults()`가 인자 없음). small/medium/large
                  선택이 silent discard → 사용자 UX 버그.

본 파일은 v0.2.0 수정 후 상태를 검증하는 RED 테스트.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from scripts._shared.types import (
    BuildPlan,
    ResourceDefaults,
    UserInputs,
)
from scripts.config_loader import ConfigLoader
from scripts.manifest_generator import ManifestGenerator
from scripts.pipeline.orchestrator import SkillPipeline
from scripts.project_analyzer import ProjectAnalyzer
from scripts.stacks.jvm import JvmStackModule
from scripts.template_renderer import TemplateRenderer

# ---------------------------------------------------------------------------
# B1 + B2: deployment.yaml image wiring + imagePullPolicy
# ---------------------------------------------------------------------------


def _make_gradle_sample(root: Path) -> Path:
    """최소 Gradle Spring Boot 3 샘플 — detect/build_plan 모두 통과 가능."""
    (root / "build.gradle.kts").write_text(
        "plugins {\n"
        '    id("org.springframework.boot") version "3.3.5"\n'
        '    kotlin("jvm") version "2.0.21"\n'
        "}\n"
        "dependencies {\n"
        '    implementation("org.springframework.boot:spring-boot-starter-web")\n'
        '    implementation("org.springframework.boot:spring-boot-starter-actuator")\n'
        "}\n",
        encoding="utf-8",
    )
    (root / "settings.gradle.kts").write_text('rootProject.name = "s"\n', encoding="utf-8")
    (root / "src" / "main" / "resources").mkdir(parents=True)
    return root


def test_orchestrator_passes_image_tag_to_deployment(tmp_path: Path) -> None:
    """_generate_step3가 build.image_tag를 manifest_generator에 전달해야 함.

    MagicMock 기반: generate_deployment 호출 인자의 `image=` 값이
    `config.build.image_tag` 와 일치해야 한다.
    """
    from tests.test_orchestrator import _make_analysis_result, _make_deps

    deps, mocks = _make_deps(
        config_raw={
            "build": {"engine": "skip", "image_tag": "myregistry.example.com/my-app:1.2.3"},
            "output": {"on_exists": "overwrite"},
        }
    )
    # 빌더 runner와 앱 이미지를 분리하여 회귀 잡음
    base = _make_analysis_result()
    analysis = replace(
        base,
        build_plan=BuildPlan(
            builder_image="gradle:jdk21-alpine",
            runner_image="eclipse-temurin:21-jre-alpine",  # MUST NOT appear in deployment
            build_cmd=base.build_plan.build_cmd,
            artifact_path=base.build_plan.artifact_path,
        ),
    )
    mocks["project_analyzer"].analyze.return_value = analysis

    SkillPipeline(deps).run(tmp_path / "p", tmp_path / "o")

    gen_deployment: MagicMock = mocks["manifest_generator"].generate_deployment
    assert gen_deployment.called

    passed_image = gen_deployment.call_args.kwargs.get("image")
    assert passed_image == "myregistry.example.com/my-app:1.2.3"
    assert passed_image != "eclipse-temurin:21-jre-alpine", (
        "runner_image는 앱 배포 이미지가 아님 — v0.1.0의 CrashLoop 버그 회귀"
    )


def test_orchestrator_default_image_tag_when_build_section_absent(tmp_path: Path) -> None:
    """build.image_tag 미지정 시 default `app:0.2.0` 사용."""
    from tests.test_orchestrator import _make_deps

    deps, mocks = _make_deps(
        config_raw={"build": {"engine": "skip"}, "output": {"on_exists": "overwrite"}}
    )

    SkillPipeline(deps).run(tmp_path / "p", tmp_path / "o")

    gen_deployment: MagicMock = mocks["manifest_generator"].generate_deployment
    passed_image = gen_deployment.call_args.kwargs.get("image")
    assert passed_image != "eclipse-temurin:21-jre-alpine"
    assert passed_image == "app:0.2.0"


def test_deployment_manifest_includes_image_pull_policy() -> None:
    """deployment.yaml에 imagePullPolicy 명시 필요.

    k8s 기본은 `:latest`→Always, 그 외→IfNotPresent이지만 tag mutation 방어를 위해 명시.
    """
    from tests.test_orchestrator import _make_analysis_result

    gen = ManifestGenerator(TemplateRenderer(Path(__file__).parent.parent / "templates"))
    inputs = UserInputs(
        app_name="x",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("/tmp/o"),
        resource_hint="medium",
    )
    analysis = _make_analysis_result()
    yaml_str = gen.generate_deployment(
        inputs,
        analysis,
        analysis.defaults,
        analysis.probe_config,
        image="myregistry/app:1.0.0",
    )

    doc = yaml.safe_load(yaml_str)
    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert "imagePullPolicy" in container
    assert container["imagePullPolicy"] in {"Always", "IfNotPresent", "Never"}


# ---------------------------------------------------------------------------
# B3: resource_hint tiering
# ---------------------------------------------------------------------------


class TestResourceHintTiering:
    """JvmStackModule.defaults(resource_hint)가 tier별 다른 값을 반환해야 함."""

    def test_defaults_accepts_resource_hint(self) -> None:
        module = JvmStackModule()
        # 새 시그니처: defaults(resource_hint)
        small = module.defaults("small")
        medium = module.defaults("medium")
        large = module.defaults("large")

        assert isinstance(small, ResourceDefaults)
        assert isinstance(medium, ResourceDefaults)
        assert isinstance(large, ResourceDefaults)

    def test_tiers_are_monotonic(self) -> None:
        """small < medium < large for both cpu_limit and memory_limit."""
        module = JvmStackModule()
        small = module.defaults("small")
        medium = module.defaults("medium")
        large = module.defaults("large")

        # cpu 단위 비교: "Xm" 정규화
        def cpu_m(v: str) -> int:
            return int(v.rstrip("m")) if v.endswith("m") else int(v) * 1000

        def mem_mi(v: str) -> int:
            if v.endswith("Mi"):
                return int(v[:-2])
            if v.endswith("Gi"):
                return int(v[:-2]) * 1024
            raise ValueError(f"unknown memory unit: {v}")

        assert cpu_m(small.cpu_limit) < cpu_m(medium.cpu_limit) < cpu_m(large.cpu_limit)
        assert mem_mi(small.memory_limit) < mem_mi(medium.memory_limit) < mem_mi(large.memory_limit)

    def test_analyze_respects_resource_hint(self, tmp_path: Path) -> None:
        """ProjectAnalyzer.analyze()가 resource_hint를 받아 AnalysisResult.defaults에 반영."""
        _make_gradle_sample(tmp_path)

        cl = ConfigLoader()
        config = cl.load(tmp_path)
        analyzer = ProjectAnalyzer(
            config_loader=cl,
            stack_registry={"jvm": JvmStackModule()},
            prompt_callback=None,
        )

        # 새 시그니처: analyze(project_dir, config, resource_hint)
        result_small = analyzer.analyze(tmp_path, config, resource_hint="small")
        result_large = analyzer.analyze(tmp_path, config, resource_hint="large")

        assert result_small.defaults.cpu_limit != result_large.defaults.cpu_limit, (
            "analyze가 resource_hint에 따라 defaults를 다르게 반환해야 함"
        )
