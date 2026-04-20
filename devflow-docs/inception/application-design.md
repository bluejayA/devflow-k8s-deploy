# Application Design

**Mode**: LIST (목록 단계 — 리뷰 반영판)
**Timestamp**: 2026-04-17T01:30:00+09:00
**Depth**: Comprehensive (NFR Design 활성)
**Source**:
- `devflow-docs/inception/requirements.md` (71 F-*, 17 NFR — 자동 집계)
- `devflow-docs/inception/user-stories.md` (22 stories)
- `devflow-docs/inception/nfr-requirements.md` (17 NFR + NFR-SEC-05 추가)
- `devflow-docs/inception/2026-04-15-brainstorming-v0.1.0-scope.md` (v0.1.0 scope lock)

**Review history**:
- 2026-04-17 1차 LIST: 15개 컴포넌트 (병합 전)
- 2026-04-17 3-페르소나 리뷰 + Codex 독립 검토 → **현재 (2차 LIST)**: 12개 컴포넌트 + 추적 매트릭스

---

## 설계 원칙

1. **5-STEP 파이프라인** (F-01): 입력 → 분석 → 생성 → 검증 → 패키징
2. **생성 전용 경계** (NFR-SEC-03): push / apply(dry-run 외) / cluster API 호출 0건. **NFR-SEC-05**: CI 감지 테스트로 회귀 방지 (런타임 가드 아님)
3. **확장성 우선** (F-90~F-94): JVM 전용 로직은 `stacks/jvm.py`에 격리. SKILL.md/`validate_k8s.py`는 stack-agnostic
4. **결정론성** (NFR-DET-01): Jinja2 고정 렌더링 + YAML 키 순서 고정. TemplateRenderer가 책임 중심지
5. **Atomic write** (F-103): 임시 디렉토리 → atomic rename. SIGINT/SIGTERM 핸들러로 결정론적 정리. `.tmp-*` 고아 자동 회수
6. **메시지 정책 — 전 STEP 한국어 우선** (NFR-17 확장): STEP 1 입력뿐 아니라 STEP 2 추론 실패 질문, STEP 4 검증 실패, troubleshoot.md까지 한국어 요약 + 원어 병기. SkillPipeline/ProjectAnalyzer/K8sValidator/OutputPackager가 사용자 대면 출력 책임
7. **Degraded success 기계 판독성** (NFR-PLG-02): kubectl/빌드엔진 미감지 시 `summary.json.validation.skipped[]`에 식별자 기록. CI가 exit 0/2만 보고 "전부 통과"로 오인 방지
8. **MVP 단순성**: 확장성 핵심(StackModule/JvmStackModule/TemplateRenderer)만 분리. 기본값 경로(opt-in 미사용) 컴포넌트는 SkillPipeline 인라인

---

## 컴포넌트 목록 (12개)

| # | 컴포넌트 | 책임 | 타입 | 1차 LIST 대비 변경 |
|---|---------|------|------|-----------------|
| 1 | SkillPipeline | 5-STEP 파이프라인 전체 오케스트레이션(SKILL.md 본문). **STEP 1 한국어 의도 질문(F-02a) + 도움말 카탈로그(F-02b) + 도움말 사전 소유.** **3회 자동 수정 루프 인라인 처리(`_shared/retry.py` 유틸 사용).** **opt-in 컨테이너 빌드(F-53~F-58) 인라인 호출.** **메시지 정책(NFR-17) 진입점.** **경계 allowlist 가이드(NFR-SEC-05) 사용** | Controller | AutoFixLoop, ContainerBuildRunner 흡수 |
| 2 | ConfigLoader | 3계층 설정(프로젝트/조직/내장) YAML 파싱 + 우선순위 병합. **`stack: auto\|jvm\|...` 강제/auto 분기 책임(F-62/F-92).** **namespace 4단계 조회(F-70/F-71) `resolve_namespace()` 흡수.** YAML 파싱 실패 시 graceful degrade + rationale 기록 | Service | NamespaceResolver 흡수 |
| 3 | ProjectAnalyzer | STEP 2 분석 오케스트레이션, ConfigLoader의 `stack` 결과로 StackModule 라우팅, multi-module 감지 + 비개발자 친화 힌트("API 서버는 보통 `-api` 모듈"). **상태성 감지(F-38) + 신뢰도 표시.** 추론 실패 시 한국어 우선 질문(NFR-17) | Service | 상태성 감지 책임 명시 |
| 4 | StackModule (Interface) | 5 메서드 계약 `detect/build_plan/probe_plan/defaults/artifact_locator`. **BuildPlan 일반화는 v0.2+ (Go 추가 직전)** — v0.1.0은 JDK/JRE 2단계 가정 유지하고 v0.2 백로그에 명시 | Adapter | 변경 없음 |
| 5 | JvmStackModule | Kotlin/Java Spring 감지(Gradle KTS/Groovy/Maven) + Boot 2.x/3.x 버전/포트/actuator 추론 + probe 플랜 + 기본 쓰기 경로(`/tmp` + `/var/log` + Tomcat work dir) 노출 | Adapter | F-32 확장 반영 (쓰기 경로 노출) |
| 6 | TemplateRenderer | Jinja2 기반 템플릿 렌더링(`templates/dockerfile/{stack}.tmpl`, manifest 템플릿). **결정론성 중심지** — 고정 키 순서, 고정 렌더 컨텍스트 정렬, 빈 라인 정규화 | Util | 유지 (결정론성 중심) |
| 7 | DockerfileGenerator | multi-stage Dockerfile 생성(JDK builder → JRE runner) + 비root 사용자 + 보안 주석 주입 + Gradle/Maven 캐시 레이어 최적화(F-25) | Service | 변경 없음 |
| 8 | ManifestGenerator | Deployment/Service/ServiceAccount YAML 생성. Pod/Container securityContext + probes + 리소스 + 근거 주석. **emptyDir 기본 마운트(`/tmp` + `/var/log`)** + Service type 제약 안내 | Service | F-32 확장 반영 |
| 9 | K8sValidator | `validate_k8s.py` stack-agnostic 정적 검증 (SEC-001~009 / RES-001 / IMG-001 / SA-001~002 / SVC-001~002 / PRB-001~002 + WARN). 3단계 exit code(F-42) + `--json` 모드(F-47) + **메시지 한국어 요약(NFR-17)** + **`validation.skipped[]` 메타 정보 출력(F-83 확장)** | Service | 메시지 정책 + skipped 출력 책임 명시 |
| 10 | KubectlDryRunner | `kubectl apply --dry-run=client` 실행 어댑터. 미설치 시 degraded success(경고 + rationale 기록 + `summary.json.validation.skipped`에 `kubectl_dry_run` 추가). **경계 allowlist 준수**(`--dry-run=client` 외 인자 금지) | Adapter | skipped 기록 책임 명시 |
| 11 | AtomicWriter | 임시 디렉토리(`.tmp-{uuid}/`) 쓰기 → atomic rename. **SIGINT/SIGTERM 핸들러**로 임시 정리. **시작 시 7일 이상 고아 `.tmp-*` 자동 회수.** `output.on_exists`(prompt/overwrite/suffix) 분기 | Util | SIGINT 핸들러 + 고아 회수 명시 |
| 12 | OutputPackager | STEP 5 최종 패키징: `rationale.md`(결정 소스 매핑 + 스킵 검증 섹션) + `summary.json`(고정 스키마, UTC, `validation.skipped[]` 포함) + bail-out 시 `troubleshoot.md`(상단 한국어 1-2줄 요약 의무) | Service | troubleshoot 한국어 요약 + skipped 책임 명시 |

**총 12개** (1차 15개에서 NamespaceResolver→ConfigLoader, AutoFixLoop→SkillPipeline, ContainerBuildRunner→SkillPipeline 인라인)

### 흡수된 컴포넌트 (1차 LIST에서 제거)

| 1차 컴포넌트 | 흡수처 | 사유 |
|------------|-------|------|
| NamespaceResolver | ConfigLoader.resolve_namespace() | 4단계 조회의 2/3단계가 ConfigLoader 영역. 단일 함수로 흡수 |
| AutoFixLoop | SkillPipeline + `_shared/retry.py` 유틸 | "3회 재시도 + bail-out"은 패턴. 독립 Service는 오버엔지니어링. 단, 로직 중복 회피 위해 공통 유틸 함수로 추출 (k8s validation / kubectl / build 3곳에서 동일) |
| ContainerBuildRunner | SkillPipeline (build.engine 분기) | 기본값 `skip`이라 사용자 0%가 기본 경로에서 안 만남. opt-in 시에만 SkillPipeline에서 docker/podman/nerdctl 감지 후 호출 |

---

## 스테이지 → 컴포넌트 매핑

| 5-STEP | 주 컴포넌트 | 보조 / 인라인 |
|--------|-----------|------------|
| STEP 1 입력 수집 | SkillPipeline (한국어 질문 + 도움말 사전) | ConfigLoader |
| STEP 2 코드 분석 | ProjectAnalyzer, JvmStackModule (via StackModule) | ConfigLoader |
| STEP 3 아티팩트 생성 | DockerfileGenerator, ManifestGenerator | TemplateRenderer, AtomicWriter |
| STEP 4 검증 게이트 | K8sValidator, KubectlDryRunner | SkillPipeline 인라인 (3회 재시도 + opt-in 빌드) |
| STEP 5 결과 패키징 | OutputPackager | AtomicWriter |

---

## 요구사항 추적 매트릭스 (F-* / US / NFR → 컴포넌트)

### Functional Requirements

| F-ID | 컴포넌트 | 비고 |
|------|---------|------|
| F-01 | SkillPipeline | 5-STEP 파이프라인 |
| F-02, F-02a, F-02b | SkillPipeline | STEP 1 입력 + 한국어 번역 + 도움말 |
| F-03 | ProjectAnalyzer | STEP 2 추론 |
| F-04 | ManifestGenerator | 4종 리소스 (Deployment/Service/SA + Dockerfile) |
| F-05 | SkillPipeline + K8sValidator + KubectlDryRunner | STEP 4 검증 게이트 |
| F-06 | OutputPackager | STEP 5 패키징 |
| F-07, F-08 | SkillPipeline (SKILL.md 본문) | 한국어 description + 자연어 트리거 |
| F-10, F-11 | JvmStackModule | JVM 스택 + Gradle/Maven 판별 |
| F-12, F-13, F-14 | JvmStackModule | 포트 추론 + Boot 2.x/3.x probe |
| F-15 | JvmStackModule.defaults() | 리소스 기본값 |
| F-16 | JvmStackModule | 비-Spring JVM TCP 폴백 |
| F-20, F-21 | DockerfileGenerator + JvmStackModule.build_plan() | multi-stage + 베이스 이미지 |
| F-22, F-23, F-24, F-25 | DockerfileGenerator | 비root + latest 금지 + 보안 주석 + 캐시 |
| F-30, F-31, F-32, F-33, F-34, F-35, F-37 | ManifestGenerator | Deployment/securityContext/probe/리소스/SA + 근거 주석 |
| F-36 | SkillPipeline + ManifestGenerator | Service type 안내(STEP 1) + Service 생성 |
| F-38 | ProjectAnalyzer | 상태성 감지 + 경고 |
| F-39 | ProjectAnalyzer | multi-module 감지 + 비개발자 힌트 |
| F-40, F-41 | K8sValidator | stack-agnostic + Rule ID |
| F-42 | K8sValidator + OutputPackager(README/스펙 문서) | exit code 3단계 + 소비자 가이드 명시 |
| F-43, F-44, F-45, F-46, F-46a | K8sValidator | 규칙 셋 + 메시지 포맷 + SEC-009 시크릿 검출 |
| F-47 | K8sValidator | `--json` 모드 |
| F-50, F-51, F-52 | SkillPipeline + `_shared/retry.py` | 3회 자동 수정 루프 + bail-out + troubleshoot 한국어 요약 |
| F-53, F-54, F-55, F-57, F-58, F-59 | SkillPipeline (인라인) | opt-in 빌드 (build.engine 분기) |
| F-56 | KubectlDryRunner | kubectl 미설치 degrade |
| F-60, F-61, F-62, F-63 | ConfigLoader | 3계층 + 스키마 + stack 강제/auto + rationale 소스 |
| F-70, F-71 | ConfigLoader.resolve_namespace() | 4단계 조회 + default 차단 |
| F-80, F-81, F-82, F-83 | OutputPackager | 출력 디렉토리 + 파일 + rationale + summary.json (skipped 포함) |
| F-90 | TemplateRenderer | 템플릿 외부화 |
| F-91, F-92, F-93 | StackModule (Interface) + ConfigLoader + SkillPipeline | 5 메서드 계약 + stack 강제 + SKILL.md 하드코딩 금지 |
| F-94 | K8sValidator | stack-agnostic 재확인 |
| F-100 | AtomicWriter | output.on_exists 분기 |
| F-101 | OutputPackager | summary.json + exit code 계약 (AIDLC 비종속) |
| F-102 | SkillPipeline (인라인 빌드) | 빌드 타임아웃 |
| F-103 | AtomicWriter | atomic rename + SIGINT 핸들러 + 고아 회수 |

