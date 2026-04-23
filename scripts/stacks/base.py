"""StackModule Protocol — 스택별 계약 (PEP 544).

v0.1.0 구현체: JvmStackModule (scripts.stacks.jvm)
v0.2+: Go / Python / React 슬롯 예정

Dockerfile 생성 책임은 v0.5 (BL-015)부터 StackModule로 이관되었다:
  - template_name: 템플릿 파일명 키 (예: "jvm", "go", "python")
  - dockerfile_context(...): 해당 템플릿 렌더에 필요한 변수 딕셔너리
DockerfileGenerator는 스택 중립 facade로서 보안 검증만 담당하고,
템플릿 선택 + 컨텍스트 구성은 각 스택 모듈이 캡슐화한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal

from typing_extensions import Protocol, runtime_checkable

from scripts._shared.types import (
    BuildPlan,
    ProbeConfig,
    ResourceDefaults,
    StackDetectResult,
    UserInputs,
)

ResourceHint = Literal["small", "medium", "large"]


@runtime_checkable
class StackModule(Protocol):
    """스택 감지 + 빌드/프로브/리소스/Dockerfile 계획 계약.

    모든 메서드는 실패 시 스택 전용 예외를 raise한다.
    ProjectAnalyzer가 catch하여 gaps에 기록.
    """

    name: ClassVar[str]  # 예: "jvm", "go", "python", "react"
    template_name: ClassVar[str]  # Dockerfile 템플릿 키 (templates/dockerfile/{name}.tmpl)

    def detect(self, project_dir: Path) -> StackDetectResult | None:
        """이 스택인지 감지.

        Returns:
            StackDetectResult — 감지 성공 시.
            None — 이 스택이 아닌 경우.
        """
        ...

    def build_plan(self, detect_result: StackDetectResult) -> BuildPlan:
        """detect_result 기반 BuildPlan 생성.

        v0.2+에서 BuildPlan(stages: list[Stage])로 일반화 예정 (백로그).
        """
        ...

    def probe_plan(self, detect_result: StackDetectResult) -> ProbeConfig:
        """liveness / readiness ProbeConfig 생성."""
        ...

    def defaults(self, resource_hint: ResourceHint) -> ResourceDefaults:
        """스택 기본 리소스 설정 + writable_paths.

        resource_hint: 사용자가 STEP 1에서 선택한 규모 등급 (small/medium/large).
                       각 스택은 tier별 cpu/memory 값을 차등 반환해야 한다.
        """
        ...

    def artifact_locator(
        self, detect_result: StackDetectResult, project_dir: Path
    ) -> list[Path]:
        """생성된 jar/binary/static asset 경로 후보.

        Dockerfile COPY 소스로 사용.
        """
        ...

    def dockerfile_context(
        self,
        *,
        build_plan: BuildPlan,
        detect_result: StackDetectResult,
        inputs: UserInputs,
        project_dir: Path | None,
    ) -> dict[str, object]:
        """Dockerfile Jinja2 템플릿 렌더에 주입할 컨텍스트.

        스택별 동적 힌트(예: JVM의 has_gradle_dir, Python의 venv_path)를
        이 메서드 안에서 project_dir을 관찰해 결정한다.
        """
        ...
