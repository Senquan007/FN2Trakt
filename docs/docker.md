# Docker / Docker Compose 部署

推荐方式：**一份 `docker-compose.yml`，不用 `.env`**。所有配置直接写在 compose 文件里，改完 `docker compose up -d` 即生效。

## 快速开始

```bash
mkdir -p /vol1/docker/fn2trakt && cd /vol1/docker/fn2trakt
curl -O https://raw.githubusercontent.com/Senquan007/FN2Trakt/main/docker-compose.yml
# 改两处：宿主机端口、飞牛数据库目录
docker compose up -d
```

打开 `http://<NAS-IP>:8213`，按初始化向导操作。

`docker-compose.yml` 里需要按你的机器改的只有两处：

```yaml
    ports:
      - "8213:8080"        # 冒号左边是宿主机端口，容器内固定 8080
    volumes:
      - ./data:/data
      - /usr/local/apps/@appdata/trim.media/database:/fntv
```

其余 `environment` 都是容器内路径与默认值，保持原样。

## 目录与端口

| 项目 | 位置 | 说明 |
| --- | --- | --- |
| 宿主机端口 | `ports:` 左边 | 默认 `8213`，可改 `8080` / `18080` 等 |
| 应用数据 | `./data` → `/data` | `fn2trakt.db`、`.secret_key`、`backups/` |
| 飞牛数据库 | 宿主机目录 → `/fntv` | 必须是**目录**，不是 `trimmedia.db` 单文件 |

容器内路径：

```text
/data/                 应用 SQLite、密钥、备份
/fntv/trimmedia.db     飞牛数据库（常规只读；写入飞牛时需要可写）
```

`/data` 必须可写；entrypoint 会按 `PUID:PGID` 修正目录所有者。`/fntv` 常规同步只需可读可进入；使用「写入飞牛」时需要目录可写、主库 `rw`，且挂载不能加 `:ro`。

## 更新

```bash
# 改 compose 里的 image 标签（例如 4.1.4 -> 4.2.0）后
docker compose pull
docker compose up -d
```

改端口或挂载后必须重建容器，`restart` 不会应用新的挂载：

```bash
docker compose up -d --force-recreate
```

## 备份

应用数据库在 `./data/fn2trakt.db`。写入飞牛 / 恢复操作会自动备份到 `./data/backups/`。

## 常见问题

- **端口被占用**：改 `ports:` 左边的数字，例如 `"18080:8080"`。
- **无法读取飞牛库**：确认挂载的是包含 `trimmedia.db` 的**目录**，并且容器用户（`PUID`）有读权限。
- **权限错误**：把 compose 里的 `PUID` / `PGID` 改成 `id -u` / `id -g` 的结果。
- **`could not read full fnTV library: unable to open database file`**：`/fntv` 挂载成了 `:ro` 或目录不可写（WAL 无法创建 `-shm`）。去掉 `:ro` 后 `docker compose up -d --force-recreate`，详见 [fntv-permissions.md](fntv-permissions.md)。
- **写入飞牛 400**：先按权限文档确认 `READ_OK` 与 `WRITE_OK` 都通过，再看接口 `detail`。
- **首次启动没有管理员**：打开首页会进入初始化向导；也可以在 compose 的 `environment` 里加 `FN2TRAKT_ADMIN_USERNAME` / `FN2TRAKT_ADMIN_PASSWORD` 自动创建。

## 源码构建镜像

日常部署不需要这一步，用 `docker-compose.yml` 直接拉取镜像即可。

```bash
docker compose -f docker-compose.build.yml up -d --build
```

`docker-compose.build.yml` 同样不使用 `.env`，配置与 `docker-compose.yml` 一致，只是把 `image:` 换成 `build:`。

## 离线 / 跨架构

镜像已经发布到 Docker Hub：`spikeding/fn2trakt:4.1.4`（多架构清单，amd64 与 arm64 自动匹配）。

需要离线搬运时，在能联网的机器上导出：

```bash
docker pull spikeding/fn2trakt:4.1.4
docker save spikeding/fn2trakt:4.1.4 | gzip > fn2trakt-4.1.4.tar.gz
```

拷到目标机器后载入，并把 compose 里的 `image:` 保持为同一个标签：

```bash
docker load -i fn2trakt-4.1.4.tar.gz
docker compose up -d
```

只构建单一架构时：

```bash
docker buildx build --platform linux/amd64 -t fn2trakt:4.1.4-amd64 --load .
# 载入后把 compose 的 image 改成 fn2trakt:4.1.4-amd64
```

> v4 的「Trakt → 飞牛写入」需要目录写权限与主库 `rw`，详见 [fntv-writeback.md](fntv-writeback.md) 与 [fntv-permissions.md](fntv-permissions.md)。
