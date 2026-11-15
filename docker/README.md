# Docker 交付物

## 目录

- `image/`：x86_64 离线镜像包与 SHA-256（按需用 `docker save` 生成，命名 `fn2trakt-<版本>-amd64.tar.gz`）
- `deploy/`：从 Docker Hub 拉取镜像的 Compose 部署
- `entrypoint.sh`：源码构建镜像时使用的启动脚本

源码构建配置在仓库根目录：`Dockerfile`、`docker-compose.yml`、`.env.docker.example`。

## 直接拉取镜像（推荐）

```bash
docker pull spikeding/fn2trakt:4.1.4
cp docker/deploy/.env.example .env
# 编辑 .env：FN2TRAKT_IMAGE=spikeding/fn2trakt:4.1.4、DATA_DIR、FNTV_DB_DIR
docker compose --project-directory . -f docker/deploy/docker-compose.yml up -d --no-build
```

## x86_64 离线部署

有离线包时（`fn2trakt-4.1.4-amd64.tar.gz`）：

```bash
docker load -i docker/image/fn2trakt-4.1.4-amd64.tar.gz
cp docker/deploy/.env.example .env
# 编辑 .env，至少设置 FN2TRAKT_IMAGE / DATA_DIR / FNTV_DB_DIR
docker compose --project-directory . -f docker/deploy/docker-compose.yml up -d
```

没有离线包时可以先导出：

```bash
docker pull spikeding/fn2trakt:4.1.4
docker save spikeding/fn2trakt:4.1.4 | gzip > docker/image/fn2trakt-4.1.4-amd64.tar.gz
shasum -a 256 docker/image/fn2trakt-4.1.4-amd64.tar.gz > docker/image/fn2trakt-4.1.4-amd64.tar.gz.sha256
```

## 源码构建

```bash
cp .env.docker.example .env
docker compose up -d --build
```

## 挂载权限

`/fntv` 不要加 `:ro`：常规同步只需要读，但 SQLite 的 WAL 要在目录里创建 `-shm`，v4 的「写入飞牛」还需要主库 `rw`。排查步骤见 [`../docs/fntv-permissions.md`](../docs/fntv-permissions.md)。

完整参数见 [`../docs/docker.md`](../docs/docker.md)。