### User Stories (22건 전수)

| US-ID | 주 컴포넌트 |
|-------|-----------|
| US-001 | SkillPipeline (STEP 1 + 한국어 + 도움말) |
| US-002 | ProjectAnalyzer + JvmStackModule |
| US-003 | JvmStackModule.probe_plan() |
| US-004 | DockerfileGenerator |
| US-005 | ManifestGenerator |
| US-006 | ManifestGenerator |
| US-007 | K8sValidator |
| US-008 | KubectlDryRunner |
| US-009 | SkillPipeline + OutputPackager (troubleshoot 한국어 요약) |
| US-010 | ConfigLoader |
| US-011 | ConfigLoader.resolve_namespace() |
| US-012 | OutputPackager (skipped 필드 + rationale 스킵 섹션) |
| US-013 | StackModule + JvmStackModule + TemplateRenderer + K8sValidator (확장성 골격) |
| US-014 | AtomicWriter |
| US-015 | AtomicWriter (output.on_exists) |
| US-016 | SkillPipeline (5-STEP + 한국어 description) |
| US-017 | OutputPackager + K8sValidator (summary.json 계약 + exit code 가이드) |
| US-018 | SkillPipeline (인라인 빌드) |
| US-019 | JvmStackModule (비-Spring) |
| US-020 | DockerfileGenerator |
| US-021 | ProjectAnalyzer (Stateful 경고) |
| US-022 | K8sValidator (WARN 규칙) |

### Non-Functional Requirements (18건 전수)

| NFR-ID | 컴포넌트 / 책임 |
|--------|--------------|
| NFR-01, NFR-SEC-01 | K8sValidator (FAIL: 0 보장) |
| NFR-02, NFR-DET-01 | TemplateRenderer (결정론성 중심) + ManifestGenerator + DockerfileGenerator |
| NFR-03, NFR-SEC-03 | 설계 원칙 2 (생성 전용 경계) — 모든 Adapter 컴포넌트 (KubectlDryRunner / SkillPipeline 빌드 인라인) |
| **NFR-SEC-05** | **CI 통합 테스트 (allowlist 픽스처) — 컴포넌트 외 테스트 레이어** |
| NFR-04, NFR-SEC-04 | KubectlDryRunner + SkillPipeline 빌드 인라인 (네트워크 호출 범위 제한) |
| NFR-05, NFR-PLG-01 | SkillPipeline (`${CLAUDE_PLUGIN_ROOT}` + semver) |
| NFR-06, NFR-PLG-02 | OutputPackager (summary.json 하위호환) |
| NFR-07, NFR-ERR-01, NFR-ERR-02 | SkillPipeline + AtomicWriter (3회 재시도 + atomic write) |
| NFR-08, NFR-EXT-01 | CI 테스트 (StackModule grep + 인터페이스 검증) — 컴포넌트 외 |
| NFR-10, NFR-OBS-01 | OutputPackager (rationale.md 소스 매핑) |
| NFR-11 | SkillPipeline (한국어 description 트리거) |
| NFR-12, NFR-DOC-01 | DockerfileGenerator + ManifestGenerator + CI 테스트 (주석 grep) |
| NFR-13, NFR-TEST-01, NFR-TEST-02 | CI 테스트 (커버리지) — 컴포넌트 외 |
| NFR-14, NFR-TEST-03 | CI 테스트 (flaky 0) — 컴포넌트 외 |
| NFR-15, NFR-SEC-02 | K8sValidator (SEC-009 평문 시크릿) + ManifestGenerator (Secret 생성 안 함) |
| NFR-16, NFR-COMPAT-01 | KubectlDryRunner + SkillPipeline 빌드 인라인 (degraded success) |
| NFR-17 | SkillPipeline + ProjectAnalyzer + K8sValidator + OutputPackager (전 STEP 한국어 + 원어 병기) |

**커버리지** (자동 집계 검증): F-* 71/71 (100%), US 22/22 (100%), NFR 17/17 (100%)
- **F-09 reserved** (의도적 미사용, requirements.md ID 인벤토리 참조)
- **NFR-09 removed** (성능, v0.2+ 검토)
- **NFR-SEC-05 신규** (경계 엔포스먼트 CI 감지)
- 자동 집계 명령: `grep -oE '^\| F-[0-9]+[a-z]?' requirements.md | sort -u | wc -l` → 71

---

## UX 결정 (2026-04-17)

**대상 사용자**: JVM 개발자 + AI-assisted 개발자 (비개발자 포함)

### v0.1.0 포함

- **용어 번역** (F-02a): SkillPipeline STEP 1 한국어 의도 질문
- **인라인 도움말** (F-02b): 각 질문에 "? 도움말" 옵션
- **도움말 카탈로그 스키마** (DETAIL에서 명시):
  ```yaml
  term_id: "service_type"
  ko_short: "어디서 접속할 건가요?"
  ko_detail: "사내 네트워크만 접속할지, 외부 인터넷에서도 접속할지 결정해요. 외부 공개는 클라우드 비용이 발생할 수 있어요."
  original: "Service type (ClusterIP/NodePort/LoadBalancer)"
  example: "사내 백엔드 API: ClusterIP / 모바일 앱 백엔드: LoadBalancer"
  ```
  v0.1.0은 SKILL.md 본문에 정적 포함. 외부 파일 분리는 v0.2+
- **메시지 정책 전 STEP 확대** (NFR-17): STEP 1뿐 아니라 STEP 2 추론 실패 질문, STEP 4 검증 실패, troubleshoot.md까지 한국어 요약 + 원어 병기
- **multi-module 비개발자 힌트** (F-39): "API 서버는 보통 `-api` 또는 `-web` 모듈입니다"
- **troubleshoot.md 한국어 요약** (F-52): 상단 1-2줄 요약 의무

### v0.2+ 백로그

- **프리셋/프로파일** ("웹 API(외부 공개) / 내부 서비스 / 데모" 일괄) — MVP 피드백 후 결정
- **스택 확장** (Python/Node/Go/React) — 비개발자 타깃 본격화
- **NetworkPolicy 생성** (zero-trust default deny + 명시 허용) — 운영 감사 대응
- **PodDisruptionBudget / topologySpreadConstraints** WARN 규칙 (`RES-W02`) — 노드 드레인 안전성
- **Stateful 감지 신뢰도 점수** (runtime env 기반 false-negative 보완) — 페르소나 P3-5
- **LoadBalancer 비용 경고 문구** (월 $20~ 등) — 페르소나 P3-6
- **StackModule BuildPlan 일반화** (`stages: list`) — Go/React 추가 직전 필수
- **validate_k8s.py WARN 확장**: `terminationGracePeriodSeconds`, `imagePullPolicy: Always` (digest pin 없을 때)
- **도움말 카탈로그 외부 파일 분리** (다국어/커스터마이징)
- **외부 CLI Adapter 베이스 추상화** (KubectlDryRunner + SkillPipeline 빌드 인라인 공통화) — v0.2+ 스택 추가 시 검증 어댑터 늘어나면 도입

---

## 5-STEP 시퀀스 다이어그램 (ASCII)

### STEP 1: 입력 수집 + 도움말 흐름

```
User             SkillPipeline       ConfigLoader     HelpCatalog (자체 컴포넌트)
 |                    |                    |                  |
 |                    |--load(project)---->|                  |
 |                    |<---ResolvedConfig--|                  |
 |                    |  (source_map)      |                  |
 |                    |                    |                  |
 |                    |--stack_decision(config, dir)>          |
 |                    |<--StackDecision----|                  |
 |                    |                    |                  |
 |<-앱 이름 질문(KO)--|                    |                  |
 |                    |                    |                  |
 |--"? 도움말"------->|                    |                  |
 |                    |--HelpCatalog.lookup('app_name')------>|
 |                    |<--HelpEntry(step=1)------------------|
 |<--ko_short + 예시--|                    |                  |
 |--앱 이름 입력----->|                    |                  |
 |                    |                    |                  |
 |<-노출 방식 질문(KO)|                    |                  |
 |--"외부 공개"------>|                    |                  |
 |                    |--HelpCatalog.lookup('exposure')------>|
 |                    |<--경고: LB 비용----------------------|
 |<--LB 비용 안내-----|                    |                  |
 |                    |                    |                  |
 |<-namespace 질문----|                    |                  |
 |--입력------------->|                    |                  |
 |                    |--resolve_namespace(config,input,dir)>  |
 |                    |<--NamespaceResolution-                 |
 |                    |  (4단계 조회 적용) |                  |
 |                    |                    |                  |
 |--출력 디렉토리---->|                    |                  |
 |--리소스 힌트------>|                    |                  |
 |                    |                    |                  |
 |              [UserInputs 완성]          |                  |
```

### STEP 2: 코드 분석 + 추론 실패 분기

```
SkillPipeline    ProjectAnalyzer    ConfigLoader   JvmStackModule    User
 |                    |                    |                |              |
 |--analyze(dir,cfg)->|                    |                |              |
 |                    |--stack_decision(cfg, dir)>           |              |
 |                    |<--StackDecision(forced=None)---------|             |
 |                    |                    |                |              |
 |                    |--detect(dir)----------------------->|              |
 |                    |<--StackDetectResult-----------------|              |
 |                    |  (port=None, framework=spring)      |              |
 |                    |                    |                |              |
 |                    |  [port 추론 실패]  |                |              |
 |                    |  AnalysisResult.gaps.add('port')    |              |
 |                    |                    |                |              |
 |<--gaps 콜백 (prompt_callback)-----                       |              |
 |--포트 질문(KO)----------------------------------------------->|         |
 |<--사용자 입력 8080-------------------------------------------|          |
 |                    |                    |                |              |
 |   [multi-module 감지]                                                   |
 |<--prompt_callback (module 선택)------                                  |
 |--힌트와 함께 질문--------------------------------------------->|        |
 |  ("API는 보통 -api")                                       |            |
 |<--사용자 선택 'api-module'------------------------------------|         |
 |                    |                    |                |              |
 |                    |--build_plan(detect_result)--------->|              |
 |                    |--probe_plan(detect_result)--------->|              |
 |                    |--defaults()------------------------>|              |
 |                    |--artifact_locator(detect_res, dir)->|              |
 |                    |                                                    |
 |                    |--_detect_statefulness(dir, module)->                |
 |                    |  StatefulnessSignal(confidence=low)                 |
 |<--Stateful 경고 콜백|                                                    |
 |--경고 안내(KO)----------------------------------------------->|         |
 |                    |                                                    |
 |<---AnalysisResult--|                                                    |
```

### STEP 3: 아티팩트 생성 (Atomic Write)

```
SkillPipeline    AtomicWriter      DockerfileGen     ManifestGen
 |                    |                    |              |
 |--__enter__()------>|                    |              |
 |  signal handler    |                    |              |
 |  .tmp-{uuid}/ 생성 |                    |              |
 |  GC orphans        |                    |              |
 |<-staging_dir------|                     |              |
 |                    |                    |              |
 |--generate(build_plan, inputs, defaults)->|             |
 |   (내부적으로 TemplateRenderer.render_dockerfile() 호출)|
 |<--Dockerfile str---|--------------------|              |
 |                    |                    |              |
 |--write Dockerfile to staging_dir-------->                |
 |                    |                    |              |
 |--generate_deployment(inputs, analysis,---------------->  |
 |   defaults, probe)  |                                  |
 |   (내부적으로 TemplateRenderer.render_manifest('deployment') 호출)|
 |<--deployment.yaml str------------------------|         |
 |                    |                                   |
 |--generate_service(inputs)--------------------------->  |
 |<--service.yaml str-------------------------------|     |
 |                    |                                   |
 |--generate_serviceaccount(inputs)-------------------->  |
 |<--serviceaccount.yaml str------------------------|     |
 |                    |                                   |
 |--write deployment.yaml/service.yaml/serviceaccount.yaml to staging_dir
 |                                                        |
 |  [STEP 4 진입 — staging_dir 대상]                       |
```

### STEP 4: 검증 게이트 + 3회 재시도 + bail-out

