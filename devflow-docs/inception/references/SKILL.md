# K8s 배포 준비 Skill

## 언제 이 Skill을 사용하는가
사용자가 개발한 애플리케이션을 컨테이너 이미지로 빌드하고,
K8s 환경에 배포하기 위한 Dockerfile 및 manifest 파일 생성을 요청할 때.

키워드 예시: "배포 준비", "Dockerfile 만들어줘", "k8s manifest", "컨테이너화"

---

## 작업 디렉토리 규칙
- 생성 파일 임시 저장: /tmp/k8s-output/
- 검증 완료 후 사용자 검토용: 프로젝트 디렉토리 내 output_candidate/ 폴더
- 배포 성공 후 최종 출력: 프로젝트 디렉토리 내 output/ 폴더
- 검증 스크립트: ~/skills/k8s-deploy/validate_k8s.py

---

## 수행 단계 (이 순서를 반드시 지킬 것)

### STEP 1. 코드베이스 분석
다음 항목을 파악한다:
- 언어 및 런타임 (Python/Node/Go/Java 등)
- 의존성 파일 (requirements.txt / package.json / go.mod 등)
- 실행 진입점 (main.py / index.js / main.go 등)
- 리스닝 포트 (코드 내 PORT 환경변수, listen() 호출 등에서 추론)
- 스테이트 여부 (DB 연결, 파일 쓰기 등 → stateful 판단)

베이스 이미지 선택 기준:
  - Python  → python:3.11-slim
  - Node.js → node:20-alpine
  - Go      → golang:1.22-alpine (빌드) + scratch (런타임)
  - Java    → eclipse-temurin:17-jre-alpine

### STEP 2. Dockerfile 생성
아래 규칙을 반드시 준수한다:

#### [필수] 보안 규칙
- 비root 유저를 생성하고 해당 유저로 실행
  RUN addgroup -S appgroup && adduser -S appuser -G appgroup
  USER appuser  ← 반드시 CMD 바로 앞에 위치
- latest 태그 절대 사용 금지

#### [필수] 주석 규칙
모든 Dockerfile 지시어에 한국어 주석을 달 것.
"무엇을 하는가"가 아니라 "왜 이렇게 하는가"를 설명할 것.

### STEP 3. K8s Manifest 생성
생성할 리소스: Deployment + Service

#### [필수] securityContext (Pod 레벨)
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000

#### [필수] securityContext (Container 레벨)
securityContext:
  allowPrivilegeEscalation: false
  privileged: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: [ALL]

#### [필수] 리소스 스펙
resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "500m"
    memory: "256Mi"

추론 기준:
- 단순 API 서버   → cpu: 100m/500m,  memory: 128Mi/256Mi
- ML 추론 서버    → cpu: 500m/2000m, memory: 512Mi/2Gi
- 배치 처리 워커  → cpu: 200m/1000m, memory: 256Mi/1Gi

#### [필수] 주석 규칙
모든 manifest 필드에 한국어 주석 필수.
보안 관련 필드는 "이 설정이 없으면 어떤 위험이 있는지"를 주석으로 설명.

### STEP 4. Docker 이미지 빌드
Dockerfile이 생성된 후 실제 이미지 빌드를 수행한다:

docker build -t <앱이름>:<버전태그> -f /tmp/k8s-output/Dockerfile <프로젝트디렉토리>

- 빌드 실패 시 에러를 분석하고 Dockerfile 수정안을 작성한 뒤, 변경 사항을 사용자에게 보여주고 재빌드 승인을 요청한다 (AskUserQuestion 사용). 승인 후 재빌드 수행
- 빌드 성공 후 사용자에게 **컨테이너 레지스트리 주소**를 입력받는다 (AskUserQuestion 사용)
  예: "이미지를 push할 컨테이너 레지스트리 주소를 입력해주세요 (예: myregistry.io/my-team)"
- 입력받은 레지스트리 주소로 이미지 태깅 및 push:
  docker tag <앱이름>:<버전태그> <레지스트리주소>/<앱이름>:<버전태그>
  docker push <레지스트리주소>/<앱이름>:<버전태그>
- push 성공 후, K8s manifest의 image 필드를 push된 전체 이미지 경로로 자동 업데이트

### STEP 5. 검증 스크립트 실행
manifest 생성 후 반드시 아래 명령 실행:

python3 ~/skills/k8s-deploy/validate_k8s.py /tmp/k8s-output/deployment.yaml

결과가 FAIL이면 실패 항목을 수정 후 재실행. 모든 PASS 확인 후 다음 단계.

### STEP 6. Dry-run 배포
kubectl apply -f /tmp/k8s-output/ --dry-run=server --namespace=default 2>&1

실패 시 에러 메시지를 분석하고 manifest 수정 후 재시도.

### STEP 6.5. 검토용 파일 이동 및 사용자 확인
dry-run을 포함한 모든 검증이 통과된 후:
- /tmp/k8s-output/ 의 파일들을 프로젝트 디렉토리의 output_candidate/ 폴더로 복사
- 사용자에게 output_candidate/ 폴더의 파일을 검토하도록 안내 (AskUserQuestion 사용)
  예: "모든 검증이 통과되어 output_candidate/ 폴더에 파일을 준비했습니다. 파일을 검토한 후 실제 배포를 진행할까요?"
- 사용자가 수정을 요청하면 output_candidate/ 내 파일을 수정하고 검증(STEP 5~6)을 재실행
- 사용자가 거부한 경우 배포를 수행하지 않고, output_candidate/ 폴더에 파일만 남겨둠

### STEP 7. 실제 배포 실행
사용자가 검토 후 배포를 승인한 경우에만 수행:
- output_candidate/ 폴더의 파일로 실제 배포 수행:
  kubectl apply -f <프로젝트디렉토리>/output_candidate/ --namespace=default
- 배포 후 롤아웃 상태 확인:
  kubectl rollout status deployment/<앱이름> --namespace=default --timeout=120s
- 배포 결과 출력:
  kubectl get deployment <앱이름> --namespace=default
  kubectl get service <앱이름> --namespace=default
  kubectl get pods -l app=<앱이름> --namespace=default

### STEP 8. 결과 정리
- 배포 성공 후 output_candidate/ 폴더의 파일을 프로젝트 디렉토리의 output/ 폴더로 이동
- output_candidate/ 폴더를 삭제
- 다음 내용 요약 보고:
  * 생성된 파일 목록
  * 적용된 보안 설정 요약
  * 리소스 스펙 값과 추론 근거
  * Docker 이미지 빌드 및 push 결과
  * dry-run 결과
  * 실제 배포 수행 여부 및 결과 (승인된 경우)

---

## 주의사항
- 실제 kubectl apply (dry-run 없이)는 사용자가 명시적으로 요청한 경우에만 수행
- 민감한 값(DB 패스워드, API 키 등)은 절대 manifest에 평문으로 포함하지 않음
- 포트를 코드에서 추론할 수 없는 경우 사용자에게 확인 요청
