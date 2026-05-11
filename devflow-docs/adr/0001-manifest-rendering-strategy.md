# ADR-0001 — Manifest 렌더링 전략 통일

- **Date**: 2026-05-07
- **Status**: Accepted
- **Backlog**: BL-018 ([#28](https://github.com/bluejayA/devflow-k8s-deploy/issues/28))
- **Driven by**: Python 스택(BL-006) 추가 직전, manifest 생성 방식 일관성 확보 필요.

## Context

BL-003 (StatefulSet+PVC) / BL-004 (NetworkPolicy zero-trust) 구현 시 기존 manifest 생성 패턴(Jinja2 템플릿)을 따르지 않고 Python `dict` + `yaml.dump()` 방식으로 구현되어 5개 매니페스트 타입 중 2개가 다른 경로를 사용한다.

| 매니페스트 | 방식 | 위치 | 보안 근거 주석 |
|---|---|---|---|
| deployment | Jinja2 | `templates/manifest/deployment.tmpl` | ✅ |
| service | Jinja2 | `templates/manifest/service.tmpl` | ❌ |
| serviceaccount | Jinja2 | `templates/manifest/serviceaccount.tmpl` | ❌ |
| **statefulset** | **dict + yaml.dump** | `scripts/manifest_generator.py:319-419` | ❌ |
| **networkpolicy** | **dict + yaml.dump** | `scripts/manifest_generator.py:422-518` | ❌ |

이는 BL-003+BL-004 requirements 문서에 명시된 `statefulset.tmpl 신규` / `networkpolicy.tmpl 신규` 계획과 구현이 어긋난 결과 (계획/구현 drift).

## Decision

**β (Jinja2 통일)** 을 채택한다.

신규 작성:
- `templates/manifest/statefulset.tmpl`
- `templates/manifest/networkpolicy.tmpl`

`ManifestGenerator.generate_statefulset()` / `generate_networkpolicy()` 는 `_renderer.render_manifest("statefulset", ctx)` / `render_manifest("networkpolicy", ctx)` 호출로 교체한다.

## Rationale

### β를 선택한 이유

1. **보안 근거 주석 보존** — `deployment.tmpl`에는 BL-021에서 다듬은 stack-aware 보안/운영 메모(Pod securityContext, OOMKill 방어, 프로브 의도 등)가 들어있다. `yaml.dump()`는 주석을 출력할 수 없어 dict 통일을 택하면 이 자산이 모두 소실된다. ruamel.yaml로 우회하려면 의존성이 무거워지고 출력 결정성 검증 비용이 증가한다.

2. **리뷰 가시성** — 5개 manifest 정책을 파일 단위로 분리하면 DevOps 엔지니어가 grep/diff로 정책을 빠르게 파악할 수 있다. 532줄 `manifest_generator.py`에 모든 구조가 묻히면 정책 변경 추적이 어렵다.

3. **작업량 비대칭** — β는 신규 템플릿 2개 작성. α는 기존 템플릿 3개 변환 + 모든 보안 주석 재배치 + dict 헬퍼 추가. β가 더 작은 변경으로 동일 일관성을 달성한다.

4. **계획/구현 drift 복원** — 원래 BL-003/BL-004 requirements가 명시한 방향이 β였다. drift를 복원하는 게 계획 책임에 부합.

### α를 선택하지 않은 이유

- 조건부 필드(`storage_class`, 동적 `ingress`/`egress`)가 Python dict에서 더 자연스럽다는 장점이 있으나, 기존 `deployment.tmpl`의 `{% if liveness_http %}` / `{% for vm in writable_volume_mounts %}` 패턴이 충분히 검증돼 있어 결정적 단점이 아니다.
- BL-021 작업이 무력화되는 비용이 위 장점을 압도한다.

## Output 규격 영향

### Byte-identical 해석 (이슈 Acceptance 명시 vs 현실)

이슈 Acceptance에 "기존 골든 스냅샷 byte-identical 유지"가 적혀있으나, 실제로는 **두 방식이 출력 스타일이 달라 양립 불가능**하다.

```yaml
# Jinja2 (deployment.yaml) — 리스트 항목 2칸 들여쓰기
containers:
  - name: jvm-app

# yaml.dump (statefulset.yaml) — 리스트 항목 같은 컬럼
containers:
- name: jvm-app
```

따라서 byte-identical 요구를 다음과 같이 재해석한다:

> **기존 출력의 의미(parsed YAML deep-equality)는 동일하게 유지하되, 직렬화 스타일은 단일 렌더 경로(Jinja2)에 맞춰 정합화한다.**

### 골든 영향

| 골든 파일 | 영향 |
|---|---|
| `tests/snapshots/jvm/deployment.yaml` | 변경 없음 (이미 Jinja2) |
| `tests/snapshots/jvm/service.yaml` | 변경 없음 (이미 Jinja2) |
| `tests/snapshots/jvm/serviceaccount.yaml` | 변경 없음 (이미 Jinja2) |
| `tests/snapshots/jvm/statefulset.yaml` | **갱신** — 들여쓰기 스타일 정합화 (Jinja2 style) |
| `tests/snapshots/jvm/networkpolicy.yaml` | **신규** — networkpolicy 첫 골든 |

### 회귀 방지 가드

Byte 비교만으로는 의도된 스타일 갱신을 검증할 수 없으므로, 다음 가드를 추가한다:

1. **Parsed YAML deep-equality 가드** — 신규 템플릿 출력을 PyYAML로 파싱하여, 이전 `dict` 빌드 결과 dict와 deepEquals 비교. 직렬화 스타일이 달라도 의미가 같음을 보장.
2. **갱신된 골든 byte 가드** — 새 골든 파일과 새 출력의 byte-identical을 lock down (이후 회귀 방지).

## Consequences

### Positive

- 5개 manifest 모두 단일 렌더 경로(Jinja2). 신규 manifest 추가 시 패턴 혼란 없음.
- 보안 근거 주석을 statefulset/networkpolicy에도 추가 가능 (별도 작업).
- BL-006 (Python 스택)에서 manifest 추가 시 진입 비용 균질화.

### Negative / Trade-off

- 신규 `.tmpl` 2개 추가 = 정책이 코드(.py) ↔ 데이터(.tmpl) 사이를 오갈 때 인지 부담 약간 증가. 다만 이 부담은 이미 deployment에 존재하므로 새로 도입되는 부담은 아님.
- statefulset 골든 한 번 갱신 → 향후 다른 작업이 byte 비교에 의존할 때 혼선 가능성. ADR로 명시 + commit 메시지로 의도 박제하여 완화.

## Validation

- `pytest`: 신규 parsed-equivalence 가드 + 갱신 골든 byte 가드 모두 통과
- `ruff check`: clean
- 모든 manifest가 `_renderer.render_manifest(...)` 호출만 사용 (grep으로 잔존 `yaml.dump(` 부재 확인)
