# 빌드 단계: JDK로 소스 빌드 (builder image에 시스템 gradle/maven 포함)
FROM gradle:jdk21-alpine AS builder

WORKDIR /build

# 의존성 캐시 레이어 — 빌드 스크립트만 먼저 복사해 소스 변경 시 재사용
COPY build.gradle* settings.gradle* gradle.properties* ./
RUN gradle --no-daemon dependencies > /dev/null 2>&1 || true

# 소스 + 모듈 전체 복사 — `.dockerignore`(k8s-output/, .git/, build/, target/, .env 등)로 오염 차단
COPY . .
RUN gradle --no-daemon bootJar

# 런타임 단계: JRE로 경량 실행
FROM eclipse-temurin:21-jre-alpine

# 비root 사용자 — 컨테이너 탈출 시 호스트 root 권한 차단
# busybox 계열(alpine) 유틸 사용 — glibc 전용 명령은 alpine에서 미동작
RUN addgroup -S -g 1000 appgroup \
 && adduser -S -u 1000 -G appgroup -H appuser

WORKDIR /app

# COPY --chown — 임의 사용자 ID 충돌 방지
COPY --from=builder --chown=appuser:appgroup /build/build/libs/*.jar /app/app.jar

# latest 태그 금지 — 재현성 + 공급망 공격 방지 (builder/runner 이미지 태그에 반영)

EXPOSE 8080

USER appuser

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
