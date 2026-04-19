"""DockerfileGenerator — multi-stage Dockerfile 생성기.

JDK builder → JRE runner 2단계 구조. 비root 사용자. `latest` 금지 검증.
Gradle/Maven 의존성 캐시 레이어 최적화(F-25). 보안 근거 주석(F-24).
"""

from __future__ import annotations

from typing import Literal

from scripts._shared.errors import InvalidImageError
from scripts._shared.types import BuildPlan, ResourceDefaults, UserInputs
from scripts.template_renderer import TemplateRenderer


class DockerfileGenerator:
    """multi-stage Dockerfile 생성 서비스."""

    def __init__(self, renderer: TemplateRenderer) -> None:
        self._renderer = renderer

    def generate(
        self,
        build_plan: BuildPlan,
        inputs: UserInputs,
        defaults: ResourceDefaults,
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
            defaults: 리소스 기본값 (현재 미사용, 확장성 위해 수용).

        Returns:
            정규화된 Dockerfile 문자열.

        Raises:
            InvalidImageError: builder_image 또는 runner_image에 'latest' 태그 사용 시.
        """
        # Fail-fast: 이미지 태그 검증
        self._validate_image_tag(build_plan.builder_image)
        self._validate_image_tag(build_plan.runner_image)

        build_system = _detect_build_system(build_plan.build_cmd)

        context: dict[str, object] = {
            "artifact_path": build_plan.artifact_path,
            "build_cmd": build_plan.build_cmd,
            "build_system": build_system,
            "builder_image": build_plan.builder_image,
            "port": inputs.port,
            "runner_image": build_plan.runner_image,
        }

        return self._renderer.render_dockerfile("jvm", context)

    def _validate_image_tag(self, image: str) -> None:
        """latest 또는 태그 누락 시 raise InvalidImageError.

        규칙:
          - ``image:latest`` → InvalidImageError (재현성 위반)
          - 태그 없음 (`:` 미포함) → InvalidImageError (암묵적 latest와 동일)
          - ``@sha256:`` digest pinning → PASS (태그 없어도 허용)

        Args:
            image: 검증할 이미지 레퍼런스 문자열.

        Raises:
            InvalidImageError: 'latest' 태그 또는 태그 누락 시.
        """
        # digest pinning은 허용: image@sha256:...
        if "@sha256:" in image:
            return

        if ":" not in image:
            raise InvalidImageError(
                f"이미지 태그가 명시되지 않음: {image!r} — "
                "명시적 태그(예: eclipse-temurin:21-jre-alpine) 또는 "
                "digest(@sha256:...)를 사용하세요."
            )

        if image.endswith(":latest"):
            raise InvalidImageError(
                f"이미지 태그 'latest' 사용 금지: {image!r} — "
                "재현성과 공급망 공격 방지를 위해 고정 태그를 사용하세요. "
                "(F-23, NFR-SEC)"
            )


def _detect_build_system(build_cmd: str) -> Literal["gradle", "maven"]:
    """빌드 커맨드 기반 빌드 시스템 자동 감지.

    Args:
        build_cmd: 빌드 명령어 문자열 (예: ``./gradlew bootJar``, ``mvn package``).

    Returns:
        'gradle' 또는 'maven'. 감지 불가 시 'gradle' 기본값.
    """
    lower = build_cmd.lower()
    if "mvn" in lower or "maven" in lower:
        return "maven"
    # gradle / gradlew → gradle (기본 fallback 포함)
    return "gradle"
