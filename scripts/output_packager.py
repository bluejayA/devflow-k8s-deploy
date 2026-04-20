"""OutputPackager — STEP 5 최종 패키징.

summary.json (v1 스키마, UTC ISO8601, validation.skipped[]) +
rationale.md (결정 소스 매핑 + 스킵 검증 섹션) +
troubleshoot.md (bail-out 시, 상단 한국어 1-2줄 요약 의무).

F-06, F-52, F-56, F-80~F-83, F-101 구현.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scripts._shared.image_ref import _IMAGE_REF_RE
from scripts._shared.types import (
    AnalysisResult,
    BailOutContext,
    PackagingResult,
    UserInputs,
    ValidationOutcome,
    ValidationReport,
)

if TYPE_CHECKING:
    pass

# Markdown/텍스트 컨텍스트 개행·제어문자 차단
_UNSAFE_CHARS = ("\n", "\r", "\x00")

# 스킵 사유 기본 메시지 (한국어)
_SKIP_REASON_DEFAULT: dict[str, str] = {
    "kubectl_dry_run": "쿠버네티스 CLI(kubectl)가 설치되어 있지 않아 dry-run 검증을 건너뜀",
    "container_build": "컨테이너 빌드 엔진이 감지되지 않아 빌드 단계를 건너뜀",
}

# 네임스페이스 출처 한국어 레이블
_NAMESPACE_SOURCE_KO: dict[str, str] = {
    "project_config": "프로젝트 설정",
    "org_config": "조직 설정",
    "user_input": "사용자 직접 입력",
    "project_dir": "프로젝트 디렉토리명 추론",
    "default": "기본값 (사용자 확인 필요)",
}

# 상태성 한국어 레이블
_CONFIDENCE_KO: dict[str, str] = {
    "high": "높음 (high)",
    "medium": "중간 (medium)",
    "low": "낮음 (low)",
}

# 설정 출처 한국어 레이블
_SOURCE_KO: dict[str, str] = {
    "project_config": "프로젝트 설정 (devflow.yml)",
    "org_config": "조직 설정",
    "builtin_default": "내장 기본값",
    "auto-detect": "자동 감지 (설정 없음)",
    "auto": "자동 감지 (설정 없음)",
    "user_input": "사용자 입력",
}


def _utc_now_iso() -> str:
    """현재 UTC 시각을 ISO 8601 형식(Z suffix)으로 반환.

    monkeypatch 대상 — 테스트에서 고정값 주입 가능.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_text_field(value: str, field_name: str) -> None:
    """Markdown/텍스트 컨텍스트에 삽입될 문자열에서 개행/NUL 차단.

    Args:
        value: 검증할 문자열.
        field_name: 오류 메시지에 포함될 필드명.

    Raises:
        ValueError: 개행 또는 NUL 문자가 포함된 경우.
    """
    for ch in _UNSAFE_CHARS:
        if ch in value:
            raise ValueError(
                f"텍스트 주입 방어: {field_name}에 개행 또는 제어문자 포함 금지: {value!r}"
            )


def _parse_image_reference(image_reference: str) -> dict[str, Any]:
    """이미지 참조를 파싱해 repository/tag/digest dict 반환.

    지원 형식:
      - ``repo:tag`` → {"repository": "repo", "tag": "tag", "digest": null}
      - ``repo:tag@sha256:<64hex>`` → {"repository": "repo", "tag": "tag", "digest": "sha256:..."}
      - ``repo@sha256:<64hex>`` → {"repository": "repo", "tag": null, "digest": "sha256:..."}

    Args:
        image_reference: OCI 이미지 참조 문자열.

    Returns:
        repository/tag/digest 키를 가진 dict.
    """
    match = _IMAGE_REF_RE.fullmatch(image_reference)
    if not match:
        # 파싱 실패 시 전체를 repository로 취급 (OutputPackager는 예외 비발생 원칙)
        return {"repository": image_reference, "tag": None, "digest": None}

    repo = match.group("repo")
    tag = match.group("tag")  # None if absent
    digest_hex = match.group("digest")  # None if absent
    digest = f"sha256:{digest_hex}" if digest_hex else None

    return {"repository": repo, "tag": tag, "digest": digest}


