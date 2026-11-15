# Trakt → 飞牛数据库写入（危险操作）

> 这是 FN2Trakt v4 唯一会写入飞牛数据库的功能。默认不会自动执行，必须由管理员手动确认。

## 它做什么

把已经匹配到飞牛媒体库的 Trakt 观看历史，写入飞牛的：

```text
item_user_play
```

效果：

- 飞牛 App 里这些电影 / 剧集显示为已看
- 播放进度变为 100%
- 观看时间使用 Trakt 的 `watched_at`
- 没有播放记录的条目会新建一条

不会修改：

- 飞牛的 `item` / `user` / 媒体文件
- FN2Trakt 的常规只读同步逻辑

## 操作前必须满足

1. 当前账号是管理员
2. 已经绑定 Trakt 账号
3. 当前 Trakt 账号已经绑定飞牛用户
4. 页面上点过「拉取 Trakt 历史」（写入页内即可完成，不必先去别的页面）
5. 容器对飞牛数据库有**写权限**
6. 飞牛数据库目录可写（WAL 需要 `-shm`）

### 权限要求

这是 v4 和普通只读模式最大的区别。

```text
UID 1000 需要：
  目录  rwx
  主库  rw
  侧车  rw（如果存在）
```

示例：

```bash
sudo setfacl -m u:1000:rwx /path/to/trim.media/database
sudo setfacl -m u:1000:rw /path/to/trim.media/database/trimmedia.db
```

compose 需要：

```yaml
volumes:
  - /path/to/trim.media/database:/fntv
```

不要加 `:ro`。

> 普通同步只需要读；写入飞牛必须临时开放写权限。操作完成后可以再收回。

写权限是否到位，用应用用户（不是 root）验证：

```bash
docker exec -u 1000 fn2trakt sh -c '
  cat /fntv/trimmedia.db >/dev/null && echo READ_OK
  touch /fntv/.write-test && rm /fntv/.write-test && echo WRITE_OK
'
```

必须同时看到 `READ_OK` 与 `WRITE_OK`。缺少 `WRITE_OK` 或报
`could not read full fnTV library: unable to open database file`
时，按 [飞牛数据库权限与 Docker 挂载](fntv-permissions.md) 逐项排查（`/fntv` 不能是 `:ro`）。

## 操作步骤

### 1. 拉取历史 + 预览

打开：

```text
开发者 → 写入飞牛
```

点击「拉取 Trakt 历史」，会先从 Trakt 拉取完整历史并完成匹配，然后显示：

- 目标飞牛用户、数据库是否可写
- Trakt 历史总数、最近拉取时间
- **匹配成功，待写入**：可写入条数、更新 / 新建数量、前 20 条记录
- **已写入飞牛**：之前已成功写入的记录及写入时间（默认跳过，不重复写入）
- **无法匹配（将跳过）**：不在飞牛媒体库 / 缺少可播放文件的条目及原因

之后可随时点「刷新预览」用本地已拉取的历史重新计算，不会重复请求 Trakt。
需要重写已写入的记录时，打开工具栏的「含已写入」再预览（此时它们会重新出现在待写入列表中）。

如果显示“数据库不可写”，先处理权限：见 [fntv-permissions.md](fntv-permissions.md)；接口返回 400 时可直接看 `detail`（数据库不可写 / 无法读取播放记录 / 飞牛用户不存在）。

### 2. 两步确认写入

点击「开始写入飞牛」：

1. **第 1 步**：核对写入条数、跳过条数与目标用户，勾选「我已核对写入范围与跳过数量」→ 下一步。
2. **第 2 步**：最终确认，勾选后点「确认写入」。

提交时会带上预览时的条数；如果预览之后数据发生变化（重新拉取、重新匹配），后端会拒绝写入并提示重新预览。

系统会：

0. 跳过已写入过的记录（除非「含已写入」）
1. 校验飞牛用户
2. 使用 SQLite backup API 备份飞牛数据库
3. 开启事务
4. 更新 / 插入 `item_user_play`
5. 提交
6. 刷新本地 `play_record`
7. 写入本地 `sync_record` 成功标记，防止重复上传

备份文件位于：

