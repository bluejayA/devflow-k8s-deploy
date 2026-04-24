"""errors.py 단위 테스트 — DevflowError 상속 + raise/except 흐름."""

import pytest


def test_devflow_error_is_exception() -> None:
    """DevflowError: Exception 상속."""
    from scripts._shared.errors import DevflowError

    err = DevflowError("테스트 오류")
    assert isinstance(err, Exception)


def test_all_derived_errors_inherit_devflow_error() -> None:
    """모든 파생 예외가 DevflowError를 상속."""
    from scripts._shared.errors import (
        BailOutError,
        ConfigError,
        DevflowError,
        GoBuildPlanError,
        GoDetectionError,
        InvalidImageError,
        JvmDetectionError,
        KubectlExecutionError,
        MalformedManifestError,
        MultiModuleAbort,
        OutputExistsAbort,
        TemplateNotFoundError,
        UnknownStackError,
        UnsupportedStackError,
        UserAbort,
    )

    all_errors = [
        UserAbort,
        BailOutError,
        ConfigError,
        UnsupportedStackError,
        UnknownStackError,
        MultiModuleAbort,
        JvmDetectionError,
        GoDetectionError,
        GoBuildPlanError,
        InvalidImageError,
        MalformedManifestError,
        KubectlExecutionError,
        OutputExistsAbort,
        TemplateNotFoundError,
    ]
    for cls in all_errors:
        assert issubclass(cls, DevflowError), f"{cls.__name__}이 DevflowError를 상속하지 않음"


def test_user_abort_raise_except() -> None:
    """UserAbort: raise/except 흐름 검증."""
    from scripts._shared.errors import DevflowError, UserAbort

    with pytest.raises(UserAbort) as exc_info:
        raise UserAbort("사용자가 작업을 취소했습니다.")
    assert isinstance(exc_info.value, DevflowError)
    assert "취소" in str(exc_info.value)


def test_bail_out_error_raise_except() -> None:
    """BailOutError: raise/except 흐름 검증."""
    from scripts._shared.errors import BailOutError, DevflowError

    with pytest.raises(BailOutError):
        raise BailOutError("3회 재시도 실패")
    # 부모로도 catch 가능
    try:
        raise BailOutError("실패")
    except DevflowError as e:
        assert "실패" in str(e)


def test_config_error_raise_except() -> None:
    """ConfigError: 설정 파싱 실패 시나리오."""
    from scripts._shared.errors import ConfigError

    with pytest.raises(ConfigError):
        raise ConfigError("devflow.yaml 파싱 실패")


def test_kubectl_execution_error_raise_except() -> None:
    """KubectlExecutionError: kubectl 실행 실패 시나리오."""
    from scripts._shared.errors import DevflowError, KubectlExecutionError

    try:
        raise KubectlExecutionError("exit code 1")
    except DevflowError as e:
        assert "exit code 1" in str(e)


def test_invalid_image_error_raise_except() -> None:
    """InvalidImageError: 'latest' 태그 금지 시나리오."""
    from scripts._shared.errors import InvalidImageError

    with pytest.raises(InvalidImageError) as exc_info:
        raise InvalidImageError("'latest' 태그는 사용 금지입니다.")
    assert "latest" in str(exc_info.value)


def test_template_not_found_error_raise_except() -> None:
    """TemplateNotFoundError: 템플릿 파일 없는 시나리오."""
    from scripts._shared.errors import TemplateNotFoundError

    with pytest.raises(TemplateNotFoundError):
        raise TemplateNotFoundError("templates/dockerfile/jvm.tmpl을 찾을 수 없습니다.")


def test_go_detection_error_raise_except() -> None:
    """GoDetectionError: go.mod 파싱 실패 시나리오 (F-20)."""
    from scripts._shared.errors import DevflowError, GoDetectionError

    with pytest.raises(GoDetectionError) as exc_info:
        raise GoDetectionError("go.mod 파싱 실패: invalid module path")
    assert isinstance(exc_info.value, DevflowError)
    assert "go.mod" in str(exc_info.value)


def test_go_build_plan_error_raise_except() -> None:
    """GoBuildPlanError: 복수 cmd 엔트리포인트 해결 실패 시나리오 (F-26)."""
    from scripts._shared.errors import DevflowError, GoBuildPlanError

    with pytest.raises(GoBuildPlanError) as exc_info:
        raise GoBuildPlanError(
            "복수 cmd 엔트리포인트 발견: [kube-api, kube-scheduler]. "
            "'app_name'을 해당 디렉토리명과 일치시키거나 'stack.go.entrypoint'를 지정하세요."
        )
    assert isinstance(exc_info.value, DevflowError)
    assert "cmd" in str(exc_info.value)
