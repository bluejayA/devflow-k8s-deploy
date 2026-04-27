"""ProjectAnalyzer Go stack auto-detection (BL-001 Phase 7, F-15/F-16/F-17).

시나리오:
- Go-only 프로젝트 → analyzer.stack == "go"
- JVM + Go 공존 → JVM 우선 (registry 등록 순서)
- 빈 디렉토리 → UnknownStackError (기존 동작 유지)
- forced_stack="go" + go.mod 있음 → 정상
- forced_stack="go" + go.mod 없음 → UnknownStackError
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from scripts._shared.errors import UnknownStackError
from scripts._shared.types import (
    ResolvedConfig,
    StackDecision,
    UserInputs,
)
from scripts.config_loader import ConfigLoader
from scripts.project_analyzer import ProjectAnalyzer
from scripts.stacks.go import GoStackModule
from scripts.stacks.jvm import JvmStackModule


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_resolved_config(raw: dict[str, Any] | None = None) -> ResolvedConfig:
    if raw is None:
        raw = {"stack": "auto"}
    return ResolvedConfig(
        raw=raw,
        source_map={"stack": "builtin_default"},
        warnings=[],
        layer_raws={},
    )


def _make_loader_auto() -> ConfigLoader:
    loader = MagicMock(spec=ConfigLoader)
    loader.stack_decision.return_value = StackDecision(
        forced_stack=None, source="auto"
    )
    loader.resolve_stack_config.return_value = {}
    return loader


def _make_loader_forced(stack: str) -> ConfigLoader:
    loader = MagicMock(spec=ConfigLoader)
    loader.stack_decision.return_value = StackDecision(
        forced_stack=stack, source="project_config"
    )
    loader.resolve_stack_config.return_value = {}
    return loader


def _go_only_project(tmp_path: Path) -> Path:
    _write(tmp_path / "go.mod", "module example.com/svc\n\ngo 1.22\n")
    _write(tmp_path / "main.go", "package main\nfunc main() {}\n")
    return tmp_path


def _spring_boot_project(tmp_path: Path) -> Path:
    _write(
        tmp_path / "build.gradle.kts",
        'plugins { id("org.springframework.boot") version "3.2.0" }\n',
    )
    _write(
        tmp_path / "src/main/resources/application.yml",
        "server:\n  port: 8080\n",
    )
    return tmp_path


def _make_inputs(app_name: str = "myapp") -> UserInputs:
    return UserInputs(
        app_name=app_name,
        port=8080,
        exposure="ClusterIP",
        namespace="default",
        output_dir=Path("/tmp/out"),
        resource_hint="medium",
    )


# ──────────────────────────────────────────────────────────────────────────────
# F-15 + F-16: 자동 감지
# ──────────────────────────────────────────────────────────────────────────────


def test_auto_detects_go_only_project(tmp_path: Path) -> None:
    """go.mod만 있는 프로젝트 → stack=go (auto)."""
    _go_only_project(tmp_path)
    analyzer = ProjectAnalyzer(
        config_loader=_make_loader_auto(),
        stack_registry={"jvm": JvmStackModule(), "go": GoStackModule()},
    )
    result = analyzer.analyze(
        tmp_path, _make_resolved_config(), inputs=_make_inputs()
    )
    assert result.stack == "go"
    assert result.detect_result.framework == "go-generic"
    assert result.build_plan.builder_image == "golang:1.22-alpine"


def test_jvm_takes_priority_when_both_exist(tmp_path: Path) -> None:
    """JVM + Go 공존 시 JVM 우선 (registry 등록 순서, F-16)."""
    _spring_boot_project(tmp_path)
    _write(tmp_path / "go.mod", "module example.com/x\ngo 1.22\n")
    _write(tmp_path / "main.go", "package main\nfunc main() {}\n")

    analyzer = ProjectAnalyzer(
        config_loader=_make_loader_auto(),
        stack_registry={"jvm": JvmStackModule(), "go": GoStackModule()},
    )
    result = analyzer.analyze(
        tmp_path, _make_resolved_config(), inputs=_make_inputs()
    )
    assert result.stack == "jvm"


def test_empty_dir_still_raises_unknown_stack(tmp_path: Path) -> None:
    """F-17: 전 스택 detect 실패 → 기존 UnknownStackError 유지."""
    analyzer = ProjectAnalyzer(
        config_loader=_make_loader_auto(),
        stack_registry={"jvm": JvmStackModule(), "go": GoStackModule()},
    )
    with pytest.raises(UnknownStackError):
        analyzer.analyze(
            tmp_path, _make_resolved_config(), inputs=_make_inputs()
        )


def test_forced_go_with_go_mod(tmp_path: Path) -> None:
    """forced_stack=go + go.mod 있음 → Go 사용."""
    _go_only_project(tmp_path)
    analyzer = ProjectAnalyzer(
        config_loader=_make_loader_forced("go"),
        stack_registry={"jvm": JvmStackModule(), "go": GoStackModule()},
    )
    result = analyzer.analyze(
        tmp_path, _make_resolved_config({"stack": "go"}), inputs=_make_inputs()
    )
    assert result.stack == "go"


def test_forced_go_without_go_mod_raises(tmp_path: Path) -> None:
    """forced_stack=go + go.mod 없음 → UnknownStackError."""
    analyzer = ProjectAnalyzer(
        config_loader=_make_loader_forced("go"),
        stack_registry={"jvm": JvmStackModule(), "go": GoStackModule()},
    )
    with pytest.raises(UnknownStackError):
        analyzer.analyze(
            tmp_path, _make_resolved_config({"stack": "go"}), inputs=_make_inputs()
        )


def test_orchestrator_registers_go(tmp_path: Path) -> None:
    """F-15: _build_default_dependencies가 Go를 registry에 등록한다."""
    from scripts.pipeline.orchestrator import _build_default_dependencies

    deps = _build_default_dependencies(tmp_path)
    assert "jvm" in deps.stack_registry
    assert "go" in deps.stack_registry
    # 등록 순서가 JVM → Go 임을 보장 (F-16 우선순위)
    keys = list(deps.stack_registry.keys())
    assert keys.index("jvm") < keys.index("go")
