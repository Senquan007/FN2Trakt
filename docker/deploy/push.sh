#!/usr/bin/env bash
# 把本地 amd64 + arm64 两个镜像合并成多架构清单并推送到 Docker Hub
set -euo pipefail

USER_NAME="${1:-${DOCKERHUB_USER:-}}"
if [ -z "$USER_NAME" ]; then
  echo "用法: $0 <dockerhub用户名>"
  echo "  或: DOCKERHUB_USER=<用户名> $0"
  exit 1
fi

REPO="$USER_NAME/fn2trakt"
VERSION="${VERSION:-4.1.4}"
AMD64_IMAGE="${AMD64_IMAGE:-fn2trakt:4.1.4-amd64}"
ARM64_IMAGE="${ARM64_IMAGE:-fn2trakt:4.1.4}"

for img in "$AMD64_IMAGE" "$ARM64_IMAGE"; do
  if ! docker image inspect "$img" >/dev/null 2>&1; then
    echo "找不到本地镜像: $img"
    exit 1
  fi
done

echo "==> 架构确认"
docker image inspect "$AMD64_IMAGE" --format "  $AMD64_IMAGE  ->  {{.Os}}/{{.Architecture}}"
docker image inspect "$ARM64_IMAGE" --format "  $ARM64_IMAGE  ->  {{.Os}}/{{.Architecture}}"

echo "==> 打标签"
docker tag "$AMD64_IMAGE" "$REPO:$VERSION-amd64"
docker tag "$ARM64_IMAGE" "$REPO:$VERSION-arm64"

echo "==> 推送单架构镜像"
docker push "$REPO:$VERSION-amd64"
docker push "$REPO:$VERSION-arm64"

echo "==> 合成多架构清单"
docker buildx imagetools create \
  -t "$REPO:$VERSION" \
  -t "$REPO:latest" \
  "$REPO:$VERSION-amd64" "$REPO:$VERSION-arm64"

echo "==> 结果"
docker buildx imagetools inspect "$REPO:$VERSION"
