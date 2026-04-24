"""types.py 단위 테스트 — dataclass 기본값/frozen/field 존재 검증."""

from pathlib import Path

import pytest


def test_resolved_config_is_frozen_and_has_required_fields() -> None:
    """ResolvedConfig: frozen dataclass이며 raw/source_map/warnings 필드 존재."""
    from scripts._shared.types import ResolvedConfig

    cfg = ResolvedConfig(raw={"a": 1}, source_map={"a": "project"})
    assert cfg.raw == {"a": 1}
    assert cfg.source_map == {"a": "project"}
    assert cfg.warnings == []  # default_factory=list

    # frozen이면 수정 시 FrozenInstanceError
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        cfg.raw = {}  # type: ignore[misc]


def test_stack_decision_fields() -> None:
    """StackDecision: forced_stack/source 필드 존재 + frozen."""
    from scripts._shared.types import StackDecision

    sd = StackDecision(forced_stack=None, source="auto")
    assert sd.forced_stack is None
    assert sd.source == "auto"
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        sd.source = "manual"  # type: ignore[misc]


def test_user_inputs_literal_exposure() -> None:
    """UserInputs: exposure가 Literal 타입 + 필수 필드 존재."""
    from scripts._shared.types import UserInputs

    ui = UserInputs(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP",
        namespace="dev",
        output_dir=Path("k8s-output"),
        resource_hint="medium",
    )
    assert ui.app_name == "my-app"
    assert ui.port == 8080
    assert ui.exposure == "ClusterIP"


def test_validation_report_counts_and_exit_code() -> None:
    """ValidationReport: results/counts/exit_code/skipped 필드 + frozen."""
    from scripts._shared.types import ValidationReport

    vr = ValidationReport(
        results=[],
        counts={"pass": 3, "warn": 1, "fail": 0},
        exit_code=1,
        skipped=[],
    )
    assert vr.exit_code == 1
    assert vr.counts["pass"] == 3


def test_fix_outcome_fields() -> None:
    """FixOutcome: applied/summary_ko 필드 + frozen."""
    from scripts._shared.types import FixOutcome

    fo = FixOutcome(applied=True, summary_ko="디플로이먼트 수정 완료")
    assert fo.applied is True
    assert fo.summary_ko == "디플로이먼트 수정 완료"
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        fo.applied = False  # type: ignore[misc]


def test_retry_attempt_generic_fields() -> None:
    """RetryAttempt: Generic[T] — result 필드에 임의 타입 저장 가능."""
    from scripts._shared.types import RetryAttempt

    ra: RetryAttempt[int] = RetryAttempt(
        attempt_number=1,
        result=42,
        error=None,
        success=True,
        fix_outcome=None,
    )
    assert ra.attempt_number == 1
    assert ra.result == 42
    assert ra.success is True


def test_dry_run_result_skipped_fields() -> None:
    """DryRunResult: skipped/skip_reason_ko 포함 — F-56 degraded 경로 지원."""
    from scripts._shared.types import DryRunResult

    dr = DryRunResult(
        success=False,
        stdout=None,
        stderr=None,
        exit_code=None,
        skipped=True,
        skip_reason_ko="kubectl 미설치",
    )
    assert dr.skipped is True
    assert dr.skip_reason_ko == "kubectl 미설치"


def test_validation_outcome_is_mutable_dataclass() -> None:
    """ValidationOutcome: mutable dataclass (frozen=False) — step4에서 필드 갱신."""
    from scripts._shared.types import ValidationOutcome, ValidationReport

    vr = ValidationReport(
        results=[], counts={"pass": 0, "warn": 0, "fail": 0}, exit_code=0, skipped=[]
    )
    vo = ValidationOutcome(
        k8s_report=vr,
        dry_run=None,
        build=None,
        skipped=[],
        skip_reasons={},
        bailed=False,
    )
    # mutable이므로 필드 수정 가능해야 함
    vo.skipped.append("kubectl_dry_run")
    assert "kubectl_dry_run" in vo.skipped


def test_stack_detect_result_new_fields() -> None:
    """StackDetectResult: build_system / actuator_enabled 신규 필드 기본값 확인."""
    from scripts._shared.types import StackDetectResult

    # 기존 4 필드만으로 생성 → 신규 필드는 기본값
    result = StackDetectResult(port=8080, entrypoint="", framework="spring-boot", version="3.2.0")
    assert result.build_system is None
    assert result.actuator_enabled is False

    # 신규 필드 명시
    result2 = StackDetectResult(
        port=8080,
        entrypoint="",
        framework="spring-boot",
        version="3.2.0",
        build_system="gradle",
        actuator_enabled=True,
    )
    assert result2.build_system == "gradle"
    assert result2.actuator_enabled is True


