# HTTP API

内部管理接口基址：`http://<host>:8080/api`。除 `/health`、`/setup/*`、`/auth/login` 外均需登录 Cookie。

个人只读 API 使用 Bearer Token，基址为 `/api/v1`，见 [api-v1.md](api-v1.md)。

## 认证与初始化

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| GET | `/setup/status` | 是否需要初始化；未初始化时返回飞牛库探测结果 |
| POST | `/setup` | 创建首个管理员（仅当无用户） |
| POST | `/auth/login` | 登录，写入 `fn2t_session` Cookie |
| POST | `/auth/logout` | 退出 |
| GET | `/auth/me` | 当前用户、飞牛绑定、Trakt 绑定 |
| POST | `/auth/password` | 修改自己的密码 |

## 用户（管理员）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/users` | 用户列表（含绑定与已看完数量，管理员） |
| POST | `/users` | 创建账号，可绑定飞牛用户 |
| PATCH | `/users/{id}` | 改角色 / 启停 / 绑定 / 重置密码 |
| DELETE | `/users/{id}` | 删除账号 |

## 飞牛数据

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/fntv/status` | 数据库路径、表、计数、本地缓存统计 |
| GET | `/fntv/users` | 实时读取飞牛用户列表（管理员） |
| POST | `/fntv/refresh` | 重新读取并入库，可选自动匹配 |
| GET | `/fntv/schema` | 返回飞牛库 DDL（管理员） |

## Trakt 绑定

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/trakt/credential-status` | 默认凭据是否可用（普通用户只返回 `configured`） |
| GET | `/trakt/credentials` | 命名凭据列表（管理员；不含 Client ID / Secret） |
| POST | `/trakt/credentials` | 新建凭据（管理员） |
| PATCH | `/trakt/credentials/{id}` | 更新名称 / 重填 ID 或 Secret / Redirect URI（管理员） |
| POST | `/trakt/credentials/{id}/default` | 设为默认凭据（管理员） |
| DELETE | `/trakt/credentials/{id}` | 删除凭据；有账号使用时拒绝（管理员） |
| POST | `/trakt/device/start` | 生成设备码，返回 `user_code` / `verification_url` |
| GET | `/trakt/device/{id}` | 轮询授权状态；服务端按 Trakt `interval` 限速 |
| GET | `/trakt/account` | 当前用户 Trakt 绑定 |
| DELETE | `/trakt/account` | 解除绑定 |
| GET | `/trakt/accounts` | 全部绑定（管理员） |

设备码状态：`pending` / `authorized` / `expired` / `denied` / `error`。

## 角色说明

- 管理员：用户管理、飞牛用户分配、Trakt 应用凭据、全量数据、媒体匹配。
- 普通用户：仅自己的观看记录 / 同步记录，以及自己的 Trakt 设备授权；无法读取凭据列表。

凭据接口的任何响应都不会包含 `client_id` 或 `client_secret` 明文；修改时需要重新输入。

## 观看记录与匹配

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/plays` | 分页列表；支持状态、用户、类型、关键词、日期过滤 |
| GET | `/plays/{id}` | 单条详情（含原始记录、同步请求） |
| GET | `/media/targets` | 需要处理的媒体（未匹配 / 自动 / 手动 / 忽略）；孤儿播放记录（媒体条目缺失）也会列出，`orphan=true` |
| GET | `/media/search` | 搜索 Trakt 候选条目 |
| POST | `/media/match` | 保存手动匹配 |
| POST | `/media/reject` | 忽略媒体 |
| POST | `/media/rematch` | 重新自动匹配（管理员） |

`/plays` 的 `status`：

- `all`、`completed`
- `pending`（已看完、已匹配、未上传）
- `synced`、`failed`、`blocked`
- `unmatched`（真正未匹配到 Trakt）
- `rejected`（已忽略，与 `unmatched` 分开，和「媒体匹配」分组一致）
- `writeback_pending`（匹配成功、尚未写入飞牛，保留给脚本使用）
- `writeback_written`（已写入飞牛，保留给脚本使用）

每条记录带 `writeback` 字段描述飞牛方向的状态：

```json
"writeback": {"status": "written", "at": "2026-11-15T16:23:06Z"}
```

`status` 取值：`none`（未匹配或已忽略）、`pending`（匹配成功待写入）、`written`（已写入飞牛）。
前端「观看记录」只展示 Trakt 同步状态，不再渲染这两个筛选与 `writeback` 标记，字段保留给自动化脚本按需使用。
`summary` 同步返回 `rejected`、`writeback_pending`、`writeback_written` 计数。

进度字段有两个：

- `progress_percent`：飞牛库里的原始进度（`播放位置 / 时长`），已看完的条目可能因为播放位置被清零而变成 `0`；
- `progress_display`：供界面展示的进度，`completed=true` 时固定为 `100`，其余情况等于原始进度。

## 同步

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/sync/preview` | 预估可上传 / 已同步 / 阻塞数量 |
| POST | `/sync/run` | 启动当前用户同步（后台线程） |
| POST | `/sync/run-all` | 为所有已绑定用户创建同步任务（管理员） |
| POST | `/sync/play/{id}` | 立即上传单条记录（同步返回结果） |
| GET | `/sync/runs` | 同步任务列表 |
| GET | `/sync/records` | 单条上传记录与错误 |
| POST | `/sync/records/{id}/retry` | 重置并重试单条 |

