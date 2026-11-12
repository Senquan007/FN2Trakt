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
| GET | `/media/targets` | 需要处理的媒体（未匹配 / 自动 / 手动 / 忽略） |
| GET | `/media/search` | 搜索 Trakt 候选条目 |
| POST | `/media/match` | 保存手动匹配 |
| POST | `/media/reject` | 忽略媒体 |
| POST | `/media/rematch` | 重新自动匹配（管理员） |

`/plays` 的 `status`：

- `all`、`completed`
- `pending`（已看完、已匹配、未上传）
- `synced`、`failed`、`blocked`
- `unmatched`（含被忽略）

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

## v3：Trakt 历史回填（管理员）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/trakt/history/accounts` | 可回填的 Trakt 账号列表 |
| GET | `/trakt/history/summary?account_id=` | 本地历史镜像计数、最近拉取/回填 |
| POST | `/trakt/history/pull` | 拉取全部 Trakt 历史并写入 `trakt_history` |
| GET | `/trakt/history/preview?account_id=` | 预演将更新哪些本地播放记录（只读） |
| POST | `/trakt/history/apply` | 备份数据库后执行回填；必须传 `{"confirm": true}` |

回填会处理「Trakt 历史能匹配到飞牛媒体库」的记录：已有 PlayRecord 的更新，没有 PlayRecord 的会补建 `media_item` + `play_record`；飞牛库没有的条目只保存在历史镜像中，供 API 查询。

执行 `apply` 前会自动使用 SQLite backup API 备份到 `data/backups/fn2trakt-<时间>-before-backfill.db`，响应返回 `backup_path`。

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
- `backfill.completed`：Trakt 历史回填完成
- `test`：测试通知

请求体是 JSON，包含 `event`、`version`、`sent_at`、`data`。如果端点配置了 Secret，会附加：

```http
X-FN2Trakt-Event: sync.failed
X-FN2Trakt-Delivery: 123
X-FN2Trakt-Signature: sha256=<hex hmac-sha256 of raw body>
```

失败会在 5 分钟后自动重试，最多 3 次；可在「开发者 → Webhook」查看投递结果。