```
SkillPipeline    K8sValidator    KubectlDryRunner   _shared/retry.py
 |                    |                    |                |
 |--retry_with_fix(                                         |
 |    operation=lambda: K8sValidator.validate(manifest_paths),
 |    fix_attempt=lambda r: _fix_k8s(r, staging_dir),       |
 |    success_predicate=lambda r: r.exit_code != 1,         |
 |  )--------------------------------------------------->   |
 |                    |                                     |
 |    attempt 1:                                            |
 |  -- operation() ---->                                    |
 |--validate(manifest_paths: list[Path])--->                |
 |<--ValidationReport(fail=2, exit_code=1)-                 |
 |  (success_predicate False)                               |
 |  -- fix_attempt(result) ---->                            |
 |  → FixOutcome(applied=True, summary_ko='SEC-001 추가')   |
 |--update files in staging_dir                             |
 |                    |                                     |
 |    attempt 2:                                            |
 |--validate(manifest_paths)>                               |
 |<--ValidationReport(fail=0,warn=1, exit_code=2)--         |
 |  (success_predicate True — soft-success)                 |
 |<--RetryResult(success=True, attempts=[a1,a2])----        |
 |                                                          |
 |--retry_with_fix(                                         |
 |    operation=lambda: KubectlDryRunner.dry_run(staging_dir),
 |    fix_attempt=lambda r: _fix_dry_run(r, staging_dir),   |
 |    success_predicate=lambda r: r.success,                |
 |  )--------------------------------------------------->   |
 |                                                          |
 |--is_available()-------> (KubectlDryRunner)               |
 |<--True (또는 False → skipped 분기)                       |
 |--dry_run(staging_dir)->|                                 |
 |<--DryRunResult(success=True, skipped=False)-             |
 |  ⎡ kubectl 미설치 시: skipped=True, skip_reason_ko 포함  |
 |  ⎣ → ValidationOutcome.skipped += ['kubectl_dry_run']    |
 |                                                          |
 |  [build.engine != 'skip'이면]                            |
 |--_build_container_image(staging_dir) 인라인               |
 |  엔진 감지(docker/podman/nerdctl, allowlist 준수)        |
 |  미감지 시: ValidationOutcome.skipped += ['container_build']
 |                                                          |
 |  [ValidationOutcome 구성 → STEP 5로 pass-through]        |
 |                                                          |
 |  ─── bail-out 시나리오 (3회 모두 실패) ───                |
 |    attempt 3 fail → RetryResult(success=False, bailout=True)
 |--BailOutError(STEP=4, comp='K8sValidator',                |
 |     ko_summary=구성된 요약, attempts=[a1,a2,a3])->        |
 |  OutputPackager.write_troubleshoot()                      |
 |  (상단 한국어 1-2줄 요약 + 전체 attempts 로그)            |
 |  AtomicWriter.cleanup() (staging 폐기, output_dir 이전 보존)|
 |  exit(1)                                                  |
```

### STEP 5: 패키징 + skipped 기록

```
SkillPipeline    OutputPackager    AtomicWriter
 |                    |                    |
 |--write(staging,    |                    |
 |  inputs, analysis, |                    |
 |  validation,       |                    |
 |  source_map)------>|                    |
 |                    |                    |
 |     [validation.skipped 결정]            |
 |     - kubectl 미감지: ["kubectl_dry_run"]|
 |     - build.engine=skip: ["container_build"]|
 |                    |                    |
 |     write_summary_json()                |
 |       schema v1, UTC, validation.skipped|
 |     write_rationale_md()                |
 |       source_map → 각 값 출처 표기      |
 |       스킵된 검증 섹션 포함             |
 |                    |                    |
 |<--PackagingResult--|                    |
 |                    |                    |
 |--commit()----------------------->|       |
 |   on_exists 분기:                |       |
 |     prompt → 사용자 확인         |       |
 |     overwrite → atomic rename    |       |
 |     suffix → output_dir-{ts}/    |       |
 |<--final_dir------                |       |
 |                                  |       |
 |--__exit__() (정상)--------------->|      |
 |   signal handler 해제, .tmp-* 삭제|      |
 |                                  |       |
 [exit(0) 또는 exit(2) — soft-success 시]
```

---

## NFR Design Patterns

> ⚠️ NFR 패턴 선택은 운영 환경과 비용에 따라 달라집니다.
> 기술 담당자와 상의를 권장합니다.

### 보안 — 생성물 품질 (NFR-SEC-01, NFR-SEC-02)

| 패턴 | 장점 | 단점 | 비용 영향 |
|------|------|------|----------|
| **A. 정적 규칙 셋 (현재 선택)** — `validate_k8s.py` 내장 SEC-* 규칙 | 결정론적, 오프라인, 설명 가능 | 새 위협 대응 시 코드 수정 필요 | 0 (스킬 내장) |
| B. 외부 정책 엔진 (OPA/Conftest) | Rego DSL로 규칙 분리, 커뮤니티 정책 재사용 | 외부 의존성 추가, OPA 학습 곡선 | OPA 프로세스 호출 비용 + 의존성 |
| C. Kyverno admission 규칙 검증 | 클러스터 정책과 동일 규칙 사용 | 클러스터 의존성 (스킬 경계 위반) | 클러스터 호출 |

**v0.1.0 결정**: A (생성 전용 경계 + MVP 단순성)

### 결정론성 (NFR-DET-01)

| 패턴 | 장점 | 단점 | 비용 영향 |
|------|------|------|----------|
| **A. Jinja2 + 키 정렬 (현재 선택)** | 인기 템플릿 엔진, 디버깅 쉬움, 결정론적 | YAML 키 정렬 별도 로직 필요 | Jinja2 의존성 +1 |
| B. 코드 생성 (PyYAML.dump + 파이썬 dict 직조립) | 외부 템플릿 의존성 0 | 템플릿 가독성 낮음, 사용자 커스터마이징 어려움 | 0 |
| C. cdk8s / Pulumi | 타입 안전, k8s 객체 모델 내장 | TypeScript/Python SDK 학습, 무거움 | SDK 의존성 + 빌드 시간 |

**v0.1.0 결정**: A (브레인스토밍 OQ-04 해결)

### 에러 복구 — Atomic Write (NFR-ERR-01, NFR-ERR-02)

| 패턴 | 장점 | 단점 | 비용 영향 |
|------|------|------|----------|
| **A. tmp 디렉토리 + atomic rename + signal handler (현재 선택)** | 원자성 보장, 부분 파일 0 | 디스크 사용 일시 2배, signal handler 보일러플레이트 | 0 |
| B. 백업 + 직접 쓰기 (기존을 .bak으로 옮긴 뒤 새로 쓰기) | 단순 구현 | 중간 실패 시 .bak 복원 로직 필요 | 0 |
| C. 트랜잭션 라이브러리 (pyfilesystem 등) | API 추상화 | 의존성 추가, 마법 행위 | 라이브러리 의존성 |

**v0.1.0 결정**: A (페르소나 Must-fix 반영, 시작 시 7일 이상 고아 자동 회수 추가)

### 경계 엔포스먼트 (NFR-SEC-05)

| 패턴 | 장점 | 단점 | 비용 영향 |
|------|------|------|----------|
| **A. CI 감지 테스트 (subprocess 패치, 현재 선택)** | 테스트만 수정, 런타임 영향 0, 회귀 방지 효과 큼 | 테스트 환경 외에서는 가드 없음 | 0 |
| B. 런타임 wrapper (`subprocess.run`을 monkey-patch) | 우발적 호출도 차단 | 우회 가능 (직접 os.exec), 디버깅 어려움 | 약간의 런타임 오버헤드 |
| C. 권한 분리 컨테이너 (rootless + capabilities drop) | 강력한 시스템 가드 | MVP 스코프 초과, 사용자 환경 제약 | 컨테이너 런타임 의존성 |

**v0.1.0 결정**: A (런타임 가드 오버엔지니어링 회피, 회귀 방지가 목적)

### 국제화 — 메시지 정책 (NFR-17)

| 패턴 | 장점 | 단점 | 비용 영향 |
|------|------|------|----------|
| **A. 한국어 우선 + 원어 병기 인라인 (현재 선택)** | 단일 코드베이스, 비개발자/개발자 모두 대응 | 메시지마다 두 언어 작성 부담 | 0 |
| B. gettext 기반 i18n (.po 파일) | 다국어 확장 용이 | MVP에 과함, 빌드 단계 추가 | gettext 의존성 |
| C. 한국어 단독 (영문 제거) | 단순 | 원어 검색/디버깅 어려움 | 0 |

**v0.1.0 결정**: A (도움말 카탈로그 외부 파일 분리는 v0.2+에서 i18n 검토)

---

## 컴포넌트 상세 설계 (DETAIL — Comprehensive)

> 표기 규약:
> - 시그니처는 Python 3.11+ 타입 힌트 기준
> - 입력/출력 타입은 `_shared/types.py`에 정의 (DETAIL 산출물)
> - 예외는 `_shared/errors.py`의 `DevflowError` 계열
> - 의존성 방향: `A → B`는 "A가 B를 호출"

### 1. SkillPipeline (Controller)

**Responsibility**: 5-STEP 파이프라인 전체 오케스트레이션. SKILL.md 본문이 Claude 프롬프트로 각 STEP을 진행. 도움말 카탈로그 소유. 3회 자동 수정 루프 인라인 처리. opt-in 컨테이너 빌드 분기. 메시지 정책(NFR-17) 진입점.

**Public interface** (논리적 — SKILL.md 본문이지만 진행 의사결정 포인트):

```
step1_collect_inputs(config: ResolvedConfig) -> UserInputs
  입력: ResolvedConfig (ConfigLoader 결과)
  출력: UserInputs(app_name, port, exposure, namespace, output_dir, resource_hint)
  예외: UserAbort (사용자 Ctrl+C / 거부)
  메시지: 한국어 의도 질문 + "? 도움말" 분기 (HelpCatalog 조회)

step2_analyze_project(project_dir: Path, config: ResolvedConfig) -> AnalysisResult
  내부적으로 ProjectAnalyzer.analyze() 호출
  추론 실패 항목은 한국어 질문으로 사용자에게 다시 묻기

step3_generate_artifacts(inputs: UserInputs, analysis: AnalysisResult) -> GeneratedArtifacts
  AtomicWriter 컨텍스트 안에서 DockerfileGenerator + ManifestGenerator 호출

step4_validate_gate(artifacts: GeneratedArtifacts, staging_dir: Path) -> ValidationOutcome
  retry_with_fix() 유틸로 3회 재시도 (각 호출은 lambda 래퍼로 인자 캡처):
    retry_with_fix(
      operation=lambda: K8sValidator.validate(artifacts.manifest_paths),
      fix_attempt=lambda result_or_err: _fix_k8s(result_or_err, staging_dir),
      success_predicate=lambda r: r.exit_code != 1,
    )
    retry_with_fix(
      operation=lambda: KubectlDryRunner.dry_run(staging_dir),
      fix_attempt=lambda result_or_err: _fix_dry_run(result_or_err, staging_dir),
      success_predicate=lambda r: r.success,
    )
  build.engine != skip이면 _build_container_image(staging_dir) 인라인 호출 (동일 retry 패턴)
  ValidationOutcome.skipped: list[str] — kubectl/build 미감지 식별자 (F-56/F-58, OutputPackager로 pass-through)

step5_package(artifacts, validation, analysis) -> PackagingResult
  OutputPackager.write() 호출 + AtomicWriter rename 트리거
```

**Dependencies** (방향: SkillPipeline → 호출 대상):
```
SkillPipeline → ConfigLoader (STEP 1 진입 시)
SkillPipeline → ProjectAnalyzer (STEP 2)
SkillPipeline → DockerfileGenerator, ManifestGenerator (STEP 3)
SkillPipeline → AtomicWriter (STEP 3~5 컨텍스트, prompt 콜백 주입)
SkillPipeline → K8sValidator, KubectlDryRunner (STEP 4)
SkillPipeline → OutputPackager (STEP 5)
SkillPipeline → _shared/retry.py (재시도 유틸)
SkillPipeline → HelpCatalog (도움말 사전, 컴포넌트 인터페이스 — 아래 정의)
```

**Data Owned**:
- `HelpCatalog`: 용어 ID → 도움말 항목 (정적, SKILL.md 본문에 포함). 컴포넌트로 노출:
  ```python
  class HelpCatalog:
      def lookup(self, term_id: str) -> HelpEntry | None:
          """term_id로 HelpEntry 조회. 없으면 None.
          HelpEntry(term_id, ko_short, ko_detail, original, example, step: Literal[1, 2, 'config'])"""
      def for_step(self, step: Literal[1, 2, 'config']) -> list[HelpEntry]:
          """STEP 1 입력용 / STEP 2 추론 실패용 / 설정용 분류."""
  ```
