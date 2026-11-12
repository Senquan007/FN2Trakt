# Docker / Docker Compose 部署

## 快速开始

```bash
cp .env.docker.example .env
# 按需修改 .env 中的路径和端口
docker compose up -d --build
```

打开 `http://<NAS-IP>:<FN2TRAKT_HOST_PORT>`，按初始化向导操作。

如果不想使用默认的 `.env`，可以指定其他文件：

```bash
docker compose --env-file my.env up -d
```

## 目录与端口

`.env` 中最重要的四个变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `FN2TRAKT_HOST_PORT` | `8080` | 宿主机端口；容器内部固定 8080 |
| `DATA_DIR` | `./data` | 宿主机上的应用数据目录，挂载到容器 `/data` |
| `FNTV_DB_DIR` | `./DB` | 飞牛数据库所在目录，只读挂载到 `/fntv` |
| `FNTV_DB_FILE` | `trimmedia.db` | 目录下的数据库文件名 |

NAS 示例：

```dotenv
FN2TRAKT_HOST_PORT=8080
DATA_DIR=/vol1/docker/fn2trakt/data
FNTV_DB_DIR=/vol1/@appdata/trim.media/database
FNTV_DB_FILE=trimmedia.db
PUID=1000
PGID=1000
```

容器内路径：

```text
/data/                 应用 SQLite、密钥、备份
/fntv/trimmedia.db     飞牛数据库（只读）
```

`DATA_DIR` 必须可写；entrypoint 会按 `PUID:PGID` 修正目录所有者。`FNTV_DB_DIR` 只需要可读。

## 更新

```bash
docker compose build --pull
docker compose up -d
```

## 备份

应用数据库在 `DATA_DIR/fn2trakt.db`。回填操作也会自动备份到 `DATA_DIR/backups/`。

## 常见问题

- **端口被占用**：改 `FN2TRAKT_HOST_PORT`，例如 `18080`。
- **无法读取飞牛库**：确认 `FNTV_DB_DIR` 指向包含 `trimmedia.db` 的目录，并且容器用户有读权限。
- **权限错误**：把 `.env` 中 `PUID/PGID` 改成 `id -u` / `id -g` 的结果。
- **首次启动没有管理员**：打开首页会进入初始化向导；也可以使用 `FN2TRAKT_ADMIN_USERNAME` / `FN2TRAKT_ADMIN_PASSWORD` 自动创建。

## 使用预构建 x86 镜像

如果不想在 NAS 上构建，可以直接加载 amd64 镜像包：

```bash
docker load -i fn2trakt-3.0.0-amd64.tar.gz
```

确认镜像：

```bash
docker images fn2trakt
# fn2trakt:3.0.0-amd64
```

`.env` 中设置：

```dotenv
FN2TRAKT_IMAGE=fn2trakt:3.0.0-amd64
```

然后启动，不需要 `--build`：

```bash
docker compose up -d --no-build
```

镜像包约 74 MB，适用于 `linux/amd64`（绝大多数 x86 NAS）。Apple Silicon 上的本地镜像是 `fn2trakt:3.0.0`，两者不要混用。

## 镜像架构

镜像会在构建它的机器上生成对应架构：

- 在 Apple Silicon Mac 上构建的是 `linux/arm64`
- 在大多数 x86 NAS 上构建的是 `linux/amd64`

如果构建机和部署机架构不同，请在部署机上执行 `docker compose build`，或在构建机上使用：

```bash
docker buildx build --platform linux/amd64 -t fn2trakt:3.0.0-amd64 --load .
# 传到 NAS 后
docker load -i fn2trakt-3.0.0-amd64.tar
```

然后把 `.env` 里的 `FN2TRAKT_IMAGE` 改成对应的镜像标签。
