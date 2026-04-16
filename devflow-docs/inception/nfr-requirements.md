# NFR Requirements

**Timestamp**: 2026-04-17T00:00:00+09:00
**Mode**: GENERATE
**Domain**: 개발자 도구/CLI (Kubernetes 배포 아티팩트 생성 플러그인)
**Profile**: MVP/프로토타입 (v0.1.0 첫 릴리스)

---

## NFR Summary

| 카테고리 | ID | 요구사항 | 측정 기준 | 근거 |
|---------|-----|---------|----------|------|
| 보안 (생성물 품질) | NFR-SEC-01 | 생성된 모든 manifest는 validate_k8s.py에서 FAIL: 0 | SEC-* 전체 규칙 통과 | 보안 도구의 핵심 가치. MVP에서도 타협 불가 |
| 보안 (생성물 품질) | NFR-SEC-02 | 생성된 manifest에 평문 시크릿 포함 금지 | env[].value 시크릿 패턴 0건 | SEC-009 규칙. Secret 참조(valueFrom.secretKeyRef)만 허용 |
| 보안 (경계 준수) | NFR-SEC-03 | 컨테이너 push / kubectl apply(dry-run 외) / cluster API 호출 0건 | 통합 테스트로 검증 | 생성 전용 도구의 존재 이유. 경계 위반은 치명적 |
| 보안 (네트워크) | NFR-SEC-04 | 허용 외부 호출: 컨테이너 레지스트리 + 선언된 의존성 레포지토리만 | 그 외 네트워크 호출 0건 | 오프라인 동작 가능해야 함 (캐시 존재 시) |
| 테스트 신뢰성 | NFR-TEST-01 | pytest 커버리지: validate_k8s.py ≥ 70% | pytest --cov 출력 | MVP 완화 기준. v0.2+에서 85%로 상향 검토 |
| 테스트 신뢰성 | NFR-TEST-02 | pytest 커버리지: 스택 추론 모듈 ≥ 60% | pytest --cov 출력 | MVP 완화 기준. v0.2+에서 75%로 상향 검토 |
| 테스트 신뢰성 | NFR-TEST-03 | CI 실행 10회 연속 성공률 100% | flaky 테스트 0건 | 결정론적 도구는 flaky 허용 불가 |
| 결정론성 | NFR-DET-01 | 동일 프로젝트 + 동일 설정 재실행 시 Dockerfile + manifest YAML byte-identical | cksum 비교 테스트 | Jinja2 템플릿 + 고정 순서 출력으로 보장. summary.json generated_at, rationale.md 타임스탬프, suffix 모드 디렉토리명은 예외 |
| 에러 복구 | NFR-ERR-01 | 각 STEP 최대 3회 자동 수정. bail-out 시 상태 100% 보존 | troubleshoot.md에 전체 시도 로그. 부분 파일 삭제 금지 | atomic write(F-103)와 연계. 사용자 작업물 보호 |
| 에러 복구 | NFR-ERR-02 | Atomic write: 실패/중단 시 k8s-output/은 이전 상태 보존 | 임시 디렉토리 → atomic rename 패턴 | 일관된 완전한 세트 보장 |
| 확장성 | NFR-EXT-01 | F-90~F-94 준수: 스택 모듈 분리, 템플릿 외부화, SKILL.md JVM 하드코딩 0건 | CI에서 자동 확인 (grep + 파일 존재 + 인터페이스 검증) | v0.2(Go) / v0.3(Python) 확장 비용 최소화 |
| 관찰성 | NFR-OBS-01 | rationale.md는 최종 결정값의 소스(config layer / 추론 / 기본값)를 1:1 매핑 | 각 값에 source 명시 | 디버깅 + 감사 추적. MVP에서도 "왜 이 값인지" 설명 필수 |
| 플러그인 규약 | NFR-PLG-01 | 하드코딩 경로 0건. ${CLAUDE_PLUGIN_ROOT} 사용. SKILL.md에 version: 0.1.0 semver 헤더 | grep 검증 | Claude Code 플러그인 표준 준수 |
| 플러그인 규약 | NFR-PLG-02 | summary.json 스키마 v0.1.x 패치에서 하위호환 유지 | 필드 제거/타입 변경 시 minor 업 | CI/CD 파이프라인 소비자 계약 보호 |
| 국제화 | NFR-I18N-01 | SKILL description + 사용자 대화 + 생성 파일 주석: 한국어. 에러: 한국어 + 영문 병기. summary.json generated_at: UTC 고정 | locale ko-KR 기본 | 한국어 사용자 우선. 기계 소비 필드는 UTC |
| 호환성 | NFR-COMPAT-01 | 권장: kubectl 1.25+ / Docker 20.10+ / Podman 4.0+ / nerdctl 1.0+. 필수: Python 3.11+ / Java Temurin 17 or 21 / Gradle 7+ / Maven 3.8+ | kubectl·빌드 엔진 부재 시 degraded success | 도구 미설치 환경에서도 생성·검증(부분) 가능 |
| 주석 품질 | NFR-DOC-01 | 보안(securityContext, SA) + 리소스(requests/limits) + 위험(image tag, probes) 필드에 근거 주석 필수 | CI에서 grep-friendly 패턴 점검 | "왜 이 설정인지" 근거가 생성물의 핵심 가치 |