## 仪表盘与设置

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/dashboard` | 统计、30 天趋势、状态分布、热门剧、最近同步 |
| GET | `/settings` | 数据库路径、同步间隔、阈值、调度器状态 |
| PUT | `/settings` | 保存设置；阈值变化会立即重算已看完 |
| POST | `/settings/test-fntv` | 测试飞牛数据库路径 |

## 错误格式

```json
{ "detail": "可读的错误信息" }
```

Trakt 侧错误会映射为 400，并保留可读原因（例如「Trakt 未找到该条目」「授权码已过期」）。

## v3：Trakt 历史镜像（管理员）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/trakt/history/accounts` | 可拉取历史的 Trakt 账号列表 |
| GET | `/trakt/history/summary?account_id=` | 本地历史镜像计数、最近拉取 / 写入时间 |
| POST | `/trakt/history/pull` | 拉取全部 Trakt 历史并写入 `trakt_history`，同时完成飞牛媒体库匹配 |

> v4.1.2 起，「Trakt 回填（写入本地假记录）」已移除：`/trakt/history/preview` 与 `/trakt/history/apply` 不再提供。请使用下方的「写入飞牛」，它只写飞牛数据库，不伪造本地播放记录。

## v3：个人 API Token

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/tokens` | 当前用户的 Token 列表（只返回前缀） |
| POST | `/tokens` | 创建 Token；响应中的 `token` 只出现一次 |
| DELETE | `/tokens/{id}` | 撤销 Token |

外部调用接口见 [api-v1.md](api-v1.md)。

## v3：Webhook（管理员）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/webhooks` | 端点列表与可用事件 |
| POST | `/webhooks` | 新建端点 |
| PATCH | `/webhooks/{id}` | 修改名称 / URL / 事件 / Secret / 启停 |
| DELETE | `/webhooks/{id}` | 删除端点 |
| POST | `/webhooks/{id}/test` | 发送测试通知 |
| GET | `/webhooks/deliveries?limit=50` | 最近投递 |
| POST | `/webhooks/deliveries/{id}/retry` | 手动重试（最多 3 次） |

事件：

- `sync.failed`：同步任务失败或部分失败
- `sync.unmatched`：存在未匹配 / 上传失败的记录（同一批记录只提醒一次）
- `sync.completed`：同步完成且有新记录上传
- `backfill.completed`：写入飞牛完成（旧名“回填”）
- `test`：测试通知

端点的 `format` 决定请求体形状：`generic`（默认，FN2Trakt 原始 JSON）、`feishu`（飞书自定义机器人）、`dingtalk`（钉钉加签）、`wecom`（企业微信群机器人）。新建时若不传则按 URL 自动识别。

通用 JSON 请求体包含 `event`、`version`、`sent_at`、`data`。如果端点配置了 Secret，会附加：

```http
X-FN2Trakt-Event: sync.failed
X-FN2Trakt-Signature: sha256=<hex hmac-sha256 of raw body>
```

飞书要求 `timestamp` / `sign` 位于请求体内并使用 `msg_type` + `content`，否则返回 `19021 sign match fail`；v4.1.2 已按官方算法实现。

失败会在 5 分钟后自动重试，最多 3 次；可在「开发者 → Webhook」查看投递结果。

## v4：Trakt → 飞牛数据库写入（管理员，危险）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/fntv/writeback/preview?account_id=` | 预演将写入飞牛 `item_user_play` 的记录（只读，使用本地已拉取的历史） |
| POST | `/fntv/writeback/preview` | 预演并可先拉取 Trakt 历史（`{"account_id": 1, "pull": true, "include_written": false}`） |
| POST | `/fntv/writeback/apply` | 备份飞牛数据库后写入；必须传 `{"confirm": true, "expected_total": <预览条数>}`；`include_written=true` 才会重写已写入过的记录 |
| GET | `/fntv/backups` | 列出飞牛数据库备份 |
| POST | `/fntv/restore` | 用指定备份恢复飞牛数据库；必须传 `{"confirm": true}` |

预览返回 `summary.already_written`（已写入过、默认跳过）、`items`（匹配成功待写入）与 `written_items`（已写入）。
默认跳过已写入记录，避免重复写入同一个 Trakt 历史。

写入前会使用 SQLite backup API 备份到：

```text
DATA_DIR/backups/fntv-YYYYMMDD-HHMMSS-before-writeback.db
```

恢复前会再备份当前数据库：

```text
DATA_DIR/backups/fntv-YYYYMMDD-HHMMSS-before-restore.db
```

恢复只覆盖飞牛数据库，不恢复 FN2Trakt 本地数据库。

`apply` 会校验 `expected_total`：如果预览之后待写入条数发生变化，会返回 400 并提示重新预览。响应中的 `skipped` 为无法匹配（不在媒体库 / 缺少可播放文件）而被跳过的条数。

> 该功能需要容器对飞牛数据库有写权限；普通同步仍然只读。
