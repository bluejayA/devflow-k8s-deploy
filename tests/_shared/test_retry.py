"""retry.py 단위 테스트 — 6개 핵심 케이스."""

from unittest.mock import MagicMock

import pytest


def test_first_attempt_success() -> None:
    """케이스 1: 첫 시도 성공 — operation 1회, fix_attempt 호출 안 됨."""
    from scripts._shared.retry import retry_with_fix

    call_count = 0

    def operation() -> int:
        nonlocal call_count
        call_count += 1
        return 42

    fix_mock = MagicMock()

    result = retry_with_fix(
        operation,
        fix_mock,
        success_predicate=lambda r: r == 42,
    )

    assert result.success is True
    assert result.final_result == 42
    assert call_count == 1
    fix_mock.assert_not_called()
    assert len(result.attempts) == 1
    assert result.attempts[0].success is True


def test_second_attempt_success() -> None:
    """케이스 2: 2번째 시도 성공 — operation 2회, fix_attempt 1회 (applied=True)."""
    from scripts._shared.retry import retry_with_fix
    from scripts._shared.types import FixOutcome

    call_count = 0

    def operation() -> int:
        nonlocal call_count
        call_count += 1
        # 첫 번째는 실패값, 두 번째는 성공값
        return 0 if call_count == 1 else 1

    fix_outcome = FixOutcome(applied=True, summary_ko="수정 적용")
    fix_mock = MagicMock(return_value=fix_outcome)

    result = retry_with_fix(
        operation,
        fix_mock,
        success_predicate=lambda r: r == 1,
    )

    assert result.success is True
    assert result.final_result == 1
    assert call_count == 2
    fix_mock.assert_called_once()
    assert len(result.attempts) == 2


def test_three_attempts_all_fail() -> None:
    """케이스 3: 3회 모두 실패 — 3회 attempts 반환, 모두 applied=True."""
    from scripts._shared.retry import retry_with_fix
    from scripts._shared.types import FixOutcome

    fix_outcome = FixOutcome(applied=True, summary_ko="수정 시도했으나 실패")
    fix_mock = MagicMock(return_value=fix_outcome)
    call_count = 0

    def operation() -> int:
        nonlocal call_count
        call_count += 1
        return 0  # 항상 실패값

    result = retry_with_fix(
        operation,
        fix_mock,
        success_predicate=lambda r: r == 1,
    )

    assert result.success is False
    assert result.bailout is True
    assert call_count == 3
    assert len(result.attempts) == 3
    # 마지막 attempt는 fix_outcome 없어야 함 (마지막 이후엔 fix 안 함)
    assert result.attempts[2].fix_outcome is None


def test_missing_success_predicate_raises_type_error() -> None:
    """케이스 4: success_predicate 생략 시 TypeError (키워드 전용 강제)."""
    from scripts._shared.retry import retry_with_fix
    from scripts._shared.types import FixOutcome

    fix_mock = MagicMock(return_value=FixOutcome(applied=True, summary_ko=None))

    # success_predicate를 위치 인자로 전달하면 TypeError 발생해야 함
    # (positional arg로 3개: operation, fix_attempt, success_predicate)
    with pytest.raises(TypeError):
        retry_with_fix(lambda: 1, fix_mock, lambda r: True)  # type: ignore[call-arg]


def test_fix_outcome_applied_false_immediate_bailout() -> None:
    """케이스 5: FixOutcome.applied=False 시 즉시 bail-out — 이후 operation 호출 안 됨."""
    from scripts._shared.retry import retry_with_fix
    from scripts._shared.types import FixOutcome

    call_count = 0

    def operation() -> int:
        nonlocal call_count
        call_count += 1
        return 0  # 항상 실패값

    fix_outcome = FixOutcome(applied=False, summary_ko="수정 불가")
    fix_mock = MagicMock(return_value=fix_outcome)

    result = retry_with_fix(
        operation,
        fix_mock,
        success_predicate=lambda r: r == 1,
    )

    assert result.success is False
    assert result.bailout is True
    # operation은 1회만 호출됨 (bail-out으로 2번째 시도 안 함)
    assert call_count == 1
    fix_mock.assert_called_once()


def test_operation_exception_passed_to_fix_attempt() -> None:
    """케이스 6: operation 예외 발생 시 fix_attempt에 예외 전달."""
    from scripts._shared.retry import retry_with_fix
    from scripts._shared.types import FixOutcome

    error_raised = RuntimeError("연결 실패")
    received_by_fix: list[Exception] = []

    def operation() -> int:
        raise error_raised

    def fix_attempt(arg: int | Exception | None) -> FixOutcome:
        if isinstance(arg, Exception):
            received_by_fix.append(arg)
        return FixOutcome(applied=False, summary_ko="예외 수신 확인")

    result = retry_with_fix(
        operation,
        fix_attempt,
        success_predicate=lambda r: True,
    )

    assert result.success is False
    assert len(received_by_fix) >= 1
    assert received_by_fix[0] is error_raised
    # attempt의 error 필드에 예외 기록
    assert result.attempts[0].error is error_raised
    assert result.attempts[0].result is None


def test_user_abort_propagates_immediately() -> None:
    """케이스 7: UserAbort를 raise하는 operation은 fix_attempt 호출 없이 즉시 예외 전파."""
    from scripts._shared.errors import UserAbort
    from scripts._shared.retry import retry_with_fix
    from scripts._shared.types import FixOutcome

    fix_mock = MagicMock(return_value=FixOutcome(applied=True, summary_ko="호출 안 돼야 함"))
    abort_error = UserAbort("사용자가 취소했습니다")

    def operation() -> int:
        raise abort_error

    with pytest.raises(UserAbort) as exc_info:
        retry_with_fix(
            operation,
            fix_mock,
            success_predicate=lambda r: True,
        )

    assert exc_info.value is abort_error
    fix_mock.assert_not_called()


def test_keyboard_interrupt_propagates_immediately() -> None:
    """케이스 8: KeyboardInterrupt는 fix_attempt 호출 없이 즉시 전파."""
    from scripts._shared.retry import retry_with_fix
    from scripts._shared.types import FixOutcome

    fix_mock = MagicMock(return_value=FixOutcome(applied=True, summary_ko="호출 안 돼야 함"))

    def operation() -> int:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        retry_with_fix(
            operation,
            fix_mock,
            success_predicate=lambda r: True,
        )

    fix_mock.assert_not_called()


def test_fix_attempt_receives_none_when_operation_returns_none_and_fails() -> None:
    """케이스 9: operation None 반환 + success_predicate(None)=False 시 fix_attempt에 None 전달."""
    from scripts._shared.retry import retry_with_fix
    from scripts._shared.types import FixOutcome

    received_by_fix: list[object] = []

    def operation() -> None:
        return None

    def fix_attempt(arg: None | Exception | None) -> FixOutcome:
        received_by_fix.append(arg)
        return FixOutcome(applied=False, summary_ko="None 수신 확인")

    result = retry_with_fix(
        operation,
        fix_attempt,
        success_predicate=lambda r: r is not None,
    )

    assert result.success is False
    assert len(received_by_fix) >= 1
    assert received_by_fix[0] is None