---

## 카테고리별 상세

### 1. 보안 (생성물 품질 + 경계 준수)

이 프로젝트에서 "보안"은 두 축:
- **생성물 보안**: 만들어내는 K8s manifest/Dockerfile의 보안 품질 (NFR-SEC-01, NFR-SEC-02)
- **도구 경계**: 도구 자체가 위험한 행위를 하지 않음 (NFR-SEC-03, NFR-SEC-04)

MVP에서도 양쪽 모두 타협 불가. "시니어 엔지니어의 판단력을 인코딩"이 프로젝트 존재 이유.

### 2. 테스트 신뢰성

MVP 완화 적용:
- validate_k8s.py: 85% → **70%** (핵심 규칙은 100% 커버, 엣지 케이스는 v0.2+)
- 스택 추론 모듈: 75% → **60%** (JVM 단일 스택이므로 분기 적음)
- flaky: 0건 유지 (결정론적 도구의 기본)

### 3. 결정론성

byte-identical 재현성을 v0.1.0부터 강제:
- Jinja2 템플릿의 고정 렌더링 순서
- YAML 출력 시 키 순서 고정
- 예외: generated_at 타임스탬프, rationale.md 타임스탬프, suffix 모드 디렉토리명

### 4. 에러 복구

atomic write + bail-out 패턴:
- 임시 디렉토리에 먼저 생성 → 검증 통과 후 rename
- 실패 시 이전 상태 100% 보존
- troubleshoot.md에 전체 시도 로그

### 5. 확장성

구조적 분리만 v0.1.0에서 보장:
- 스택 모듈(scripts/stacks/), 템플릿(templates/dockerfile/) 파일 분리
- StackModule 인터페이스 5 메서드 계약
- 실제 확장은 v0.2+

### 6. 관찰성

rationale.md가 유일한 관찰성 채널 (MVP):
- 런타임 모니터링/대시보드: N/A (CLI 도구)
- 로깅: rationale.md + summary.json으로 대체

### 7. 플러그인 규약

Claude Code 플러그인 생태계 표준 준수:
- ${CLAUDE_PLUGIN_ROOT} 경로
- semver 헤더
- summary.json 하위호환 계약

### 8. 호환성

degraded success 패턴:
- kubectl/빌드 엔진 없어도 생성 + 정적 검증은 수행
- 해당 단계만 스킵 + rationale.md에 기록

---

## 조정 이력

- NFR-TEST-01: validate_k8s.py 커버리지 85% → **70%** (이유: MVP 첫 릴리스, 핵심 규칙 100% 커버는 유지하되 엣지 케이스 커버리지는 v0.2+에서 상향)
- NFR-TEST-02: 스택 추론 모듈 커버리지 75% → **60%** (이유: v0.1.0은 JVM 단일 스택, 분기 경로가 적어 60%로도 핵심 경로 커버 가능)

---

## MVP 범위 외 (v0.2+ 검토)

| 카테고리 | 항목 | 시점 |
|---------|------|------|
| 테스트 | validate_k8s.py ≥ 85%, 스택 모듈 ≥ 75% | v0.2 (스택 추가 시) |
| 성능 | 생성 시간 벤치마크 (운영 데이터 기반) | v0.2+ |
| 컴플라이언스 | CIS Kubernetes Benchmark 매핑 | v0.3+ |
| 모니터링 | 생성 이력 대시보드 / 사용 통계 | v0.4+ |

---

## Change Log

- 2026-04-17T00:00:00+09:00 — 최초 생성. GENERATE 모드. 도메인: 개발자 도구/CLI, 프로파일: MVP. 17개 NFR 항목, 2건 조정 (테스트 커버리지 완화)
