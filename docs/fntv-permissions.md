# 飞牛数据库权限与 Docker 挂载指南

这篇文档解决两类问题：

1. **读不到飞牛 `trimmedia.db`**（同步用不了）
2. **「写入飞牛」报 400 / 不可写**（v4 的回写功能用不了）

两种场景对权限的要求不同，先分清再动手。

---

## 0. 先分清两种需求

| 场景 | 需要什么权限 | 说明 |
| --- | --- | --- |
| 常规同步（飞牛 → Trakt） | 目录可执行 + 主库可读 + 目录可写（WAL 需要） | 数据库以 `mode=ro` 打开，不会修改飞牛数据 |
| 「写入飞牛」（Trakt → 飞牛） | 上面全部 + **主库可写** | 需要 `UPDATE / INSERT` 飞牛 `item_user_play` |

v3 只需要读；**v4 的「写入飞牛」必须能写**，所以：

> `/fntv` 不能挂成 `:ro`，主数据库文件也不能只给 `r`。

如果你完全不需要回写飞牛，可以保持只读，但「开发者 → 写入飞牛」会一直提示数据库不可写，此时请参考文末的[第 8 节](#8-如果-fntv-必须保持只读)。

---

## 1. 三个容易踩的概念

### 1.1 `:ro` 不等于「绕过权限」

```yaml
volumes:
  - /path/to/database:/fntv:ro
```

`:ro` 只是告诉 Docker「这个挂载在容器内只读」。它**不会**让 UID 1000 获得读取 `root:root 600` 文件的权限。

容器里的应用以 `PUID:PGID` 运行，通常是：

```text
uid=1000(fn2trakt) gid=1000(fn2trakt)
```

它必须同时满足：

- 能进入数据库所在目录（目录有 `x`）
- 能读取 `trimmedia.db`（文件有 `r`）
- 写入飞牛时，还要能写 `trimmedia.db`（文件有 `w`）与目录（有 `w`）

### 1.2 `docker exec` 默认是 root

```bash
docker exec fn2trakt cat /fntv/trimmedia.db
```

这条成功只说明 **root 能读**，不代表 UID 1000 能读。一定要带 `-u` 测试：

```bash
docker exec -u 1000 fn2trakt sh -c \
  'cat /fntv/trimmedia.db >/dev/null && echo READ_OK'
```

### 1.3 SQLite 的 WAL 模式需要能写 `-shm`

飞牛数据库大概率是 WAL 模式。WAL 下即使应用使用：

```text
file:/fntv/trimmedia.db?mode=ro
```

SQLite 仍需要在数据库目录里创建 / 写入：

```text
trimmedia.db-shm
trimmedia.db-wal
```

目录只读时就会报：

```text
attempt to write a readonly database
unable to open database file
```

> 主数据库文件可以只读，但**目录必须允许应用用户创建 `-shm`**。加上「写入飞牛」后，主库本身也需要 `w`。

---

## 2. 推荐配置

### 2.1 Compose（v4.1.4，含写入飞牛）

```yaml
name: fn2trakt
services:
  fn2trakt:
    image: spikeding/fn2trakt:4.1.4
    container_name: fn2trakt
    restart: unless-stopped
    init: true
    stop_grace_period: 30s
    ports:
      - "8213:8080"
    environment:
      TZ: Asia/Shanghai
      PUID: "1000"
      PGID: "1000"
      # 容器内路径，必须是 /data，不是宿主机路径
      FN2TRAKT_DATA_DIR: /data
      FN2TRAKT_FNTV_DB_PATH: /fntv/trimmedia.db
      FN2TRAKT_PORT: "8080"
      FN2TRAKT_COOKIE_SECURE: "false"
      FN2TRAKT_SESSION_DAYS: "30"
      FN2TRAKT_SYNC_ENABLED: "true"
      FN2TRAKT_SYNC_INTERVAL_MINUTES: "5"
      FN2TRAKT_TRAKT_TRUST_ENV: "true"
    volumes:
      # 左边是宿主机路径，按你的机器修改
      - ./data:/data
      - /usr/local/apps/@appdata/trim.media/database:/fntv
```

要点：

- 挂载的是**目录**，不是 `trimmedia.db` 单文件
- `/fntv` **不加 `:ro`**
- `/data` 必须可写
- `FN2TRAKT_DATA_DIR` 写容器内路径 `/data`，不要写宿主机路径

### 2.2 为什么不能只挂单文件

```yaml
# 不推荐
- /path/to/database/trimmedia.db:/fntv/trimmedia.db:ro
```

原因：

- WAL 的 `-shm` / `-wal` 不在容器里，SQLite 打开可能直接失败
- 宿主机文件不存在时，Docker 可能创建一个同名**目录**
- 飞牛更新数据库时单文件挂载更容易出问题

---

## 3. 检查当前状态

### 3.1 看容器挂载是不是 RW

```bash
docker inspect fn2trakt \
  --format '{{range .Mounts}}{{println .Source .Destination .RW}}{{end}}'
```

`/fntv` 必须是：

```text
... /fntv true
```

如果是 `false`，说明 compose 里还是 `:ro`，改成不带 `:ro` 后重建容器：

```bash
docker compose up -d --force-recreate
```

> `docker compose restart` **不会**改变 volume 的 `:ro` / `:rw`，必须 `--force-recreate`。

### 3.2 看宿主机权限

```bash
ls -ld /usr/local/apps/@appdata/trim.media/database
stat -c '%u:%g %a %n' \
  /usr/local/apps/@appdata/trim.media/database/trimmedia.db
```

典型问题：

```text
drwx------ root root  database
-rw------- root root  trimmedia.db
```

即 UID 1000 既进不去目录，也读不了文件。

### 3.3 检查父目录链路

```bash
namei -l /usr/local/apps/@appdata/trim.media/database/trimmedia.db
```

路径上每一层目录都必须对 UID 1000 有 `x` 权限。

---

## 4. 修复权限

### 方案 A：ACL（推荐，不改变 owner）

先确认系统支持：

```bash
command -v setfacl
```

给目录写权限，主库读 + 写（写飞牛需要）：

```bash
# 目录：进入 + 创建 -shm / -wal / 写入临时文件
sudo setfacl -m u:1000:rwx /usr/local/apps/@appdata/trim.media/database

# 主库：注意是 rw，不是 r
sudo setfacl -m u:1000:rw  /usr/local/apps/@appdata/trim.media/database/trimmedia.db
```

如果已存在 sidecar：

```bash
sudo setfacl -m u:1000:rw /usr/local/apps/@appdata/trim.media/database/trimmedia.db-wal 2>/dev/null || true
sudo setfacl -m u:1000:rw /usr/local/apps/@appdata/trim.media/database/trimmedia.db-shm 2>/dev/null || true
```

检查结果：

```bash
getfacl /usr/local/apps/@appdata/trim.media/database
getfacl /usr/local/apps/@appdata/trim.media/database/trimmedia.db
```

如果 ACL 的 `mask` 把权限挡住了，同步 mask：

```bash
sudo setfacl -m m::rwx /usr/local/apps/@appdata/trim.media/database
```

### 方案 B：组权限（没有 ACL 时）

不建议直接 `chown` 飞牛的数据目录，但可以把组设为应用组：

```bash
sudo chgrp 1000 /usr/local/apps/@appdata/trim.media/database
sudo chmod 775 /usr/local/apps/@appdata/trim.media/database

sudo chgrp 1000 /usr/local/apps/@appdata/trim.media/database/trimmedia.db
sudo chmod 660 /usr/local/apps/@appdata/trim.media/database/trimmedia.db
```

sidecar 同理（`-shm` / `-wal` 给 `660`）。

### 方案 C：让 PUID/PGID 与文件 owner 一致

```bash
stat -c '%u %g' /usr/local/apps/@appdata/trim.media/database/trimmedia.db
```

如果 owner 就是 1000，compose 保持 `PUID: "1000"` / `PGID: "1000"`。如果 owner 是 root，不建议为这个改 owner，优先用 ACL。

---

## 5. 验证

### 5.1 读 + 写都要通过

```bash
docker exec -u 1000 fn2trakt sh -c '
  id
  ls -ld /fntv
  cat /fntv/trimmedia.db >/dev/null && echo READ_OK
  touch /fntv/.write-test && rm /fntv/.write-test && echo WRITE_OK
'
```

必须看到：

```text
READ_OK
WRITE_OK
```

只有 `READ_OK` 时「同步」能用，但「写入飞牛」仍然会失败。

### 5.2 SQLite 能完整读取

```bash
docker exec -u 1000 -i fn2trakt python - <<'PY'
import sqlite3

con = sqlite3.connect("file:/fntv/trimmedia.db?mode=ro", uri=True, timeout=5)
print("tables:", con.execute("select count(*) from sqlite_master").fetchone())
print("item:", con.execute("select count(*) from item").fetchone())
print("plays:", con.execute("select count(*) from item_user_play").fetchone())
con.close()
PY
```

这里如果还报 `unable to open database file`，就是权限或 WAL 的问题，回到第 1.3 / 第 4 节。

### 5.3 确认 journal_mode 是 WAL

```bash
docker exec -i fn2trakt python - <<'PY'
import shutil, sqlite3

shutil.copy("/fntv/trimmedia.db", "/tmp/check.db")
con = sqlite3.connect("/tmp/check.db")
print(con.execute("pragma journal_mode").fetchone())
con.close()
PY
```

如果是 `('wal',)`，目录必须可写、compose 不能 `:ro`。

### 5.4 确认应用用的是容器内路径

```bash
docker exec -i fn2trakt python - <<'PY'
import sqlite3

con = sqlite3.connect("/data/fn2trakt.db")
print(con.execute("select key, value from setting where key='fntv.db_path'").fetchall())
con.close()
PY
```

- 返回空列表：使用环境变量 `FN2TRAKT_FNTV_DB_PATH`
- 返回宿主机路径（例如 `/usr/local/apps/.../trimmedia.db`）：容器里不存在，需要改成 `/fntv/trimmedia.db`

---

## 6. 「写入飞牛」报 400 怎么定位

页面只显示 400 时，直接看接口返回的 `detail`：

```bash
curl -s -H "Cookie: fn2t_session=<你的 session>" \
  "http://<NAS-IP>:8213/api/fntv/writeback/preview?account_id=1"
```

`detail` 会明确指向原因：

| `detail` 内容 | 含义 | 处理 |
| --- | --- | --- |
| 数据库不可写 | 主库或目录没有写权限 | 按第 4 节给 `rw`，重建容器 |
| 无法读取飞牛播放记录 | SQLite 打不开或 `-shm` 写不了 | 检查挂载 RW 与目录权限 |
| 绑定的飞牛用户不存在 | 站内账号绑定的 `fn_user_guid` 不在飞牛库 | 到「用户管理」重新绑定飞牛用户 |
| `unable to open database file` | 路径错误或目录不可访问 | 检查 `fntv.db_path` 与挂载 |

先把 `READ_OK` 和 `WRITE_OK` 都跑通，多数 400 会直接消失。

---

## 7. 常见报错对照

| 报错 | 原因 | 处理 |
| --- | --- | --- |
| `could not read full fnTV library: unable to open database file` | 读取完整媒体库时打不开库：通常是 `/fntv` 为 `:ro`、目录无 `w`（WAL 建不了 `-shm`），或 UID 1000 无读权限 | 去掉 `:ro`，按第 4 节给目录 `rwx`、主库 `rw` |
| `Permission denied: '/fntv/trimmedia.db'` | UID 1000 没有目录 `x` 或文件 `r` | ACL / 组权限 / 调整 PUID |
| `unable to open database file` | 目录只读，SQLite 无法创建 `-shm` | 去掉 `:ro`，给目录写权限 |
| `attempt to write a readonly database` | WAL 的 `-shm` / `-wal` 不可写，或目录只读 | 给目录与 sidecar 写权限 |
| 写入飞牛提示数据库不可写 | 主库只有 `r`，没有 `w` | `setfacl -m u:1000:rw trimmedia.db` |
| `no such table: item` | 挂载到了错误的数据库，或数据库为空 | 检查 `FN2TRAKT_FNTV_DB_PATH` |
| 设置页显示宿主机路径 | 旧数据保存了宿主路径 | 改成 `/fntv/trimmedia.db` |

---

## 8. 如果 `/fntv` 必须保持只读

那「写入飞牛」就不能用，只能：

- 继续用常规同步（飞牛 → Trakt），完全不受影响
- 或者把飞牛数据库复制到可写目录，挂载**副本**：

```bash
mkdir -p /vol1/docker/fn2trakt/fntv

sqlite3 /usr/local/apps/@appdata/trim.media/database/trimmedia.db \
  ".backup '/vol1/docker/fn2trakt/fntv/trimmedia.db'"

sudo chown -R 1000:1000 /vol1/docker/fn2trakt/fntv
```

```yaml
volumes:
  - /vol1/docker/fn2trakt/fntv:/fntv
```

缺点：

- 副本不会自动更新，需要自己定时刷新
- 写入只会落在副本里，飞牛 App 看不到

「写入飞牛」本质上必须能写飞牛数据库，不能只读。

---

## 9. 安全边界

- 常规同步始终以 `mode=ro` 打开主库，不会修改飞牛数据
- 只有「写入飞牛」会修改 `item_user_play`，且执行前自动备份到 `data/backups/`
- 目录可写是为了让 SQLite 创建 `-shm`
- 不要使用 `chmod 777`
- 不要随意 `chown` 飞牛的数据目录
- 修改前建议备份数据库

---

## 10. 最小检查清单

```text
[ ] /fntv 挂载的是目录，不是单文件
[ ] compose 中 /fntv 没有 :ro
[ ] docker inspect 显示 /fntv RW=true
[ ] UID 1000 能进入目录并读取 trimmedia.db（READ_OK）
[ ] UID 1000 能在 /fntv 创建临时文件（WRITE_OK）
[ ] trimmedia.db 对 UID 1000 是 rw（写入飞牛需要）
[ ] journal_mode 是 wal
[ ] 设置中的 fntv.db_path 是 /fntv/trimmedia.db
[ ] 改完 compose 后用 --force-recreate 重建容器
```

全部通过后，飞牛数据库读取与「写入飞牛」都可以正常工作。