class OutputPackager:
    """STEP 5 최종 패키징 담당 서비스.

    AtomicWriter 컨텍스트 안에서 호출되며,
    staging_dir에 rationale.md / summary.json / (bail-out 시) troubleshoot.md를 기록.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(
        self,
        staging_dir: Path,
        inputs: UserInputs,
        analysis: AnalysisResult,
        validation: ValidationReport,
        config_source_map: dict[str, str],
        *,
        image_reference: str,
        validation_outcome: ValidationOutcome | None = None,
    ) -> PackagingResult:
        """staging_dir에 rationale.md + summary.json 생성.

        Args:
            staging_dir: 파일을 쓸 임시 디렉토리 (AtomicWriter staging).
            inputs: STEP 1 사용자 입력.
            analysis: STEP 2 분석 결과.
            validation: STEP 4 검증 결과.
            config_source_map: 설정 키 → 출처 레이어 맵 (rationale 용).
            image_reference: Dockerfile에 사용된 runner 이미지 참조.
            validation_outcome: STEP 4 통합 결과 (skipped 목록 포함). None이면 빈 skipped.

        Returns:
            PackagingResult(final_dir, files_written, troubleshoot_written).
        """
        skipped: list[str] = []
        if validation_outcome is not None:
            skipped = list(validation_outcome.skipped)

        generated_files: list[str] = [
            "Dockerfile",
            "deployment.yaml",
            "service.yaml",
            "serviceaccount.yaml",
            "summary.json",
            "rationale.md",
        ]

        summary_path = staging_dir / "summary.json"
        rationale_path = staging_dir / "rationale.md"

        self.write_summary_json(
            path=summary_path,
            inputs=inputs,
            analysis=analysis,
            validation=validation,
            image_reference=image_reference,
            skipped=skipped,
            files=generated_files,
        )

        self.write_rationale_md(
            path=rationale_path,
            inputs=inputs,
            analysis=analysis,
            validation=validation,
            config_source_map=config_source_map,
            skipped=skipped,
        )

        return PackagingResult(
            final_dir=staging_dir,
            files_written=["summary.json", "rationale.md"],
            troubleshoot_written=False,
        )

    def write_troubleshoot(
        self,
        staging_dir: Path,
        bailout: BailOutContext,
    ) -> None:
        """bail-out 시에만 호출. troubleshoot.md 작성.

        상단:
          # 막힌 지점
          STEP {n} ({한국어 단계명})에서 {component_ko} 실패: {ko_summary}
          (영문) {en_detail}

        하단: 전체 시도 로그 (attempts_log).

        Args:
            staging_dir: 파일을 쓸 임시 디렉토리.
            bailout: bail-out 컨텍스트 (step, component, 요약, 로그).
        """
        lines: list[str] = []
        total = len(bailout.attempts_log)

        # ── 상단: 한국어 1-2줄 요약 (F-52) ──────────────────────────────
        lines.append("# 막힌 지점")
        lines.append("")
        lines.append(
            f"STEP {bailout.step_number} ({bailout.step_name_ko})에서 "
            f"{bailout.component_ko} 실패: {bailout.ko_summary}"
        )
        lines.append(f"(영문) {bailout.en_detail}")
        lines.append("")

        # ── 시도 로그 ────────────────────────────────────────────────────
        lines.append("## 시도 로그")
        lines.append("")
        for attempt in bailout.attempts_log:
            n = attempt.attempt_number
            lines.append(f"### 시도 {n}/{total}")
            lines.append(f"- 결과: {'PASS' if attempt.success else 'FAIL'}")
            if attempt.fix_outcome is not None and attempt.fix_outcome.summary_ko:
                lines.append(f"- 요약: {attempt.fix_outcome.summary_ko}")
            elif not attempt.success:
                if n == total:
                    lines.append("- 요약: bail-out")
                else:
                    lines.append("- 요약: 수정 시도 실패")
            lines.append("")

        # ── 권장 조치 ────────────────────────────────────────────────────
        lines.append("## 권장 조치")
        lines.append("")
        lines.append("1. application-design.md §8 Container securityContext 확인")
        lines.append("2. 수동 manifest 편집 후 재시도")
        lines.append("")

        content = "\n".join(lines)
        (staging_dir / "troubleshoot.md").write_text(content, encoding="utf-8")

    def write_summary_json(
        self,
        path: Path,
        inputs: UserInputs,
        analysis: AnalysisResult,
        validation: ValidationReport,
        image_reference: str,
        skipped: list[str],
        files: list[str],
    ) -> None:
        """summary.json v1 스키마 직렬화.

        스키마:
        {
          "version": "v1",
          "generated_at": "<UTC ISO8601 with Z>",
          "stack": "jvm",
          "app": {"name": str, "ports": [int]},
          "images": [{"repository": str, "tag": str|null, "digest": str|null}],
          "namespace": str,
          "validation": {
            "pass": int, "warn": int, "fail": int,
            "skipped": [str, ...]
          },
          "files": [str, ...]
        }

        Args:
            path: 출력 파일 경로.
            inputs: STEP 1 사용자 입력.
            analysis: STEP 2 분석 결과.
            validation: STEP 4 검증 결과.
            image_reference: runner 이미지 참조.
            skipped: 스킵된 검증 식별자 목록 (F-83).
            files: 생성된 파일 이름 목록.
        """
        image_info = _parse_image_reference(image_reference)

        doc: dict[str, Any] = {
            "version": "v1",
            "generated_at": _utc_now_iso(),
            "stack": analysis.stack,
            "app": {
                "name": inputs.app_name,
                "ports": [inputs.port],
            },
            "images": [image_info],
            "namespace": inputs.namespace,
            "validation": {
                "pass": validation.counts.get("pass", 0),
                "warn": validation.counts.get("warn", 0),
                "fail": validation.counts.get("fail", 0),
                "skipped": list(skipped),
            },
            "files": list(files),
        }

        path.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False),
            encoding="utf-8",
        )

    def write_rationale_md(
        self,
        path: Path,
        inputs: UserInputs,
        analysis: AnalysisResult,
        validation: ValidationReport,
        config_source_map: dict[str, str],
        skipped: list[str],
    ) -> None:
        """rationale.md 생성 — 결정 근거 문서 (F-82 + 확장).

        섹션:
          - 감지된 스택 (source map)
          - 포트 (추론 근거)
          - 상태성 (StatefulnessSignal.confidence + 근거)
          - 네임스페이스 (config_source_map)
          - 베이스 이미지 (config layer 출처)
          - 리소스 (defaults 출처)
          - 프로브 (ProbeConfig 분기 근거)
          - 검증 결과 요약 (PASS/WARN/FAIL 카운트)
          - 스킵된 검증 (skipped + 사유, F-56)  ← 신규
          - 경고 목록

        Args:
            path: 출력 파일 경로.
            inputs: STEP 1 사용자 입력.
            analysis: STEP 2 분석 결과.
            validation: STEP 4 검증 결과.
            config_source_map: 설정 키 → 출처 레이어 맵.
            skipped: 스킵된 검증 식별자 목록 (F-56 pass-through).
        """
        detect = analysis.detect_result
        build = analysis.build_plan
        probe = analysis.probe_config
        defaults = analysis.defaults
        sf = analysis.statefulness

        # config_source_map 값 유효성 검사 (개행 차단)
        for k, v in config_source_map.items():
            _validate_text_field(v, f"config_source_map[{k!r}]")

        # StatefulnessSignal.reasons 유효성 검사
        for i, reason in enumerate(sf.reasons):
            _validate_text_field(reason, f"statefulness.reasons[{i}]")

        generated_at = _utc_now_iso()

        lines: list[str] = []

        # ── 헤더 ─────────────────────────────────────────────────────────
        lines.append("# 생성 근거 (rationale.md)")
        lines.append("")
        lines.append(f"**생성 시각**: {generated_at} (UTC)")
        lines.append(f"**스택**: {analysis.stack}")
        lines.append("")

        # ── §1 감지된 스택 ───────────────────────────────────────────────
        stack_source = config_source_map.get("stack", "auto-detect")
        stack_source_ko = _SOURCE_KO.get(stack_source, stack_source)
        lines.append("## 감지된 스택")
        lines.append(f"- 프레임워크: {detect.framework}"
                     + (f" {detect.version}" if detect.version else ""))
        if detect.build_system:
            lines.append(f"- 빌드 시스템: {detect.build_system}")
        lines.append(f"- actuator 활성화: {str(detect.actuator_enabled).lower()}")
        lines.append(f"- 출처: {stack_source_ko}")
        lines.append("")

        # ── §2 포트 ─────────────────────────────────────────────────────
        lines.append("## 포트")
        lines.append(f"- 값: {inputs.port}")
        if detect.port == inputs.port:
            lines.append("- 근거: application.yml의 `server.port` 또는 기본값")
        else:
            lines.append("- 근거: 사용자 직접 입력")
        lines.append("")

        # ── §3 상태성 ────────────────────────────────────────────────────
        stateful_label = "stateful" if sf.is_stateful else "stateless"
        confidence_ko = _CONFIDENCE_KO.get(sf.confidence, sf.confidence)
        lines.append("## 상태성")
        lines.append(f"- 판정: {stateful_label}")
        lines.append(f"- 신뢰도: {confidence_ko}")
        if sf.reasons:
            for reason in sf.reasons:
                lines.append(f"- 근거: {reason}")
        else:
            lines.append("- 근거: 자동 감지")
        lines.append("")

        # ── §4 네임스페이스 ─────────────────────────────────────────────
        ns_source = config_source_map.get("namespace", "user_input")
        ns_source_ko = _NAMESPACE_SOURCE_KO.get(ns_source, ns_source)
        lines.append("## 네임스페이스")
        lines.append(f"- 값: {inputs.namespace}")
        lines.append(f"- 출처: {ns_source_ko} ({ns_source})")
        lines.append("")

        # ── §5 베이스 이미지 ─────────────────────────────────────────────
        image_source = config_source_map.get("base_image", "builtin_default")
        image_source_ko = _SOURCE_KO.get(image_source, image_source)
        lines.append("## 베이스 이미지")
        lines.append(f"- builder: {build.builder_image}")
        lines.append(f"- runner: {build.runner_image}")
        lines.append(f"- 출처: {image_source_ko} ({image_source})")
        lines.append("")

        # ── §6 리소스 ────────────────────────────────────────────────────
        resource_source = config_source_map.get("resources", "builtin_default")
        resource_source_ko = _SOURCE_KO.get(resource_source, resource_source)
        lines.append("## 리소스")
        lines.append(
            f"- CPU request/limit: {defaults.cpu_request} / {defaults.cpu_limit}"
        )
        lines.append(
            f"- 메모리 request/limit: {defaults.memory_request} / {defaults.memory_limit}"
        )
        lines.append(f"- 출처: {resource_source_ko} ({resource_source})")
        lines.append("")

        # ── §7 프로브 ────────────────────────────────────────────────────
        lines.append("## 프로브")
        liveness = probe.liveness
        readiness = probe.readiness
        if liveness.kind == "http":
            lines.append(
                f"- liveness: HttpProbe({liveness.path}, {liveness.port})"
            )
        else:
            lines.append(f"- liveness: TcpProbe({liveness.port})")
        if readiness.kind == "http":
            lines.append(
                f"- readiness: HttpProbe({readiness.path}, {readiness.port})"
            )
        else:
            lines.append(f"- readiness: TcpProbe({readiness.port})")
        if detect.actuator_enabled and detect.version and detect.version.startswith("3"):
            lines.append("- 근거: Boot 3.x + actuator 감지")
        elif detect.actuator_enabled:
            lines.append("- 근거: Spring Boot Actuator 감지")
        else:
            lines.append("- 근거: actuator 미감지 — TCP probe 사용")
        lines.append("")

        # ── §8 검증 결과 요약 ────────────────────────────────────────────
        counts = validation.counts
        lines.append("## 검증 결과 요약")
        lines.append(f"- PASS: {counts.get('pass', 0)}건")
        lines.append(f"- WARN: {counts.get('warn', 0)}건")
        lines.append(f"- FAIL: {counts.get('fail', 0)}건")
        lines.append("")

        # ── §9 스킵된 검증 (F-56 신규) ──────────────────────────────────
        if skipped:
            lines.append("## 스킵된 검증")
            for skip_id in skipped:
                reason = _SKIP_REASON_DEFAULT.get(skip_id, f"{skip_id}: 사유 미기록")
                lines.append(f"- {skip_id}: {reason}")
            lines.append("")

        # ── §10 경고 목록 ────────────────────────────────────────────────
        warn_results = [r for r in validation.results if r.level == "WARN"]
        lines.append("## 경고")
        if warn_results:
            for result in warn_results:
                lines.append(f"- {result.rule_id}: {result.message_ko}")
        else:
            lines.append("- 경고 없음")
        lines.append("")

        content = "\n".join(lines)
        path.write_text(content, encoding="utf-8")
