"""DockerfileGenerator — multi-stage Dockerfile 생성기.

JDK builder → JRE runner 2단계 구조. 비root 사용자. `latest` 금지 검증.
Gradle/Maven 의존성 캐시 레이어 최적화(F-25). 보안 근거 주석(F-24).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from scripts._shared.errors import InvalidImageError
from scripts._shared.image_ref import validate_image_reference
from scripts._shared.text_safety import reject_unsafe_chars
from scripts._shared.types import BuildPlan, ResourceDefaults, UserInputs
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
        project_dir: Path | None = None,
    ) -> str:
        """Dockerfile 문자열 반환.

        포함:
          - FROM {builder_image} AS builder + 의존성 캐시 레이어 + 소스 복사 + build_cmd
          - FROM {runner_image} + RUN groupadd/useradd appuser + COPY --from=builder --chown
          - USER appuser (ENTRYPOINT 직전)
          - HEALTHCHECK는 v0.1.0 미포함 (probes로 대체)
        보안 주석:
          - # 비root 사용자 — 컨테이너 탈출 공격 시 호스트 root 권한 차단
          - # latest 태그 금지 — 재현성 + 공급망 공격 방지
          - # COPY --chown — 임의 사용자 ID 충돌 방지

        Args:
            build_plan: 빌드 계획 (이미지, 빌드 명령, 아티팩트 경로).
            inputs: 사용자 입력 (앱 이름, 포트 등).
            defaults: 리소스 기본값 (v0.1.0 미사용, v0.2+ writable_paths VOLUME 확장 예약).

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

        build_system = _detect_build_system(build_plan.build_cmd)

        # v0.2.0 P1-a: Gradle Version Catalog(`gradle/libs.versions.toml`) +
        # convention plugins 지원 — project_dir에 `gradle/` 있으면 dep cache 레이어에
        # 포함. 없으면 생략(없는 상태에서 COPY하면 docker build 실패).
        has_gradle_dir = False
        if project_dir is not None:
            gradle_path = project_dir / "gradle"
            has_gradle_dir = gradle_path.is_dir()

        context: dict[str, object] = {
            "artifact_path": build_plan.artifact_path,
            "build_cmd": build_plan.build_cmd,
            "build_system": build_system,
            "builder_image": build_plan.builder_image,
            "has_gradle_dir": has_gradle_dir,
            "port": inputs.port,
            "runner_image": build_plan.runner_image,
        }

        return self._renderer.render_dockerfile("jvm", context)

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


def _detect_build_system(build_cmd: str) -> Literal["gradle", "maven"]:
    """빌드 커맨드를 공백/구분자 기준 토큰 분해 후 정확 매칭.

    Args:
        build_cmd: 빌드 명령어 문자열 (예: ``./gradlew bootJar``, ``mvn package``).

    Returns:
        'gradle' 또는 'maven'. 감지 불가 시 'gradle' 기본값.
    """
    maven_tokens = {"mvn", "mvnw", "./mvnw", "mvn.cmd", "maven"}
    gradle_tokens = {"gradle", "gradlew", "./gradlew", "gradle.cmd"}

    for tok in build_cmd.lower().split():
        # 경로 prefix 제거 (예: "/usr/bin/mvn" → "mvn")
        base = tok.rsplit("/", 1)[-1]
        if base in maven_tokens:
            return "maven"

    for tok in build_cmd.lower().split():
        base = tok.rsplit("/", 1)[-1]
        if base in gradle_tokens:
            return "gradle"

    # 감지 불가 시 gradle 기본값
    return "gradle"