def test_resolved_config_layer_raws_default_empty_dict() -> None:
    """ResolvedConfig.layer_raws 신규 필드: 기본값 빈 dict."""
    from scripts._shared.types import ResolvedConfig

    cfg = ResolvedConfig(raw={"a": 1}, source_map={"a": "project"})
    assert cfg.layer_raws == {}  # default_factory=dict


def test_stack_detect_result_cmd_candidates_default() -> None:
    """StackDetectResult.cmd_candidates 신규 필드(F-25/NFR-04 o):
    미지정 시 기본값 빈 list. 기존 호출부 호환성."""
    from scripts._shared.types import StackDetectResult

    # 기존 호출부 스타일 — 새 필드 미지정
    result = StackDetectResult(
        port=8080, entrypoint="", framework="spring-boot", version="3.2.0"
    )
    assert result.cmd_candidates == []

    # Go 사용 시나리오 — cmd_candidates 명시
    result_go = StackDetectResult(
        port=None,
        entrypoint="",
        framework="go-generic",
        version="1.22",
        cmd_candidates=["kube-api", "kube-scheduler"],
    )
    assert result_go.cmd_candidates == ["kube-api", "kube-scheduler"]


def test_resource_defaults_run_as_user_default() -> None:
    """ResourceDefaults.run_as_user 신규 필드(F-30):
    미지정 시 기본값 1000 (JVM 관례). 기존 호출부 호환성 + Go는 65532 명시."""
    from scripts._shared.types import ResourceDefaults

    # 기존 호출부 스타일 — run_as_user 미지정 시 JVM 관례값 1000
    defaults_jvm = ResourceDefaults(
        cpu_request="100m",
        memory_request="512Mi",
        cpu_limit="1000m",
        memory_limit="1Gi",
        writable_paths=["/tmp", "/var/log"],
    )
    assert defaults_jvm.run_as_user == 1000

    # Go 스택은 distroless nonroot UID 65532 명시
    defaults_go = ResourceDefaults(
        cpu_request="50m",
        memory_request="64Mi",
        cpu_limit="250m",
        memory_limit="128Mi",
        writable_paths=["/tmp"],
        run_as_user=65532,
    )
    assert defaults_go.run_as_user == 65532


def test_resource_defaults_run_as_user_range_validation() -> None:
    """ResourceDefaults.__post_init__: run_as_user 범위(1-65535) 검증 안전장치.

    Codex Phase 2 리뷰 P1 완화 — 명백한 오값(0, 음수, 경계 초과) 차단.
    """
    import pytest

    from scripts._shared.types import ResourceDefaults

    common_kwargs = dict(
        cpu_request="100m",
        memory_request="512Mi",
        cpu_limit="1000m",
        memory_limit="1Gi",
        writable_paths=["/tmp"],
    )

    # 경계 유효값 — 생성 성공
    ResourceDefaults(**common_kwargs, run_as_user=1)
    ResourceDefaults(**common_kwargs, run_as_user=65535)

    # 무효값 — ValueError raise
    for bad in (0, -1, 65536, 100000):
        with pytest.raises(ValueError, match="run_as_user"):
            ResourceDefaults(**common_kwargs, run_as_user=bad)


def test_resolved_config_layer_raws_explicit() -> None:
    """ResolvedConfig.layer_raws 명시 설정 — project_config/org_config/builtin_default 키."""
    from scripts._shared.types import ResolvedConfig

    layer_raws = {
        "project_config": {"namespace": "proj-ns"},
        "org_config": {"stack": "jvm"},
        "builtin_default": {"build": {"engine": "skip"}},
    }
    cfg = ResolvedConfig(raw={"a": 1}, source_map={}, layer_raws=layer_raws)
    assert cfg.layer_raws["project_config"]["namespace"] == "proj-ns"
    assert cfg.layer_raws["org_config"]["stack"] == "jvm"


def test_prompt_callback_type_alias() -> None:
    """PromptCallback: TypeAlias로 Callable 타입 지정."""
    from scripts._shared.types import PromptCallback, PromptRequest

    def my_cb(req: PromptRequest) -> str:
        return "yes"

    # PromptCallback은 타입 힌트용 — 런타임 할당 가능해야 함
    cb: PromptCallback = my_cb
    pr = PromptRequest(kind="confirm", ko_text="계속할까요?", options=None, help_term_id=None)
    assert cb(pr) == "yes"
