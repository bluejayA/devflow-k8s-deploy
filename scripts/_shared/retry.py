"""3회 자동 수정 루프 공통 유틸 (F-50, F-51, F-54).
SkillPipeline에서 K8sValidator / KubectlDryRunner / 빌드 인라인 호출에 사용.
operation은 항상 lambda로 감싸 인자를 캡처한다."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from scripts._shared.types import FixOutcome, RetryAttempt

T = TypeVar("T")


@dataclass
class RetryResult(Generic[T]):
    """retry_with_fix() 반환 구조체."""

    success: bool  # 마지막 attempt가 success_predicate True
    final_result: T | None  # 마지막 성공 결과 (실패 시 마지막 attempt의 result)
    attempts: list[RetryAttempt[T]]  # 전체 시도 로그 (troubleshoot.md 입력)
    bailout: bool  # True면 max_attempts 초과 또는 fix_outcome.applied=False


def retry_with_fix(
    operation: Callable[[], T],
    fix_attempt: Callable[[T | Exception], FixOutcome],
    *,
    success_predicate: Callable[[T], bool],
    max_attempts: int = 3,
    step_name_ko: str = "검증",
    component_ko: str = "",
) -> RetryResult[T]:
    """
    operation: 검증/실행 lambda. 반환값 또는 예외.
               예: lambda: K8sValidator.validate(manifest_paths)
    fix_attempt: operation 결과(또는 예외)를 받아 수정 시도. FixOutcome 반환.
                 applied=False면 다음 attempt 안 함, 즉시 bailout.
    success_predicate: operation 결과가 성공인지 판정. 필수 키워드 인자.
                       예: lambda r: r.exit_code <= 2
                       (생략 불가 — 기본값 lambda r: True가 silent failure 일으킴)
    max_attempts: 기본 3 (F-50/F-51/F-54)
    step_name_ko, component_ko: troubleshoot.md 한국어 요약 생성용

    동작:
      for attempt in 1..max_attempts:
        try:
          result = operation()
          if success_predicate(result):
            return RetryResult(success=True, final_result=result, attempts=[...])
        except Exception as e:
          result, error = None, e
        if attempt < max_attempts:
          fix_outcome = fix_attempt(result or error)
          if not fix_outcome.applied:
            return RetryResult(success=False, bailout=True, ...)
        else:
          return RetryResult(success=False, bailout=True, ...)
    """
    attempts: list[RetryAttempt[T]] = []

    for attempt_num in range(1, max_attempts + 1):
        result: T | None = None
        error: Exception | None = None
        success = False

        try:
            result = operation()
            success = success_predicate(result)
        except Exception as exc:
            error = exc
            success = False

        # fix_outcome: 마지막 attempt가 아니고, 아직 성공 아닌 경우에만 호출
        fix_outcome: FixOutcome | None = None

        if success:
            attempts.append(
                RetryAttempt(
                    attempt_number=attempt_num,
                    result=result,
                    error=error,
                    success=True,
                    fix_outcome=None,
                )
            )
            return RetryResult(
                success=True,
                final_result=result,
                attempts=attempts,
                bailout=False,
            )

        # 실패 — fix 시도 여부 결정
        if attempt_num < max_attempts:
            fix_input: T | Exception = error if error is not None else result  # type: ignore[assignment]
            fix_outcome = fix_attempt(fix_input)

            attempts.append(
                RetryAttempt(
                    attempt_number=attempt_num,
                    result=result,
                    error=error,
                    success=False,
                    fix_outcome=fix_outcome,
                )
            )

            if not fix_outcome.applied:
                # applied=False → 즉시 bail-out
                return RetryResult(
                    success=False,
                    final_result=result,
                    attempts=attempts,
                    bailout=True,
                )
        else:
            # 마지막 attempt — fix 없이 종료
            attempts.append(
                RetryAttempt(
                    attempt_number=attempt_num,
                    result=result,
                    error=error,
                    success=False,
                    fix_outcome=None,
                )
            )
            return RetryResult(
                success=False,
                final_result=result,
                attempts=attempts,
                bailout=True,
            )

    # 이 경로는 도달하지 않음 (위 루프에서 항상 return)
    return RetryResult(success=False, final_result=None, attempts=attempts, bailout=True)