- `PipelineState`: 현재 STEP 진행 상태 (메모리, 영속화 안 함)
- `MessagePolicy`: 한국어 + 원어 병기 포맷터 (NFR-17 진입점)

**Exceptions**:
- `UserAbort` — 사용자 거부/Ctrl+C → AtomicWriter cleanup 트리거
- `BailOutError` — 3회 재시도 실패 → troubleshoot.md 한국어 요약 작성 후 종료
- `ConfigError` — 설정 파싱 실패는 ConfigLoader 영역, SkillPipeline은 graceful degrade로 기본값 진행

**Interactions**: 5-STEP 시퀀스 다이어그램 참조 (DETAIL 2)

---

### 2. ConfigLoader (Service)

**Responsibility**: 3계층 설정(프로젝트/조직/내장) YAML 파싱 + 우선순위 병합. `stack` 강제/auto 분기(F-62/F-92). namespace 4단계 조회(F-70/F-71) 흡수. YAML 파싱 실패 시 graceful degrade.

**Public interface**:

```python
class ConfigLoader:
    def load(self, project_dir: Path) -> ResolvedConfig:
        """3계층 병합 결과 반환. 파싱 실패 시 기본값 + warning 기록."""
        # 우선순위: project_dir/.devflow-k8s-deploy.yml > ~/.claude/devflow-k8s-deploy.yml > built-in
        # 출력: ResolvedConfig (frozen dataclass) with .source_map: dict[str, str] (각 필드별 출처)

    def resolve_namespace(
        self,
        config: ResolvedConfig,
        user_input: str | None,
        project_dir: Path,
    ) -> NamespaceResolution:
        """4단계 조회: project config → org config → user input → project dir name 제안.
        'default' 자동 배정 금지. user_input이 'default'이면 명시 확인 필요 표시."""
        # 출력: NamespaceResolution(value: str, source: Literal[...], requires_confirmation: bool)

    def stack_decision(self, config: ResolvedConfig, project_dir: Path) -> StackDecision:
        """stack: auto이면 None 반환 (ProjectAnalyzer가 자동 감지).
        명시값이면 해당 stack 강제. 미지원 stack(go/python/react in v0.1.0)이면 명시 에러."""
        # 출력: StackDecision(forced_stack: str | None, source: str)
```

**Dependencies** (사용):
- 표준 라이브러리: `pathlib`, `pyyaml`
- 내장 기본값 사전: `_shared/defaults.py`

**Data Owned**:
- `ResolvedConfig` 인스턴스 (호출 시점 스냅샷)
- `source_map`: 각 최종값의 출처 레이어 (rationale.md용)

**Exceptions**:
- 파싱 실패 → 예외 throw 안 함. `ResolvedConfig.warnings: list[str]`에 기록 + 기본값 사용
- `UnsupportedStackError` — `stack: go`/`python`/`react`를 v0.1.0에서 명시 시 raise (명시 사용자 의도이므로)

**Interactions**:
```
SkillPipeline → ConfigLoader.load() → (ResolvedConfig)
SkillPipeline → ConfigLoader.resolve_namespace(config, user_input, dir) → (NamespaceResolution)
ProjectAnalyzer → ConfigLoader.stack_decision(config, dir) → (StackDecision)
OutputPackager → ResolvedConfig.source_map 읽기 (rationale.md 작성)
```

---

### 3. ProjectAnalyzer (Service)

**Responsibility**: STEP 2 분석 오케스트레이션. ConfigLoader.stack_decision() 결과로 StackModule 라우팅. multi-module 감지 + 비개발자 친화 힌트. 상태성 감지 + 신뢰도 표시. 추론 실패 시 한국어 우선 질문(NFR-17).

**Public interface**:

```python
class ProjectAnalyzer:
    def __init__(
        self,
        config_loader: ConfigLoader,
        stack_registry: dict[str, StackModule],
        prompt_callback: Callable[[PromptRequest], str] | None = None,
    ):
        """config_loader: stack_decision() 호출용 의존성.
        stack_registry: v0.1.0 = {"jvm": JvmStackModule()}.
        prompt_callback: SkillPipeline에서 주입 (multi-module 선택, gaps 보충 질문).
                         None이면 자동 추론 + AnalysisResult.gaps만 채움 (테스트 모드)."""
        ...

    def analyze(self, project_dir: Path, config: ResolvedConfig) -> AnalysisResult:
        """전체 분석 흐름. 추론 실패 항목은 AnalysisResult.gaps에 기록."""
        # 1. self.config_loader.stack_decision(config, project_dir) → StackDecision
        # 2. forced_stack 있으면 해당 모듈, 없으면 _detect_stack()
        # 3. multi-module이면 _select_module() (prompt_callback 호출, 한국어 힌트)
        # 4. 선택된 module의 detect() / build_plan() / probe_plan() / defaults() 호출
        # 5. _detect_statefulness() — 신뢰도 점수와 함께
        # 출력: AnalysisResult

    def _detect_stack(self, project_dir: Path) -> StackDetectResult:
        """v0.1.0: JvmStackModule.detect()만 시도. 결과 없으면 UnknownStackError."""

    def _select_module(self, modules: list[ModuleInfo]) -> ModuleInfo:
        """multi-module 사용자 선택 프롬프트. 한국어 힌트 포함:
        '여러 모듈이 있어요. API 서버는 보통 -api 또는 -web으로 끝나요.'"""

    def _detect_statefulness(self, project_dir: Path, module: ModuleInfo) -> StatefulnessSignal:
        """build.gradle/pom.xml 의존성 + application.yml의 datasource/PVC 시그널 검사.
        출력: StatefulnessSignal(is_stateful: bool, confidence: Literal['high','medium','low'], reasons: list[str])
        confidence='low'이면 rationale.md에 'Stateful 감지 신뢰도 낮음' 경고."""
```

**Dependencies**:
- ConfigLoader (stack_decision)
- StackModule (5 메서드 호출)
- 사용자 프롬프트는 SkillPipeline 콜백을 통해 (ProjectAnalyzer는 직접 stdin 안 읽음 — 테스트성)

**Data Owned**:
- `AnalysisResult`: 분석 결과 + gaps(추론 실패) + StatefulnessSignal

**Exceptions**:
- `UnknownStackError` — 어떤 StackModule도 감지하지 못함. SkillPipeline에서 사용자에게 stack 명시 요청
- `MultiModuleAbort` — 사용자가 모듈 선택 거부 → UserAbort로 변환

**Interactions**:
```
SkillPipeline → ProjectAnalyzer.analyze(project_dir, config)
                ProjectAnalyzer → ConfigLoader.stack_decision()
                ProjectAnalyzer → JvmStackModule.detect() / build_plan() / probe_plan()
                ProjectAnalyzer → (사용자 프롬프트 콜백) [multi-module / Stateful 경고]
                ← AnalysisResult
```

---

### 4. StackModule (Interface, Adapter)

**Responsibility**: 스택별 5 메서드 계약. v0.2+에서 Go/Python/React 추가의 확장 슬롯. v0.1.0은 BuildPlan이 JDK/JRE 2단계 가정 — v0.2 BuildPlan 일반화는 백로그.

> **F-91 시그니처 정합 (DETAIL 보강)**: requirements.md F-91은 `build_plan() -> BuildPlan`이지만 실제로는 `detect()` 결과(framework/version)에 따라 BuildPlan이 달라지므로 `build_plan(detect_result: StackDetectResult)`로 확장. F-91 텍스트는 다음 requirements.md 동기화 시 업데이트 (Change Log에 명시).

**Interface (abstract)**:

```python
class StackModule(Protocol):
    name: ClassVar[str]  # "jvm", "go", "python", "react"

    def detect(self, project_dir: Path) -> StackDetectResult | None:
        """이 스택인지 감지. 아니면 None.
        StackDetectResult(port: int | None, entrypoint: str, framework: str, version: str | None)"""

    def build_plan(self, detect_result: StackDetectResult) -> BuildPlan:
        """detect_result 기반 BuildPlan 생성.
        BuildPlan(builder_image: str, runner_image: str, build_cmd: str, artifact_path: str)
        v0.2+ 일반화: BuildPlan(stages: list[Stage]) 구조로 변경 예정 (백로그)"""

    def probe_plan(self, detect_result: StackDetectResult) -> ProbeConfig:
        """ProbeConfig(liveness: ProbeSpec, readiness: ProbeSpec)
        ProbeSpec = HttpProbe(path, port) | TcpProbe(port)"""

    def defaults(self) -> ResourceDefaults:
        """ResourceDefaults(cpu_request, memory_request, cpu_limit, memory_limit)
        + 추가: writable_paths: list[str]  (emptyDir 마운트 대상)"""

    def artifact_locator(self, detect_result: StackDetectResult, project_dir: Path) -> list[Path]:
        """생성된 jar/binary/static asset 경로 후보. Dockerfile COPY에 사용."""
```

**Dependencies**: 없음 (Pure interface)

**Data Owned**: 없음 (구현체별)

**Exceptions**:
- 모든 메서드는 실패 시 stack-specific 예외 raise. ProjectAnalyzer가 catch.

---

### 5. JvmStackModule (Adapter)

**Responsibility**: Kotlin/Java Spring 감지. Gradle KTS/Groovy/Maven 빌드 시스템 판별. Boot 2.x/3.x 버전 + 포트 + actuator 추론. 기본 쓰기 경로(`/tmp` + `/var/log` + Tomcat work dir) 노출.

**Public interface** (StackModule 구현):

```python
class JvmStackModule:
    name = "jvm"

    def detect(self, project_dir: Path) -> StackDetectResult | None:
        """판별 우선순위:
        1. build.gradle.kts (Kotlin DSL)
        2. build.gradle (Groovy)
        3. pom.xml (Maven)
        4. settings.gradle(.kts) — multi-module 시그널만, detect는 root 기준
        Spring Boot 의존성 발견 시 framework='spring-boot', 버전 추출.
        그 외 JVM이면 framework='ktor'/'micronaut'/'jvm-generic' (식별 불가 시 generic)."""

    def build_plan(self, detect_result) -> BuildPlan:
        """builder_image: eclipse-temurin:{jdk_version}-jdk-alpine (default 21)
        runner_image: eclipse-temurin:{jdk_version}-jre-alpine
        build_cmd: detect_result.framework에 따라 'gradle bootJar' / 'mvn package'
        artifact_path: build/libs/*.jar (Gradle) | target/*.jar (Maven)"""

    def probe_plan(self, detect_result) -> ProbeConfig:
        """Boot 2.x + actuator: HttpProbe('/actuator/health', port) for both
        Boot 3.x + actuator: HttpProbe('/actuator/health/liveness'), HttpProbe('/actuator/health/readiness')
        actuator 미감지 / 비-Spring: TcpProbe(port) 폴백
        actuator 감지 = application.yml의 management.endpoints.web.exposure.include 확인"""

    def defaults(self) -> ResourceDefaults:
        """cpu_request='100m', memory_request='512Mi', cpu_limit='1000m', memory_limit='1Gi'
        writable_paths=['/tmp', '/var/log']  # Tomcat work dir는 /tmp 흡수"""

    def artifact_locator(self, detect_result, project_dir) -> list[Path]:
        """Gradle: project_dir / 'build/libs' / '*.jar' (fat jar 우선, plain jar 제외)
        Maven: project_dir / 'target' / '*.jar' (spring-boot-maven-plugin 산출물 우선)"""

    # 내부 헬퍼
    def _detect_boot_version(self, build_files: list[Path]) -> str | None:
        """build.gradle(.kts) → spring-boot-gradle-plugin 버전 / spring-boot-starter 의존성 버전
        pom.xml → parent spring-boot-starter-parent 버전"""

    def _detect_actuator(self, project_dir: Path) -> bool:
        """spring-boot-starter-actuator 의존성 + application(-{profile}).yml/properties의
        management.endpoints.web.exposure.include 값에 'health' 포함 여부"""

    def _detect_port(self, project_dir: Path) -> int:
        """F-12 우선순위: SERVER_PORT env (Dockerfile 컨텍스트 외이므로 스킵) →
        application-{profile}.yml/properties → application.yml/properties → 8080"""
```

**Dependencies**:
- `pyyaml`, `re`, `pathlib`
- 내부적으로 `lxml` 또는 `xml.etree.ElementTree` (pom.xml 파싱)

**Data Owned**:
- 없음 (stateless, 호출 시 디스크 읽기)

