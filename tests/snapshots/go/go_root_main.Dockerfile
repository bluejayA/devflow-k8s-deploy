# 빌드 단계: Go toolchain (alpine 기반)
FROM golang:1.22-alpine AS builder

WORKDIR /build

# 의존성 캐시 레이어 — go.mod/go.sum 만 먼저 복사해 소스 변경 시 재사용
# go.sum은 vendor 미사용 신규 프로젝트에서 부재할 수 있어 와일드카드 사용
COPY go.mod go.sum* ./
RUN go mod download

# 소스 전체 복사 — `.dockerignore`(k8s-output/, .git/, vendor/, .env 등)로 오염 차단
COPY . .

# 정적 링크 + 심볼/디버그 정보 제거 (-s -w)로 distroless 호환 + 바이너리 크기 최소화
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o myapp .

# 런타임 단계: distroless static (UID 65532 nonroot 내장)
# 비root + 셸 부재 + 최소 surface = 컨테이너 탈출 시 호스트 root 권한 차단
FROM gcr.io/distroless/static-debian12:nonroot

WORKDIR /app

# distroless는 USER/addgroup 불필요 (nonroot 내장 UID 65532).
# COPY --chown — UID 65532:65532 명시
COPY --from=builder --chown=65532:65532 /build/myapp /app/myapp

# latest 태그 금지 — 재현성 + 공급망 공격 방지

EXPOSE 8080

USER nonroot

ENTRYPOINT ["/app/myapp"]