```text
DATA_DIR/backups/fntv-YYYYMMDD-HHMMSS-before-writeback.db
```

### 3. 查看结果

页面会显示：

- 更新数量
- 新建数量
- 备份路径

## 快速恢复

在「写入飞牛」页面的「飞牛数据库备份」列表中：

1. 选择备份
2. 点击「恢复」
3. 确认

恢复流程：

1. 先备份当前飞牛数据库（撤销点）
2. 用选定备份覆盖飞牛数据库
3. 执行 WAL checkpoint

恢复前的安全备份：

```text
DATA_DIR/backups/fntv-...-before-restore.db
```

### 恢复注意

- 恢复只覆盖**飞牛数据库**
- FN2Trakt 本地数据库不会回滚
- 恢复后建议在飞牛 App 里确认数据
- 如果飞牛正在播放或扫描，恢复可能被锁阻塞，建议暂停相关操作
- 恢复本身也会写数据库，需要写权限

## 数据规则

### 一条媒体只保留一条飞牛播放记录

飞牛 `item_user_play` 对 `(item_guid, user_guid)` 唯一。

因此同一个媒体有多次 Trakt 观看记录时，只取**最近一次** Trakt 观看时间。

### 匹配规则

只处理：

- Trakt 历史已匹配到飞牛库
- 有 `media_guid`

跳过（不写入）：

- 已经写入过飞牛的历史（`sync_record.action = fntv_writeback` 且成功），除非勾选「含已写入」
- 不在飞牛媒体库的 Trakt 记录
- 飞牛库里没有可播放文件（`item_media` 无 `can_play=1`）的条目

### 字段

| 飞牛字段 | 写入值 |
| --- | --- |
| `item_guid` | 匹配到的电影 / 剧集 |
| `user_guid` | 当前 Trakt 账号绑定的飞牛用户 |
| `ts` | 时长秒数（尽可能 100%） |
| `watched` | `1` |
| `type` | `Movie` / `Episode` |
| `visible` | `1` |
| `media_guid` | 优先从 `item_media` 选择可播放文件 |
| `video_guid` / `audio_guid` / `subtitle_guid` | 从 `media_stream` 选择 |
| `create_time` / `update_time` | Trakt 观看时间（毫秒） |

### 本地防重复

写入成功后：

- 本地会生成本地播放记录
- 会生成一条 `success` 的同步记录，`action=fntv_writeback`
- 下一轮同步不会再次上传这些记录
- 如果配置了 Webhook，会发送 `backfill.completed`（写入飞牛完成）通知

## 常见问题

### 写入按钮是灰的

检查：

- 是否已点「拉取 Trakt 历史」（没有历史时没有可写入记录）
- 是否有可写入记录（匹配成功数量为 0）
- 是否绑定飞牛用户
- 飞牛数据库是否可写

### `attempt to write a readonly database`

主库或目录没有写权限：

```bash
sudo setfacl -m u:1000:rwx /path/to/database
sudo setfacl -m u:1000:rw /path/to/database/trimmedia.db
```

并确认 compose 没有 `:ro`。

### `database is locked`

飞牛正在写入或扫描。稍后重试，或暂停飞牛相关任务。

### 恢复后本地还显示记录

恢复只覆盖飞牛数据库，本地 FN2Trakt 数据不会回滚。

可以在「观看记录」里手动刷新，或在「系统设置」重新读取飞牛数据。

### 会不会写坏飞牛数据库？

写入前一定备份，且使用事务。但这是直接写第三方数据库，仍然有风险：

- 建议先备份
- 不要在飞牛升级 / 扫描时操作
- 写入后先在飞牛 App 抽查
- 出现异常立即用备份恢复

## 安全建议

- 只给管理员使用
- 操作完成后可以收回飞牛数据库写权限
- 定期把 `DATA_DIR/backups` 备份到别处
- 不要把 `DATA_DIR` 暴露到公网
- 不要手动删除备份，除非确认不再需要恢复

## 相关接口

```text
GET  /api/fntv/writeback/preview
POST /api/fntv/writeback/apply
GET  /api/fntv/backups
POST /api/fntv/restore
```

全部需要管理员登录。
