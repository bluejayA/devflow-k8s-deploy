"""StackModule Protocol — 스택별 5 메서드 계약 (PEP 544).

v0.1.0 구현체: JvmStackModule (scripts.stacks.jvm)
v0.2+: Go / Python / React 슬롯 예정
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
)

ResourceHint = Literal["small", "medium", "large"]


@runtime_checkable
class StackModule(Protocol):
    """스택 감지 + 빌드/프로브/리소스 계획 계약.

    모든 메서드는 실패 시 스택 전용 예외를 raise한다.
    ProjectAnalyzer가 catch하여 gaps에 기록.
    """

    name: ClassVar[str]  # 예: "jvm", "go", "python", "react"

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
