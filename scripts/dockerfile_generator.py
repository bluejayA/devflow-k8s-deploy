"""DockerfileGenerator — multi-stage Dockerfile 생성기 (스택 중립 facade).

책임:
  - 이미지 태그 / 주입 방어 등 스택 무관 보안 검증
  - 템플릿 렌더 위임

템플릿 선택 + Jinja2 컨텍스트 구성은 `StackModule.dockerfile_context()`가 담당한다.
v0.1~v0.4: JVM만 지원. BL-015 (v0.5) 리팩토링으로 Go/Python/Rust 확장 준비.
"""

from __future__ import annotations

from pathlib import Path

from scripts._shared.errors import InvalidImageError
from scripts._shared.image_ref import validate_image_reference
from scripts._shared.text_safety import reject_unsafe_chars
from scripts._shared.types import BuildPlan, ResourceDefaults, StackDetectResult, UserInputs
from scripts.stacks.base import StackModule
from scripts.template_renderer import TemplateRenderer


def _validate_command(value: str, field_name: str) -> None:
    """Dockerfile RUN/COPY에 주입되는 문자열에 개행/NUL 차단.

    scripts._shared.text_safety.reject_unsafe_chars에 위임.

    Args:
        value: 검증할 문자열.
        field_name: 오류 메시지에 포함될 필드명.

    Raises:
        InvalidImageError: 개행 또는 NUL 문자가 포함된 경우.
    """
    reject_unsafe_chars(
        value,
        field_name,
        exc_type=InvalidImageError,
        message_prefix="Dockerfile 주입 방어",
    )


class DockerfileGenerator:
    """multi-stage Dockerfile 생성 서비스."""

    def __init__(self, renderer: TemplateRenderer) -> None:
        self._renderer = renderer

    def generate(
        self,
        build_plan: BuildPlan,
        inputs: UserInputs,
        defaults: ResourceDefaults,  # noqa: ARG002  (v0.1.0 미사용 — v0.2+ writable_paths VOLUME 용 예약)
        *,
        stack_module: StackModule,
        detect_result: StackDetectResult,
        project_dir: Path | None = None,
    ) -> str:
        """Dockerfile 문자열 반환 (스택 중립).

        facade 책임:
          - 이미지 태그 검증 + 주입 방어 (스택 무관)
          - stack_module.dockerfile_context() 로 스택별 컨텍스트 위임
          - 템플릿 렌더 (키는 stack_module.template_name)

        Args:
            build_plan: 빌드 계획 (이미지, 빌드 명령, 아티팩트 경로).
            inputs: 사용자 입력 (앱 이름, 포트 등).
            defaults: 리소스 기본값 (v0.1.0 미사용, v0.2+ writable_paths VOLUME 확장 예약).
            stack_module: 현재 스택 모듈 (JvmStackModule 등).
            detect_result: StackModule.detect() 결과.
            project_dir: 프로젝트 루트 — 스택별 힌트 감지(Gradle 디렉토리 등)에 사용.

        Returns:
            정규화된 Dockerfile 문자열.

        Raises:
            InvalidImageError: builder_image 또는 runner_image에 'latest' 태그 사용 시,
                또는 이미지 참조 형식 위반, build_cmd/artifact_path에 제어문자 포함 시.
        """
        # Fail-fast: 이미지 태그 검증 (allowlist 정규식 + latest 명시 거부)
        self._validate_image_tag(build_plan.builder_image)
        self._validate_image_tag(build_plan.runner_image)

        # Fail-fast: Dockerfile 명령 주입 방어
        _validate_command(build_plan.build_cmd, "build_cmd")
        _validate_command(build_plan.artifact_path, "artifact_path")

        # 스택별 컨텍스트 위임
        context = stack_module.dockerfile_context(
            build_plan=build_plan,
            detect_result=detect_result,
            inputs=inputs,
            project_dir=project_dir,
        )

        return self._renderer.render_dockerfile(stack_module.template_name, context)

    def generate_dockerignore(self) -> str:
        """`.dockerignore` 내용 반환 (Docker 20.10+ `Dockerfile.dockerignore` 규약).

        v0.2.0 P1-b: `COPY . .`로 복원하면서 context pollution(.git/, build/,
        k8s-output/, .env 등) 방어를 전담하는 독립 아티팩트. Dockerfile 바로 옆에
        `Dockerfile.dockerignore` 이름으로 배치하면 `docker build -f <dir>/Dockerfile
        <ctx>` 시 자동 적용.
        """
        return self._renderer.render_dockerignore()

    def _validate_image_tag(self, image: str) -> None:
        """이미지 참조 문자열을 엄격 allowlist로 검증.

        내부 구현은 scripts._shared.image_ref.validate_image_reference에 위임.
        기존 테스트 호환을 위해 wrapper method로 유지.

        Args:
            image: 검증할 이미지 레퍼런스 문자열.

        Raises:
            InvalidImageError: 형식 위반, latest 태그, 태그/digest 누락 시.
        """
        validate_image_reference(image)
