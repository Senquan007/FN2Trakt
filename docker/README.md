# Docker 交付物

## 目录

- `../docker-compose.yml`：**推荐**，直接拉取 `spikeding/fn2trakt:4.1.4`，配置写在文件内（不使用 `.env`）
- `../docker-compose.build.yml`：源码构建镜像
- `entrypoint.sh`：容器启动脚本（按 `PUID:PGID` 修正数据目录、生成密钥等）
- `push.sh`：把本地 amd64 / arm64 镜像合并成多架构清单并推送到 Docker Hub

## 直接拉取镜像（推荐）

```bash
curl -O https://raw.githubusercontent.com/Senquan007/FN2Trakt/main/docker-compose.yml
# 改两处：ports 左边端口、/fntv 的宿主机目录
docker compose up -d
```

打开 `http://<NAS-IP>:8213`。

## 离线部署

镜像已在 Docker Hub 发布，需要离线搬运时先在联网机器导出：

```bash
docker pull spikeding/fn2trakt:4.1.4
docker save spikeding/fn2trakt:4.1.4 | gzip > fn2trakt-4.1.4.tar.gz
shasum -a 256 fn2trakt-4.1.4.tar.gz > fn2trakt-4.1.4.tar.gz.sha256
```

目标机器：

```bash
docker load -i fn2trakt-4.1.4.tar.gz
docker compose up -d
```

## 源码构建

```bash
docker compose -f docker-compose.build.yml up -d --build
```

## 发布镜像（维护者）

```bash
docker buildx build --platform linux/amd64 -t fn2trakt:4.1.4-amd64 --load .
docker buildx build --platform linux/arm64 -t fn2trakt:4.1.4 --load .
./docker/push.sh <dockerhub用户名>
```

## 挂载权限

`/fntv` 不要加 `:ro`：常规同步只需要读，但 SQLite 的 WAL 要在目录里创建 `-shm`，v4 的「写入飞牛」还需要主库 `rw`。排查步骤见 [`../docs/fntv-permissions.md`](../docs/fntv-permissions.md)。

完整参数见 [`../docs/docker.md`](../docs/docker.md)。
