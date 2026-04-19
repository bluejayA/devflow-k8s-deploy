"""DockerfileGenerator — multi-stage Dockerfile 생성기.

JDK builder → JRE runner 2단계 구조. 비root 사용자. `latest` 금지 검증.
Gradle/Maven 의존성 캐시 레이어 최적화(F-25). 보안 근거 주석(F-24).
"""

from __future__ import annotations

import re
from typing import Literal

from scripts._shared.errors import InvalidImageError
from scripts._shared.types import BuildPlan, ResourceDefaults, UserInputs
from scripts.template_renderer import TemplateRenderer

# OCI image reference allowlist — 개행/공백/제어문자 완전 차단 (NFR-SEC)
# - repo: [a-z0-9][a-z0-9._/-]{0,253}
# - tag (선택): [A-Za-z0-9_][A-Za-z0-9_.-]{0,127}
# - digest (선택): @sha256:<64 hex>
# - 태그 또는 digest 중 최소 하나 필수 (generate 단계에서 추가 검증)
_IMAGE_REF_RE = re.compile(
    r"^(?P<repo>[a-z0-9][a-z0-9._/\-]{0,253})"
    r"(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}))?"
    r"(?:@sha256:(?P<digest>[0-9a-f]{64}))?$"
)

# Dockerfile RUN/COPY에 주입될 수 있는 위험 문자
_UNSAFE_COMMAND_CHARS = ("\n", "\r", "\x00")


def _validate_command(value: str, field_name: str) -> None:
    """Dockerfile RUN/COPY에 주입되는 문자열에 개행/NUL 차단.

    Args:
        value: 검증할 문자열.
        field_name: 오류 메시지에 포함될 필드명.

    Raises:
        InvalidImageError: 개행 또는 NUL 문자가 포함된 경우.
    """
    for ch in _UNSAFE_COMMAND_CHARS:
        if ch in value:
            raise InvalidImageError(
                f"Dockerfile 주입 방어: {field_name}에 개행 또는 제어문자 포함 금지: "
                f"{value!r}"
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
        """이미지 참조 문자열을 엄격 allowlist로 검증.

        허용:
          - ``alpine:3.19`` (태그)
          - ``alpine:3.19@sha256:<64 hex>`` (태그 + digest)
          - ``alpine@sha256:<64 hex>`` (digest only)

        거부 (InvalidImageError):
          - ``alpine`` (태그/digest 둘 다 없음)
          - ``alpine:latest`` (latest 태그 — 명시 거부)
          - ``alpine:latest@sha256:...`` (digest 우회 시도)
          - ``alpine\\nUSER root`` (개행 — 인젝션 시도)
          - digest가 64 hex가 아닌 값 (예: ``alpine@sha256:abc``)
          - 정규식 allowlist 위반 (공백/제어문자/비허용 문자)

        Args:
            image: 검증할 이미지 레퍼런스 문자열.

        Raises:
            InvalidImageError: 형식 위반, latest 태그, 태그/digest 누락 시.
        """
        # NFR-SEC: 개행/제어문자는 fullmatch 정규식이 차단
        match = _IMAGE_REF_RE.fullmatch(image)
        if not match:
            raise InvalidImageError(
                f"이미지 참조 형식이 유효하지 않음: {image!r}. "
                f"예: 'eclipse-temurin:21-jre-alpine' 또는 '<repo>@sha256:<64 hex digest>'"
            )
        tag = match.group("tag")
        digest = match.group("digest")
        # 태그 또는 digest 최소 하나 필수
        if tag is None and digest is None:
            raise InvalidImageError(
                f"이미지 태그 또는 digest 중 하나는 필수: {image!r}. "
                "F-23 재현성/공급망 보안 — latest 태그 대신 고정 태그 또는 digest pinning 사용."
            )
        # latest 태그 명시 거부 (digest 존재 여부와 무관)
        if tag == "latest":
            raise InvalidImageError(
                f"이미지 태그 'latest' 사용 금지 (F-23): {image!r}. "
                "구체 태그(예: ':3.19') 또는 digest pinning 사용."
            )


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