**Exceptions**:
- `JvmDetectionError` — build 파일은 있으나 파싱 불가
- 메서드들은 실패 시 None 또는 fallback 반환 — 가능한 한 graceful

---

### 6. TemplateRenderer (Util)

**Responsibility**: Jinja2 기반 템플릿 렌더링. **결정론성 중심지** — 고정 키 순서, 고정 렌더 컨텍스트 정렬, 빈 라인 정규화.

**Public interface**:

```python
class TemplateRenderer:
    def __init__(self, template_root: Path):
        # template_root = ${CLAUDE_PLUGIN_ROOT}/templates
        # Jinja2 Environment with autoescape=False (YAML/Dockerfile은 escape 안 함)
        # finalize=lambda x: x if x is not None else ''  # None을 빈 문자열로

    def render_dockerfile(self, stack: str, context: dict) -> str:
        """templates/dockerfile/{stack}.tmpl 렌더링.
        context 키는 정렬되어 전달 (결정론성)."""

    def render_manifest(self, kind: str, context: dict) -> str:
        """templates/manifest/{kind}.tmpl 렌더링 (kind = 'deployment'/'service'/'serviceaccount').
        YAML dump 시 sort_keys=False (템플릿 순서 우선) + default_flow_style=False."""

    def _normalize(self, content: str) -> str:
        """연속 빈 라인 1개로 정규화. trailing whitespace 제거. EOF에 정확히 1개 newline."""
```

**Dependencies**:
- Jinja2 3.x
- `pyyaml` (manifest 변수 직렬화 시)

**Data Owned**:
- Jinja2 `Environment` 인스턴스 (캐시)

**Exceptions**:
- `TemplateNotFoundError` — `templates/{stack}.tmpl` 없음
- `TemplateSyntaxError` — Jinja2 표준 예외 그대로 전파 (개발자 버그)

---

### 7. DockerfileGenerator (Service)

**Responsibility**: multi-stage Dockerfile 생성. JDK builder → JRE runner. 비root 사용자. `latest` 금지. 보안 주석 주입. Gradle/Maven 캐시 레이어 최적화(F-25).

**Public interface**:

```python
class DockerfileGenerator:
    def __init__(self, renderer: TemplateRenderer):
        ...

    def generate(self, build_plan: BuildPlan, inputs: UserInputs, defaults: ResourceDefaults) -> str:
        """Dockerfile 문자열 반환.
        포함:
          - FROM {builder_image} AS builder + 의존성 캐시 레이어 + 소스 복사 + build_cmd
          - FROM {runner_image} + RUN groupadd/useradd appuser + COPY --from=builder --chown
          - USER appuser (CMD 직전)
          - HEALTHCHECK는 v0.1.0 미포함 (probes로 대체)
        보안 주석:
          - # 비root 사용자 — 컨테이너 탈출 공격 시 호스트 root 권한 차단
          - # latest 태그 금지 — 재현성 + 공급망 공격 방지
          - # COPY --chown — 임의 사용자 ID 충돌 방지"""

    def _validate_image_tag(self, image: str) -> None:
        """latest 또는 태그 누락 시 raise InvalidImageError."""
```

**Dependencies**: TemplateRenderer

**Data Owned**: 없음

**Exceptions**: `InvalidImageError`(latest 사용 시)

---

### 8. ManifestGenerator (Service)

**Responsibility**: Deployment/Service/ServiceAccount YAML 생성. Pod/Container securityContext + probes + 리소스 + 근거 주석. emptyDir 기본 마운트(`/tmp` + `/var/log`). Service type 안내.

**Public interface**:

```python
class ManifestGenerator:
    def __init__(self, renderer: TemplateRenderer):
        ...

    def generate_deployment(
        self,
        inputs: UserInputs,
        analysis: AnalysisResult,
        defaults: ResourceDefaults,
        probe: ProbeConfig,
    ) -> str:
        """deployment.yaml 문자열.
        포함:
          - metadata.name = inputs.app_name, namespace = inputs.namespace
          - spec.replicas (default 2 — v0.1.0은 고정값, v0.2+에서 설정화)
          - spec.template.spec.serviceAccountName = '{app_name}-sa'
          - spec.template.spec.automountServiceAccountToken: false
          - Pod securityContext (F-31)
          - Container securityContext (F-32) + emptyDir 볼륨 [/tmp, /var/log] 자동 마운트
          - resources (F-33)
          - probes (F-34, ProbeConfig 따름)
        근거 주석 (F-37):
          - securityContext 필드: # 컨테이너 권한 분리 — privileged escalation 방지
          - resources: # 리소스 한도 — OOMKill로 다른 Pod 영향 방지
          - probes: # 헬스체크 — 비정상 인스턴스 자동 제거"""

    def generate_service(self, inputs: UserInputs) -> str:
        """service.yaml. type = inputs.exposure.
        targetPort = container port (Dockerfile EXPOSE와 일치)."""

    def generate_serviceaccount(self, inputs: UserInputs) -> str:
        """serviceaccount.yaml.
        name = '{app_name}-sa', automountServiceAccountToken: false."""
```

**Dependencies**: TemplateRenderer

**Data Owned**: 없음

**Exceptions**: 없음 (입력 검증은 SkillPipeline 영역)

---

### 9. K8sValidator (Service — 실행 가능 모듈 `validate_k8s.py`)

**Responsibility**: stack-agnostic 정적 검증. SEC-001~009 / RES-001 / IMG-001 / SA-001~002 / SVC-001~002 / PRB-001~002 + WARN. 3단계 exit code(F-42). `--json` 모드(F-47). 메시지 한국어 요약(NFR-17). `validation.skipped[]` 메타 출력.

**CLI 인터페이스** (외부):

```
validate_k8s.py [--json] [--skipped CHECK [CHECK ...]] PATH

  PATH: manifest YAML 파일 또는 디렉토리
  --json: JSON 출력 (summary.json 호환)
  --skipped: 스킵된 검증 식별자 (kubectl_dry_run / container_build) — summary.json validation.skipped에 전달

Exit codes:
  0 — all PASS
  1 — FAIL 존재
  2 — FAIL 없음 + WARN 존재 (soft-success)
```

**Python API**:

```python
class K8sValidator:
    def validate(self, manifests: list[Path | str]) -> ValidationReport:
        """manifests 각 YAML에 대해 모든 규칙 적용.
        ValidationReport(
            results: list[CheckResult],  # CheckResult(rule_id, level, container, message_ko, message_en, suggestion)
            counts: {pass: int, warn: int, fail: int},
            exit_code: int,
            skipped: list[str],  # CLI에서 전달된 값
        )"""

    def to_json(self, report: ValidationReport) -> str:
        """summary.json validation 객체와 호환 형식 출력."""
```

**Dependencies**:
- `pyyaml`
- 표준 라이브러리만 (외부 정책 엔진 의존성 없음)

**Data Owned**:
- 규칙 셋 (SEC-001~009, RES-001, IMG-001, SA-001~002, SVC-001~002, PRB-001~002, WARN: RES-W01, IMG-W01)
- 메시지 카탈로그 (한국어 + 영문 병기)

**Exceptions**:
- `MalformedManifestError` — YAML 파싱 실패 (별도 처리, validation.fail에 카운트)

---

### 10. KubectlDryRunner (Adapter)

**Responsibility**: `kubectl apply --dry-run=client` 실행. 미설치 시 degraded success(경고 + rationale 기록 + `summary.json.validation.skipped`에 `kubectl_dry_run` 추가). **경계 allowlist 준수** — `--dry-run=client` 외 인자 금지.

**Public interface**:

```python
class KubectlDryRunner:
    def is_available(self) -> bool:
        """which kubectl + 버전 확인 (>= 1.25 권장)."""

    def dry_run(self, manifest_dir: Path) -> DryRunResult:
        """kubectl apply --dry-run=client -f {manifest_dir} 실행.
        반드시 --dry-run=client 인자 포함 (NFR-SEC-05 allowlist).
        DryRunResult(
            success: bool,
            stdout: str | None,        # 미설치 시 None
            stderr: str | None,        # 미설치 시 None
            exit_code: int | None,     # 미설치 시 None
            skipped: bool,             # True면 미설치 → degraded success
            skip_reason_ko: str | None,  # F-56 한국어 사유 ("kubectl 미감지")
        )
        kubectl 미설치 시: skipped=True, success=True (degraded), stdout/stderr/exit_code = None,
        skip_reason_ko = '쿠버네티스 CLI(kubectl)가 설치되어 있지 않아 dry-run 검증을 건너뜀'"""

    # 내부
    def _build_command(self, manifest_dir: Path) -> list[str]:
        """['kubectl', 'apply', '--dry-run=client', '-f', str(manifest_dir)]
        다른 부동 인자(--server-side, --force) 금지 — 경계 위반."""
```

**Dependencies**:
- `subprocess` (표준)
- 시스템 PATH의 `kubectl`

**Data Owned**: 없음

**Exceptions**:
- `KubectlExecutionError` — kubectl 실행 자체 실패 (PATH는 있으나 실행 권한 등). degraded로 처리 안 함 — 명시 에러
- 미설치는 예외가 아닌 `is_available() = False` + `dry_run().skipped = True` 정상 흐름

---

### 11. AtomicWriter (Util)

**Responsibility**: 임시 디렉토리(`.tmp-{uuid}/`) 쓰기 → atomic rename. SIGINT/SIGTERM 핸들러로 임시 정리. 시작 시 7일 이상 고아 `.tmp-*` 자동 회수. `output.on_exists`(prompt/overwrite/suffix) 분기.

**Public interface**:

```python
class AtomicWriter:
    def __init__(self, output_dir: Path, on_exists: Literal['prompt', 'overwrite', 'suffix']):
        ...

    def __enter__(self) -> 'AtomicWriter':
        """signal handler 등록 (SIGINT, SIGTERM).
        7일 이상 .tmp-* 고아 디렉토리 자동 삭제 (시작 시).
        새 .tmp-{uuid}/ 디렉토리 생성."""

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """예외 없이 종료: commit() 호출됐는지 확인. 안 됐으면 cleanup.
        예외 발생: cleanup(.tmp-* 삭제) — output_dir 이전 상태 유지.
        signal handler 해제."""

    @property
    def staging_dir(self) -> Path:
        """현재 .tmp-{uuid}/ 경로. SkillPipeline의 모든 쓰기는 여기로."""

    def commit(self) -> Path:
        """모든 검증 통과 후 호출.
        on_exists에 따라 분기:
          prompt: 사용자 확인 후 output_dir 백업 → atomic rename
          overwrite: 조용히 atomic rename (기존 삭제)
          suffix: output_dir-{YYYY-MM-DDTHH-MM}/ 새로 만들고 rename
        반환: 최종 디렉토리 경로."""

    def cleanup(self) -> None:
        """staging_dir 삭제. 실패해도 raise 안 함 (best effort)."""

    # 내부
    def _signal_handler(self, signum, frame) -> None:
        """cleanup() 호출 → sys.exit(130)"""

    def _gc_orphans(self) -> None:
        """output_dir.parent / .tmp-* 중 7일 이상 디렉토리 삭제."""
```

**Dependencies**:
- `pathlib`, `shutil`, `signal`, `tempfile`, `uuid`, `datetime`
- 사용자 프롬프트는 SkillPipeline 콜백 (테스트성)

**Data Owned**:
- staging_dir 경로
- signal handler 등록 상태

**Exceptions**:
- `OutputExistsAbort` — prompt 모드에서 사용자가 거부 → SkillPipeline에서 UserAbort로 변환

---

### 12. OutputPackager (Service)

**Responsibility**: STEP 5 최종 패키징. `rationale.md`(결정 소스 매핑 + 스킵 검증 섹션) + `summary.json`(고정 스키마, UTC, `validation.skipped[]`) + bail-out 시 `troubleshoot.md`(상단 한국어 1-2줄 요약 의무).

**Public interface**:

