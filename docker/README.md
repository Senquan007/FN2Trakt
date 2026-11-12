# Docker 相关文件

- `entrypoint.sh`：容器启动脚本，负责修正 `/data` 权限并以 `PUID:PGID` 运行。
- 镜像构建：见根目录 `Dockerfile`。
- 拉取预构建镜像：见根目录 `docker-compose.yml`。
- 从源码构建：见根目录 `docker-compose.build.yml`。

完整部署说明见 [`../README.md`](../README.md) 和 [`../docs/docker.md`](../docs/docker.md)。
