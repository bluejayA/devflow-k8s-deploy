"""DevflowError 계열 예외 계층.
모든 devflow 내부 예외는 DevflowError를 상속한다."""


class DevflowError(Exception):
    """devflow 스킬 예외의 최상위 기반 클래스."""


class UserAbort(DevflowError):
    """사용자가 작업을 명시적으로 취소했을 때."""


class BailOutError(DevflowError):
    """3회 재시도 실패 또는 fix_outcome.applied=False로 중단."""


class ConfigError(DevflowError):
    """설정 파일 파싱/병합 실패."""


class UnsupportedStackError(DevflowError):
    """감지된 스택이 v0.1.0 지원 범위 밖일 때."""


class UnknownStackError(DevflowError):
    """스택을 자동 감지할 수 없을 때."""


class MultiModuleAbort(DevflowError):
    """멀티 모듈 프로젝트에서 대상 모듈 선택 취소."""


class JvmDetectionError(DevflowError):
    """JVM 스택 분석 중 필수 정보(포트/엔트리포인트 등) 추론 실패."""


class GoDetectionError(DevflowError):
    """Go 스택 감지 중 필수 정보(go.mod 파싱) 실패 (F-20).

    `JvmDetectionError`와 동일 단계(감지) 예외. 엔트리포인트 resolve 실패는
    `GoBuildPlanError` 로 분리.
    """


class GoBuildPlanError(DevflowError):
    """Go 스택 엔트리포인트 resolve 실패 (F-26).

    감지 자체는 성공했으나 `build_plan()`에서 cmd 후보 모호성 해결 실패 등
    (예: 복수 `cmd/*/main.go` + `app_name` 매칭 실패 + config 미지정).
    """


class PythonBuildPlanError(DevflowError):
    """Python 스택 build_plan 실패 (BL-006).

    감지 자체는 성공했으나 `build_plan()`에서 uv 명령 합성 실패 등.
    현재 시나리오 없음 — future-proof (NFR-3 안전 폴백 정책상 detect는 raise 안 함).
    """


class InvalidImageError(DevflowError):
    """'latest' 태그 또는 유효하지 않은 이미지 레퍼런스 감지."""


class MalformedManifestError(DevflowError):
    """생성된 Kubernetes 매니페스트 YAML 구조 오류."""


class KubectlExecutionError(DevflowError):
    """kubectl 명령 실행 실패 (exit code 비정상)."""


class OutputExistsAbort(DevflowError):
    """출력 디렉토리 이미 존재 + on_exists=prompt 에서 사용자 취소."""


class TemplateNotFoundError(DevflowError):
    """Jinja2 템플릿 파일을 찾을 수 없을 때."""