```python
class OutputPackager:
    def write(
        self,
        staging_dir: Path,
        inputs: UserInputs,
        analysis: AnalysisResult,
        validation: ValidationReport,
        config_source_map: dict[str, str],
    ) -> PackagingResult:
        """staging_dir에 rationale.md + summary.json 생성.
        모든 입력은 atomic write 컨텍스트 안에서 호출됨."""

    def write_troubleshoot(
        self,
        staging_dir: Path,
        bailout: BailOutContext,
    ) -> None:
        """bail-out 시에만 호출.
        troubleshoot.md 상단:
          # 막힌 지점
          STEP {n} ({한국어 단계명})에서 {component_ko_name} 실패: {ko_summary}
          (영문) {en_detail}
        하단: 전체 시도 로그."""

    def write_summary_json(self, ...) -> None:
        """schema:
        {
          "version": "v1",
          "generated_at": "<UTC ISO8601>",
          "stack": "jvm",
          "app": {"name": ..., "ports": [int]},
          "images": [{"repository": ..., "tag": ...}],
          "namespace": ...,
          "validation": {
            "pass": int, "warn": int, "fail": int,
            "skipped": ["kubectl_dry_run", ...]
          },
          "files": ["Dockerfile", "deployment.yaml", ...]
        }"""

    def write_rationale_md(self, ...) -> None:
        """섹션 (F-82 + 확장):
        - 감지된 스택 (source map)
        - 진입점 / 포트 (추론 근거)
        - 상태성 (StatefulnessSignal.confidence + 근거)
        - 베이스 이미지 (config layer 출처)
        - 리소스 (defaults 출처)
        - namespace (NamespaceResolution.source)
        - probe (ProbeConfig 분기 근거)
        - 검증 결과 요약 (PASS/WARN/FAIL 카운트)
        - 스킵된 검증 (validation.skipped + 사유) ← 신규
        - 경고 목록"""
```

**Dependencies**:
- `json`, `datetime` (UTC ISO8601)
- AtomicWriter (호출 측에서 staging_dir 전달)

**Data Owned**:
- summary.json 스키마 정의 (frozen dict)

**Exceptions**:
- 없음 (입력 검증은 SkillPipeline)

---

## 보조 산출물

### A. 도움말 카탈로그 v0.1.0 초안 (10개 용어)

SKILL.md 본문에 정적 포함. v0.2+에서 외부 파일(`help/{lang}.yml`) 분리.

> **`step` 필드 (DETAIL 보강 — spec-reviewer Must-fix)**: 각 용어가 어느 단계에서 쓰이는지 라벨링. SkillPipeline은 step에 따라 호출 시점을 결정.
> - `step: 1` — STEP 1 입력 수집 (F-02 6개 항목)
> - `step: 2` — STEP 2 추론 실패 보충 질문 / 경고 안내 (F-03/F-38/F-39)
> - `step: config` — 설정 파일 옵션 설명 (F-61)

```yaml
# Help Catalog v0.1.0
# 키: term_id (snake_case)
# 필드: ko_short, ko_detail, original, example, step (1 | 2 | config)

# ─── STEP 1: 입력 수집 (F-02 매핑 6개) ───

app_name:
  step: 1
  ko_short: "앱 이름은 뭘로 할까요?"
  ko_detail: "앱 이름은 쿠버네티스에서 이 앱을 식별하는 라벨이에요. 보통 프로젝트 이름과 같게 짓고, 영문 소문자/숫자/하이픈만 사용합니다."
  original: "Deployment.metadata.name + Service.metadata.name + ServiceAccount.metadata.name"
  example: "my-api-service / order-backend"

port:
  step: 1
  ko_short: "앱이 어떤 포트를 쓰나요?"
  ko_detail: "앱이 요청을 받는 네트워크 포트예요. Spring Boot는 보통 8080입니다. application.yml에 server.port가 적혀 있으면 그 값을 쓰세요."
  original: "Container port + Service.spec.ports[].targetPort"
  example: "8080 (Spring Boot 기본) / 9000 (커스텀)"

exposure:
  step: 1
  ko_short: "어디서 접속할 건가요?"
  ko_detail: "앱을 어떤 범위에서 접속 가능하게 할지 결정해요. (a) 사내 네트워크만(다른 앱끼리만 호출) (b) 외부 인터넷(클라우드 비용 발생, 월 $20+)"
  original: "Service.spec.type — ClusterIP(사내) / NodePort(노드 포트) / LoadBalancer(외부)"
  example: "백엔드 API: ClusterIP / 모바일/웹 공개: LoadBalancer"

namespace:
  step: 1
  ko_short: "네임스페이스는 뭘로 할까요?"
  ko_detail: "네임스페이스(namespace)는 쿠버네티스에서 앱들을 분류하는 폴더 같은 개념이에요. 보통 프로젝트나 팀 이름을 씁니다. 'default'는 사고 방지를 위해 자동 배정되지 않아요."
  original: "Kubernetes Namespace — 리소스 격리 + RBAC 경계"
  example: "my-team / payment-svc / dev-jay"

output_dir:
  step: 1
  ko_short: "생성 파일을 어디에 둘까요?"
  ko_detail: "Dockerfile과 yaml 파일이 만들어질 폴더예요. 기본은 'k8s-output/'이고, 이미 있으면 덮어쓸지 다시 물어봅니다."
  original: "Output directory (config: output.dir)"
  example: "k8s-output (기본) / deploy/k8s"

resource_hint:
  step: 1
  ko_short: "메모리/CPU는 어느 정도 필요해요?"
  ko_detail: "앱이 사용할 자원을 추정해주세요. JVM은 기본 메모리 512Mi~1Gi를 추천합니다. 잘 모르겠으면 'medium'을 고르세요."
  original: "spec.containers[].resources.{requests,limits}.{cpu,memory}"
  example: "small (256Mi/0.5CPU) / medium (512Mi/1CPU) / large (1Gi/2CPU)"

# ─── STEP 2: 추론 실패 보충 / 경고 (F-03/F-38/F-39 매핑 3개) ───

actuator:
  step: 2
  ko_short: "actuator를 쓰고 있나요?"
  ko_detail: "actuator는 Spring Boot의 헬스체크/메트릭 기능이에요. build.gradle에 'spring-boot-starter-actuator'가 있으면 활성화된 거예요. 없으면 TCP로 헬스체크합니다."
  original: "Spring Boot Actuator — /actuator/health 엔드포인트"
  example: "Boot 2.x: /actuator/health 단일 / Boot 3.x: /liveness + /readiness 분리"

multi_module:
  step: 2
  ko_short: "여러 모듈 중 어느 걸 배포할까요?"
  ko_detail: "Gradle/Maven multi-module 프로젝트예요. 보통 API 서버는 '-api', '-web', '-server'로 끝나는 모듈이에요. 라이브러리(-core, -common)는 배포 대상이 아닙니다."
  original: "Gradle settings.gradle(.kts) / Maven <modules>"
  example: "order-api (○) / order-core (×, 라이브러리)"

stateful:
  step: 2
  ko_short: "상태성 앱이라는 게 뭐예요? (경고 발생 시)"
  ko_detail: "DB 연결이나 파일 저장이 필요한 앱이에요. v0.1.0은 Deployment만 만들기 때문에, Pod 재시작 시 데이터가 사라질 수 있어요. v0.2부터 StatefulSet/PVC를 지원합니다."
  original: "StatefulSet vs Deployment — Pod 재시작 시 데이터 보존"
  example: "stateless: 일반 API 서버 / stateful: DB, 메시지 큐, 파일 업로드 앱"

# ─── 설정 파일 옵션 (F-61 매핑 1개) ───

build_engine:
  step: config
  ko_short: "이미지를 직접 빌드할까요?"
  ko_detail: "기본은 Dockerfile만 만들고 빌드는 안 해요. 빌드도 하고 싶으면 'auto'를 고르세요 (docker/podman/nerdctl 자동 감지). CI에서는 보통 별도 단계에서 빌드합니다."
  original: "build.engine config — auto / docker / podman / nerdctl / skip(default)"
  example: "로컬 테스트: auto / CI 파이프라인: skip"
```

### B. `_shared/retry.py` 시그니처

> **보강 사항 (Codex High 반영)**:
> - `fix_attempt`를 `bool` 대신 구조체(`FixOutcome`) 반환으로 변경 — `summary_ko` 전달 경로 확보
> - `success_predicate`를 필수 인자화 — 누락 시 실패를 성공으로 오인하는 위험 차단
> - 시퀀스 다이어그램은 lambda 래퍼 형태(`lambda: K8sValidator.validate(manifests)`)로 인자 캡처 명시

```python
# _shared/retry.py
"""3회 자동 수정 루프 공통 유틸 (F-50, F-51, F-54).
SkillPipeline에서 K8sValidator / KubectlDryRunner / 빌드 인라인 호출에 사용.
operation은 항상 lambda로 감싸 인자를 캡처한다."""

from typing import Callable, TypeVar, Generic
from dataclasses import dataclass

T = TypeVar('T')


@dataclass(frozen=True)
class FixOutcome:
    """fix_attempt() 반환 구조체.

    applied: 이번 attempt 이전에 수정이 실제로 적용됐는가
             (False면 다음 attempt 진행 안 함 — 즉시 bailout)
    summary_ko: 수정 내용 한국어 요약. troubleshoot.md attempts 로그에 사용.
                applied=False여도 사유를 한국어로 기록 (예: '수정안 생성 실패')
    """
    applied: bool
    summary_ko: str | None


@dataclass
class RetryAttempt(Generic[T]):
    attempt_number: int           # 1-based
    result: T | None              # operation 반환값 (예외 시 None)
    error: Exception | None       # operation 예외 (성공 시 None)
    success: bool                 # success_predicate 결과
    fix_outcome: FixOutcome | None  # 이 attempt 직후 fix_attempt 결과 (마지막 attempt면 None)


@dataclass
class RetryResult(Generic[T]):
    success: bool                 # 마지막 attempt가 success_predicate True
    final_result: T | None        # 마지막 성공 결과 (실패 시 마지막 attempt의 result)
    attempts: list[RetryAttempt[T]]  # 전체 시도 로그 (troubleshoot.md 입력)
    bailout: bool                 # True면 max_attempts 초과 또는 fix_outcome.applied=False


def retry_with_fix(
    operation: Callable[[], T],
    fix_attempt: Callable[[T | Exception], FixOutcome],
    success_predicate: Callable[[T], bool],   # 필수 인자 (기본값 제거)
    max_attempts: int = 3,
    step_name_ko: str = "검증",
    component_ko: str = "",
) -> RetryResult[T]:
    """
    operation: 검증/실행 lambda. 반환값 또는 예외.
               예: lambda: K8sValidator.validate(manifest_paths)
    fix_attempt: operation 결과(또는 예외)를 받아 수정 시도. FixOutcome 반환.
                 applied=False면 다음 attempt 안 함, 즉시 bailout.
    success_predicate: operation 결과가 성공인지 판정. 필수.
                       예: lambda r: r.exit_code != 1
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
    ...
```

**호출 예 (SkillPipeline.step4)**:

```python
# K8sValidator 재시도
k8s_result = retry_with_fix(
    operation=lambda: validator.validate(artifacts.manifest_paths),
    fix_attempt=lambda r: _fix_k8s_failures(r, staging_dir),  # FixOutcome 반환
    success_predicate=lambda r: r.exit_code != 1,  # PASS(0) 또는 soft-success(WARN=2), FAIL=1만 재시도
    step_name_ko="STEP 4 정적 검증",
    component_ko="K8s 검증기",
)

# KubectlDryRunner 재시도
dry_run_result = retry_with_fix(
    operation=lambda: runner.dry_run(staging_dir),
    fix_attempt=lambda r: _fix_dry_run_failures(r, staging_dir),
    success_predicate=lambda r: r.success,  # skipped=True도 success=True로 통과
    step_name_ko="STEP 4 dry-run 검증",
    component_ko="kubectl 어댑터",
)

# F-56 pass-through: skip 사유를 ValidationOutcome에 누적
validation_outcome.skipped = []
if dry_run_result.final_result.skipped:
    validation_outcome.skipped.append("kubectl_dry_run")
    validation_outcome.skip_reasons["kubectl_dry_run"] = dry_run_result.final_result.skip_reason_ko
```

### B-1. F-56 degraded success pass-through 경로 (신규)

KubectlDryRunner 미설치 / ContainerBuildRunner 엔진 미감지 시 skipped 사유 전파:

```
KubectlDryRunner.dry_run() → DryRunResult(skipped=True, skip_reason_ko='kubectl 미감지')
   ↓
SkillPipeline.step4_validate_gate() → ValidationOutcome.skipped = ['kubectl_dry_run']
                                       ValidationOutcome.skip_reasons = {
                                         'kubectl_dry_run': '쿠버네티스 CLI(kubectl)가...'
                                       }
   ↓
SkillPipeline.step5_package() → OutputPackager.write(validation=ValidationOutcome)
   ↓
OutputPackager.write_summary_json() → summary.json.validation.skipped = ['kubectl_dry_run']
OutputPackager.write_rationale_md() → '## 스킵된 검증' 섹션:
                                        - kubectl_dry_run: 쿠버네티스 CLI(kubectl)가...
```

`ValidationOutcome` 타입 (DETAIL 보강 — types 카탈로그 참조):

