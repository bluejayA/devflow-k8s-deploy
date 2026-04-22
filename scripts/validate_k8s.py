"""K8s manifest 정적 검증기 (stack-agnostic).

CLI:
    validate_k8s.py [--json] [--skipped CHECK [CHECK ...]] PATH

Exit codes (F-42):
    0 — all PASS
    1 — FAIL 존재
    2 — FAIL 없음 + WARN 존재 (soft-success)

Consumer 주의 (F-42):
    set -e 환경에서 exit code 2 (soft-success)를 실패로 오인하지 않도록
    ``&& [ $? -le 2 ]`` 또는 ``|| [ $? -eq 2 ]`` 처리가 필요합니다.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from scripts._shared.types import ValidationReport

# re-exports — 기존 임포트 경로 유지
from scripts.validators.core import K8sValidator, _compute_exit_code  # noqa: F401

# ─── CLI ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Kubernetes manifest 정적 검증기 (stack-agnostic)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Exit codes:
              0 — PASS만 존재 (경고 없음)
              1 — FAIL 1건 이상
              2 — FAIL 없음 + WARN 1건 이상 (soft-success)

            주의 (F-42): set -e 환경에서 exit 2를 실패로 오인하지 않으려면
              && [ $? -le 2 ] 또는 || [ $? -eq 2 ] 처리가 필요합니다.

            사용 예시:
              validate_k8s.py manifest.yaml
              validate_k8s.py --json manifest.yaml
              validate_k8s.py --skipped kubectl_dry_run manifest.yaml
              validate_k8s.py --skipped kubectl_dry_run,container_build manifests/
            """
        ),
    )
    parser.add_argument(
        "path",
        metavar="PATH",
        help="검증할 YAML 파일 또는 디렉토리 경로",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 형식으로 출력 (summary.json validation 필드 호환)",
    )
    parser.add_argument(
        "--skipped",
        default="",
        help="콤마 구분 스킵 식별자 목록 (예: kubectl_dry_run,container_build)",
    )
    return parser


def main() -> int:
    """CLI 진입점. sys.exit()에 넘길 exit code를 반환."""
    parser = _build_parser()
    args = parser.parse_args()

    path = Path(args.path)
    skipped: list[str] = [s.strip() for s in args.skipped.split(",") if s.strip()]

    validator = K8sValidator(skipped=skipped)
    report = validator.validate([path])

    if args.json_output:
        print(validator.to_json(report, skipped=skipped))
    else:
        _print_human(report)

    return report.exit_code


def _print_human(report: ValidationReport) -> None:
    """사람이 읽기 쉬운 형식으로 결과 출력 (F-46 포맷)."""
    print(f"\n{'=' * 60}")
    print("K8s Manifest 검증 결과")
    print(f"{'=' * 60}")

    for r in report.results:
        prefix = r.level
        if r.suggestion and r.level != "PASS":
            print(f"[{prefix}] {r.rule_id} {r.container}: {r.message_ko} → {r.suggestion}")
        else:
            print(f"[{prefix}] {r.rule_id} {r.container}: {r.message_ko}")

    c = report.counts
    print(f"\n결과: PASS {c['pass']}건 / WARN {c['warn']}건 / FAIL {c['fail']}건")
    if report.skipped:
        print(f"스킵됨: {', '.join(report.skipped)}")

    if report.exit_code == 0:
        print("상태: 모든 검증 통과")
    elif report.exit_code == 1:
        print(f"상태: FAIL {c['fail']}건 수정 필요")
    else:
        print(f"상태: soft-success (WARN {c['warn']}건)")


if __name__ == "__main__":
    sys.exit(main())