```python
@dataclass
class ValidationOutcome:
    k8s_report: ValidationReport   # K8sValidator 결과
    dry_run: DryRunResult | None   # KubectlDryRunner 결과 (None이면 skipped)
    build: BuildResult | None       # 빌드 결과 (None이면 skipped)
    skipped: list[str]              # ['kubectl_dry_run', 'container_build']
    skip_reasons: dict[str, str]    # 식별자 → 한국어 사유
    bailed: bool                    # True면 3회 재시도 실패
```

### C. 경계 allowlist 테스트 픽스처 (NFR-SEC-05)

> **보안 강화 (Codex Critical 반영)**: shell=True 차단, argv 리스트 강제, `kubectl apply` 정확한 토큰 위치 매칭, 세미콜론/파이프 체인 차단

```python
# tests/conftest.py 또는 tests/fixtures/cli_allowlist.py
"""NFR-SEC-05: 금지 CLI 호출 감지 픽스처.
모든 통합 테스트에 자동 적용 (autouse=True)."""

import subprocess
import pytest

# 명시 허용된 CLI 호출 패턴 (정확한 토큰 + 필수 후행 인자)
# (command_name, required_args_in_order) — required_args_in_order는 cmd[1:]의 prefix
ALLOWLIST: list[tuple[str, list[str]]] = [
    ("kubectl",  ["apply", "--dry-run=client"]),  # 반드시 prefix 위치
    ("kubectl",  ["version"]),
    ("docker",   ["build"]),
    ("docker",   ["images"]),
    ("docker",   ["inspect"]),
    ("docker",   ["version"]),
    ("podman",   ["build"]),
    ("podman",   ["images"]),
    ("podman",   ["version"]),
    ("nerdctl",  ["build"]),
    ("nerdctl",  ["images"]),
    ("nerdctl",  ["version"]),
    ("which",    []),
    ("gradle",   ["bootJar"]),
    ("mvn",      ["package"]),
]

# 금지 패턴 (cmd_name + cmd[1] 토큰)
DENYLIST_SUBCOMMANDS: dict[str, set[str]] = {
    "docker":  {"push"},
    "podman":  {"push"},
    "nerdctl": {"push"},
    "kubectl": {"apply", "create", "delete", "replace", "rollout", "scale", "edit", "patch"},
    # kubectl apply는 ALLOWLIST에서 --dry-run=client 명시 시에만 통과
}

# 명령 체인/리다이렉션/인젝션 토큰 — 발견 시 무조건 실패
SHELL_INJECTION_TOKENS = {";", "&&", "||", "|", "&", "`", "$(", ">", ">>", "<", "\n"}


class CliBoundaryViolation(AssertionError):
    """NFR-SEC-05 위반."""


def _normalize_cmd_or_fail(cmd, kwargs: dict) -> list[str]:
    """argv 리스트만 허용. 문자열 cmd, shell=True, 인젝션 토큰은 즉시 위반.

    반환: 정규화된 argv 리스트
    Raises: CliBoundaryViolation
    """
    # shell=True 차단 (argv 검증 우회 가능)
    if kwargs.get("shell", False):
        raise CliBoundaryViolation(
            f"NFR-SEC-05: shell=True 금지 — argv 리스트만 허용. cmd={cmd!r}"
        )
    # 문자열 cmd 차단 (split 정확성 보장 어려움)
    if isinstance(cmd, str):
        raise CliBoundaryViolation(
            f"NFR-SEC-05: 문자열 명령 금지 — argv 리스트로 전달하세요. cmd={cmd!r}"
        )
    if not isinstance(cmd, (list, tuple)):
        raise CliBoundaryViolation(
            f"NFR-SEC-05: 알 수 없는 cmd 타입 {type(cmd).__name__}"
        )
    cmd_list = [str(arg) for arg in cmd]
    # 인젝션 토큰 차단 (argv 안에 들어있더라도)
    for arg in cmd_list:
        for tok in SHELL_INJECTION_TOKENS:
            if tok in arg:
                raise CliBoundaryViolation(
                    f"NFR-SEC-05: 위험 토큰 '{tok}' 발견 — {cmd_list}"
                )
    return cmd_list


def _is_allowed(command: list[str]) -> bool:
    """정확한 토큰 위치 기반 검증.

    규칙:
      1. command[0] (basename)이 DENYLIST_SUBCOMMANDS에 있고 command[1]이 금지 서브커맨드면:
         ALLOWLIST에 prefix 매칭이 있으면 통과, 없으면 거부
      2. ALLOWLIST에 (cmd_name, required_args)가 있고 command[1:1+len(required_args)] == required_args면 통과
      3. 그 외 통과 (which 같은 무인자 도구, ALLOWLIST에 빈 args)
    """
    if not command:
        return True
    cmd_name = command[0].split("/")[-1]

    # ALLOWLIST prefix 매칭 (먼저 검사 — kubectl apply --dry-run=client 통과)
    matched_allow = False
    for allow_cmd, allow_args in ALLOWLIST:
        if cmd_name != allow_cmd:
            continue
        if not allow_args:
            matched_allow = True
            break
        # cmd[1:] 의 prefix와 정확히 일치
        if command[1 : 1 + len(allow_args)] == allow_args:
            matched_allow = True
            break

    # DENYLIST 검사 (ALLOWLIST 매칭 안 된 위험 서브커맨드만 차단)
    if cmd_name in DENYLIST_SUBCOMMANDS and len(command) >= 2:
        if command[1] in DENYLIST_SUBCOMMANDS[cmd_name]:
            return matched_allow  # ALLOWLIST 통과한 경우만 허용

    # ALLOWLIST에 등재된 도구 + 무위험 서브커맨드면 통과
    if matched_allow:
        return True

    # ALLOWLIST에 명시 안 된 도구 호출 — 보수적으로 통과 (테스트 외 도구도 사용)
    # 단, DENYLIST 도구는 명시 허용된 경우만 통과 (위 분기에서 처리됨)
    if cmd_name in DENYLIST_SUBCOMMANDS:
        return False  # DENYLIST 도구는 명시 ALLOWLIST 매칭 필요
    return True


@pytest.fixture(autouse=True)
def cli_allowlist_guard(monkeypatch):
    """모든 subprocess 호출을 검사. 금지 패턴 발견 시 테스트 실패.

    검증 순서:
      1. _normalize_cmd_or_fail() — shell=True/문자열 cmd/인젝션 토큰 차단
      2. _is_allowed() — ALLOWLIST prefix + DENYLIST 서브커맨드 검사
    """
    original_run = subprocess.run
    original_popen = subprocess.Popen

    def guarded_run(cmd, *args, **kwargs):
        cmd_list = _normalize_cmd_or_fail(cmd, kwargs)
        if not _is_allowed(cmd_list):
            pytest.fail(
                f"NFR-SEC-05 위반: 금지된 CLI 호출 — {cmd_list}\n"
                f"허용 목록: ALLOWLIST 참조"
            )
        return original_run(cmd, *args, **kwargs)

    def guarded_popen(cmd, *args, **kwargs):
        cmd_list = _normalize_cmd_or_fail(cmd, kwargs)
        if not _is_allowed(cmd_list):
            pytest.fail(f"NFR-SEC-05 위반: 금지된 CLI 호출 — {cmd_list}")
        return original_popen(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)
    monkeypatch.setattr(subprocess, "Popen", guarded_popen)
```

**픽스처 자체 검증 테스트 필수** (NFR-SEC-05 회귀 방지):
- `kubectl apply --dry-run=client -f manifest/` — 통과
- `kubectl apply -f manifest/` (dry-run 없음) — 실패
- `kubectl apply --dry-run=client; docker push x` (체인) — 실패 (인젝션 토큰)
- `["sh", "-c", "kubectl apply --dry-run=client"]` (shell wrapper) — 실패 (sh는 ALLOWLIST 외 + shell 호출)
- `kubectl apply` cmd 문자열 — 실패 (문자열 차단)
- `subprocess.run("docker push x", shell=True)` — 실패 (shell=True 차단)

### D. `_shared/types.py` 타입 카탈로그 (DETAIL 보강)

> spec-reviewer Should-fix #2: 12개 컴포넌트에 등장하는 18+ dataclass/Protocol 단일 정의 위치. units-generation 진입 시 중복 정의 방지.

```python
# _shared/types.py
"""DETAIL 단계의 모든 컴포넌트가 공유하는 데이터 모델.
모두 frozen dataclass 또는 Protocol. 변경은 INCEPTION 후속 변경관리 절차로."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, ClassVar, Callable

# ─── 설정 / 입력 ───

@dataclass(frozen=True)
class ResolvedConfig:
    """ConfigLoader.load() 결과."""
    raw: dict                        # 병합된 dict
    source_map: dict[str, str]       # 키 경로 → 출처 레이어
    warnings: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class NamespaceResolution:
    value: str
    source: Literal['project_config', 'org_config', 'user_input', 'project_dir', 'default']
    requires_confirmation: bool      # 'default' 명시 선택 시 True

@dataclass(frozen=True)
class StackDecision:
    forced_stack: str | None         # 'jvm' / 'go' / None (auto)
    source: str                      # 'project_config' / 'org_config' / 'auto'

@dataclass(frozen=True)
class UserInputs:
    app_name: str
    port: int
    exposure: Literal['ClusterIP', 'NodePort', 'LoadBalancer']
    namespace: str
    output_dir: Path
    resource_hint: Literal['small', 'medium', 'large']

# ─── 분석 ───

@dataclass(frozen=True)
class StackDetectResult:
    port: int | None
    entrypoint: str
    framework: str                   # 'spring-boot' / 'ktor' / 'micronaut' / 'jvm-generic'
    version: str | None              # Spring Boot 등 버전

@dataclass(frozen=True)
class BuildPlan:
    builder_image: str
    runner_image: str
    build_cmd: str
    artifact_path: str
    # v0.2+ 일반화 예정: stages: list[Stage]

@dataclass(frozen=True)
class ProbeSpec:
    kind: Literal['http', 'tcp']
    path: str | None                 # http일 때만
    port: int

@dataclass(frozen=True)
class ProbeConfig:
    liveness: ProbeSpec
    readiness: ProbeSpec

@dataclass(frozen=True)
class ResourceDefaults:
    cpu_request: str
    memory_request: str
    cpu_limit: str
    memory_limit: str
    writable_paths: list[str]        # ['/tmp', '/var/log']

@dataclass(frozen=True)
class ModuleInfo:
    name: str
    path: Path
    is_likely_app: bool              # '-api', '-web', '-server' 패턴 매칭

@dataclass(frozen=True)
class StatefulnessSignal:
    is_stateful: bool
    confidence: Literal['high', 'medium', 'low']
    reasons: list[str]               # 한국어 사유

@dataclass(frozen=True)
class AnalysisResult:
    stack: str                       # 'jvm'
    detect_result: StackDetectResult
    build_plan: BuildPlan
    probe_config: ProbeConfig
    defaults: ResourceDefaults
    artifact_paths: list[Path]
    selected_module: ModuleInfo | None
    statefulness: StatefulnessSignal
    gaps: list[str]                  # 추론 실패 항목

# ─── 도움말 ───

@dataclass(frozen=True)
class HelpEntry:
    term_id: str
    ko_short: str
    ko_detail: str
    original: str
    example: str
    step: Literal[1, 2, 'config']

# ─── 생성 ───

@dataclass(frozen=True)
class GeneratedArtifacts:
    dockerfile_path: Path
    manifest_paths: list[Path]       # deployment/service/serviceaccount

# ─── 검증 ───

@dataclass(frozen=True)
class CheckResult:
    rule_id: str                     # 'SEC-001' 등
    level: Literal['PASS', 'WARN', 'FAIL']
    container: str
    message_ko: str
    message_en: str
    suggestion: str

@dataclass(frozen=True)
class ValidationReport:
    """K8sValidator.validate() 결과."""
    results: list[CheckResult]
    counts: dict[Literal['pass', 'warn', 'fail'], int]
    exit_code: int                   # 0 / 1 / 2
    skipped: list[str]               # CLI --skipped 인자 통과값

@dataclass(frozen=True)
class DryRunResult:
    """KubectlDryRunner.dry_run() 결과. F-56 degraded 시 None 필드."""
    success: bool
    stdout: str | None
    stderr: str | None
    exit_code: int | None
    skipped: bool                    # True면 미설치
    skip_reason_ko: str | None

@dataclass(frozen=True)
class BuildResult:
    success: bool
    image_ref: str | None            # repository:tag (성공 시)
    engine: Literal['docker', 'podman', 'nerdctl'] | None
    skipped: bool
    skip_reason_ko: str | None

@dataclass
class ValidationOutcome:
    """SkillPipeline.step4_validate_gate() 결과 — STEP 5로 pass-through."""
    k8s_report: ValidationReport
    dry_run: DryRunResult | None
    build: BuildResult | None
    skipped: list[str]               # ['kubectl_dry_run', 'container_build']
    skip_reasons: dict[str, str]     # 식별자 → 한국어 사유
    bailed: bool

# ─── 패키징 ───

@dataclass(frozen=True)
class PackagingResult:
    final_dir: Path
    files_written: list[str]
    troubleshoot_written: bool

@dataclass(frozen=True)
class BailOutContext:
    """OutputPackager.write_troubleshoot() 입력."""
    step_number: int                 # 4 (검증 게이트에서 bail)
    step_name_ko: str                # 'STEP 4 정적 검증'
    component_ko: str                # 'K8s 검증기'
    ko_summary: str                  # 한국어 1-2줄
    en_detail: str
    attempts_log: list  # _shared/retry.RetryAttempt 리스트

# ─── 프롬프트 콜백 (UI 추상화) ───

@dataclass(frozen=True)
class PromptRequest:
    kind: Literal['question', 'confirm', 'select']
    ko_text: str                     # 한국어 질문
    options: list[str] | None        # select일 때
    help_term_id: str | None         # "? 도움말" 옵션 활성화 시 HelpCatalog 키

PromptCallback = Callable[[PromptRequest], str]
"""SkillPipeline에서 ProjectAnalyzer/AtomicWriter에 주입.
None이면 자동 모드 (테스트성)."""
```

### E. SkillPipeline 서브유닛 매핑 (DETAIL 보강)

> Codex Should-fix #6: SkillPipeline은 AutoFixLoop/ContainerBuildRunner/도움말·메시지 정책 흡수로 비대 — units-generation 진입 시 단일 unit으로 잡으면 과대화. 다음 3개 서브유닛으로 분해.

| 서브유닛 | 책임 범위 | 예상 파일 위치 | 단위 테스트 경계 |
|---------|---------|--------------|----------------|
| `pipeline/orchestrator.py` | 5-STEP 진행 의사결정 + STEP 1 입력 수집 + HelpCatalog 호출 + MessagePolicy 적용 | `${CLAUDE_PLUGIN_ROOT}/scripts/pipeline/orchestrator.py` | STEP 진행 순서 + 한국어 질문 + 도움말 콜백 |
| `pipeline/retry_loop.py` | STEP 4 재시도 오케스트레이션 (`_fix_k8s_failures`, `_fix_dry_run_failures` 헬퍼 + retry_with_fix 호출) | `${CLAUDE_PLUGIN_ROOT}/scripts/pipeline/retry_loop.py` | 3회 재시도 + bail-out + ValidationOutcome.skipped pass-through |
| `pipeline/build_runner.py` | opt-in 컨테이너 빌드 인라인 (엔진 감지 + build CLI 호출 + 타임아웃 + degraded) | `${CLAUDE_PLUGIN_ROOT}/scripts/pipeline/build_runner.py` | docker/podman/nerdctl 분기 + skipped 기록 |

**SKILL.md 본문**은 위 3개 서브유닛을 STEP별로 호출하는 Claude 프롬프트 시퀀스로 표현. units-generation 진입 시:
- **Unit candidate 1**: SkillPipeline (= SKILL.md 본문 + 위 3개 서브유닛 = 1 logical unit, 4 files)
- 또는 분해: SkillPipeline 4개 unit (orchestrator / retry_loop / build_runner / SKILL.md). units-generation 스테이지에서 결정.

**`_shared/` 모듈 unit 경계 결정**: `retry.py` + `types.py` + `errors.py` + `defaults.py`를 단일 `_shared` unit으로 묶어 4개 파일 1 unit. 각 컴포넌트 unit이 의존성으로 참조.

### F. AtomicWriter prompt 콜백 (DETAIL 보강)

> spec-reviewer Should-fix #5: prompt 모드 사용자 확인 콜백 주입 방식이 ProjectAnalyzer 콜백 패턴과 동일하게 명시.

```python
class AtomicWriter:
    def __init__(
        self,
        output_dir: Path,
        on_exists: Literal['prompt', 'overwrite', 'suffix'],
        prompt_callback: PromptCallback | None = None,
    ):
        """on_exists='prompt'이고 output_dir이 이미 존재하면 prompt_callback 호출.
        prompt_callback=None이면 OutputExistsAbort raise (자동 모드/CI에서 안전 기본)."""
```

호출 시:
```python
PromptRequest(
    kind='confirm',
    ko_text=f"'{output_dir}'에 이미 파일이 있어요. 덮어쓸까요?",
    options=['덮어쓰기', '취소', 'suffix로 새 디렉토리 만들기'],
    help_term_id='output_dir',
)
```

### G. 컴포넌트별 테스트 경계 매트릭스

| 컴포넌트 | 단위 테스트 경계 | 통합 테스트 경계 | 모킹 포인트 |
|---------|--------------|---------------|-----------|
| SkillPipeline | 5-STEP 진행 의사결정 (mock된 컴포넌트 호출 순서) | 전체 e2e (가짜 Spring Boot 프로젝트 fixture) | 모든 의존 컴포넌트 |
| ConfigLoader | YAML 파싱 + 우선순위 병합 + namespace 4단계 | ~/.claude 와 project dir 양쪽 fixture | 파일 시스템(tmp_path) |
| ProjectAnalyzer | gap 식별 로직 + multi-module 선택 + Stateful 신뢰도 | 실제 Gradle/Maven 샘플 프로젝트 | StackModule (test double) |
| StackModule (Interface) | Protocol 준수 검증 | (없음 — 인터페이스) | — |
| JvmStackModule | Boot 버전/포트/actuator 추론 (각 시나리오 5+) | 실제 build.gradle.kts/pom.xml 샘플 | 파일 시스템 |
| TemplateRenderer | 결정론적 출력 (cksum 비교) + 빈 라인 정규화 | (DockerfileGenerator/ManifestGenerator 통해 간접) | Jinja2 (모킹 안 함) |
| DockerfileGenerator | latest 태그 검증 + 보안 주석 포함 검증 | TemplateRenderer 실제 호출 | TemplateRenderer (실제) |
| ManifestGenerator | securityContext 모든 필드 + emptyDir 자동 마운트 | TemplateRenderer + 결과 YAML 파싱 검증 | TemplateRenderer (실제) |
| K8sValidator | 각 SEC-/RES-/SVC-/SA-/IMG-/PRB- 규칙별 PASS/WARN/FAIL 케이스 | 실제 manifest 파일들로 e2e | 없음 (순수 함수 위주) |
| KubectlDryRunner | _build_command allowlist 준수 + degraded 처리 | 실제 kubectl(있을 때만) + monkeypatch(없을 때) | subprocess (cli_allowlist_guard) |
| AtomicWriter | rename + cleanup + on_exists 분기 + signal handler | 실제 파일시스템 + 7일 고아 GC | os.signal (테스트 시 SIGTERM 발생) |
| OutputPackager | summary.json 스키마 (jsonschema) + UTC + skipped + troubleshoot 한국어 요약 | 전체 STEP 5 e2e | 없음 |

**커버리지 목표 매핑** (NFR-TEST-01/02):
- `validate_k8s.py` (= K8sValidator): ≥ 70% (MVP 기준)
- `scripts/stacks/jvm.py` (= JvmStackModule): ≥ 60% (MVP 기준)
- 그 외 컴포넌트: 명시 목표 없음 (CI에서 전체 ≥ 60% 유지 권장)

---

## Change Log

- 2026-04-17T00:30:00+09:00 — 1차 LIST. 15개 컴포넌트.
- 2026-04-17T00:50:00+09:00 — UX 결정: F-02a/F-02b 추가, 프리셋(P1) v0.2+ 연기. 컴포넌트 변화 없음.
- 2026-04-17T01:30:00+09:00 — **2차 LIST (3-페르소나 + Codex 리뷰 반영)**:
  - 컴포넌트 15 → 12 (NamespaceResolver→ConfigLoader, AutoFixLoop→SkillPipeline, ContainerBuildRunner→SkillPipeline)
  - 추적 매트릭스 추가 (F 71 / US 22 / NFR 17 100% 커버리지)
  - 설계 원칙 추가 (메시지 정책 전 STEP 확대, degraded skipped 기계 판독성)
  - NFR Design Patterns 섹션 추가 (보안/결정론성/Atomic write/경계/국제화)
  - v0.2+ 백로그 확장 (NetworkPolicy/PDB/Stateful 신뢰도/LB 비용/BuildPlan 일반화/도움말 외부화/validate_k8s WARN/외부 CLI Adapter 베이스)
  - 도움말 카탈로그 스키마 명시 (DETAIL 모드 사전 작업)
- 2026-04-17T02:30:00+09:00 — **DETAIL 모드 완료 (Comprehensive)**:
  - 12개 컴포넌트 상세 설계 (Public interface + Dependencies + Data Owned + Exceptions + Interactions)
  - 5-STEP 시퀀스 다이어그램 (ASCII) — 입력/분석/생성/검증/패키징
  - 보조 산출물 4종: 도움말 카탈로그 v0.1.0 초안 10개 용어, `_shared/retry.py` 시그니처, NFR-SEC-05 allowlist 테스트 픽스처, 컴포넌트별 테스트 경계 매트릭스
- 2026-04-17T03:30:00+09:00 — **DETAIL 외부 검토 반영 (spec-reviewer + Codex 8건)**:
  - **[보안]** NFR-SEC-05 픽스처 강화 — shell=True 차단, argv 리스트 강제, 인젝션 토큰(;,&&,\|,`,$( 등) 차단, 정확한 토큰 위치 매칭. 픽스처 자체 검증 테스트 의무화
  - **[보안]** nfr-requirements.md에 NFR-SEC-05 항목 추가 (NFR 17개로 정렬)
  - **[정합]** SkillPipeline.step4 시그니처 통일 — `KubectlDryRunner.dry_run(staging_dir)`, `K8sValidator.validate(manifest_paths)`, lambda 래퍼로 인자 캡처 명시
  - **[정합]** ProjectAnalyzer.__init__에 `config_loader, prompt_callback` 의존성 주입 명시 (DI 명확화)
  - **[정합]** HelpCatalog 컴포넌트 인터페이스 노출 (`lookup`, `for_step`)
  - **[정합]** 시퀀스 다이어그램 메서드명 정합: `_detect_stateful` → `_detect_statefulness`, `render_dockerfile` 직접 호출 → `DockerfileGenerator.generate()` 경유
  - **[정합]** F-91 build_plan(detect_result) 시그니처 정합 (requirements.md 다음 동기화 시 업데이트 명시)
  - **[정합]** retry.py `fix_attempt` → `FixOutcome(applied, summary_ko)` 구조체 반환, `success_predicate` 필수 인자화
  - **[정합]** F-56 degraded pass-through 경로 신설 — DryRunResult.skip_reason_ko → ValidationOutcome.skipped/skip_reasons → summary.json + rationale.md
  - **[메타]** 도움말 카탈로그 10개에 `step: 1|2|config` 라벨 추가 (STEP 1: 6개, STEP 2: 3개, config: 1개)
  - **[메타]** F-* 카운트 자동 집계 정정 — 73(잘못) → **71** (F-09 reserved + F-46a). NFR 17개(NFR-09 제거 + NFR-SEC-05 추가)
  - **[메타]** `_shared/types.py` 카탈로그 섹션 신설 — 18+ dataclass/Protocol 단일 정의 (ResolvedConfig, AnalysisResult, ValidationOutcome, DryRunResult, BuildResult, BailOutContext, PromptRequest, HelpEntry 등)
  - **[메타]** SkillPipeline 서브유닛 매핑 — orchestrator/retry_loop/build_runner 3개 분해. `_shared/` 단일 unit 경계 명시
  - **[메타]** AtomicWriter.commit() prompt_callback 주입 방식 명시 (ProjectAnalyzer 패턴 일치)
  - **[메타]** F-09 reserved 명시 (requirements.md ID 인벤토리)
- 2026-04-19 — **F-42 정합성 교정 (Unit 13 구현 리뷰 반영)**:
  - §1 / §B의 `success_predicate=lambda r: r.exit_code <= 2` → `r.exit_code != 1`로 정정.
  - F-42 exit code 정의(0=PASS, 1=FAIL, 2=WARN)상 `<= 2`는 항상 True로 retry 루프 무력화.
  - `exit_code != 1`이 F-42 soft-success(WARN) 계약과 정합.
