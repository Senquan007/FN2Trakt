# 飞牛影视数据库结构

本文记录 FN2Trakt 读取的飞牛影视（trimmedia）SQLite 结构。完整 DDL 见 [fntv-schema.sql](fntv-schema.sql)。

## 位置

飞牛 NAS 默认路径：

```text
/usr/local/apps/@appdata/trim.media/database/trimmedia.db
```

同目录可能还有：

| 文件 | 用途 |
| --- | --- |
| `trimmedia.db` | 主数据库：媒体、用户、播放记录 |
| `trimmedia_ext.db` | 扩展数据（`item_archive` / `person_archive` / `user_data`） |
| `trimactivity.db` | 播放活动 / 转码等活动记录 |

FN2Trakt 只读打开 `trimmedia.db`，使用 SQLite URI `mode=ro`，不会修改飞牛数据。

## 核心表

### `item` — 媒体条目

电影、剧、季、集、目录都在这张表，用 `type` 区分：

| `type` | 含义 |
| --- | --- |
| `Movie` | 电影 |
| `TV` | 电视剧（剧级） |
| `Season` | 季 |
| `Episode` | 单集 |
| `Directory` | 媒体库目录 |
| `Video` | 未识别 / 散落视频 |
| `MediaDB` | 媒体库根节点 |

关键字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `guid` | text | 主键，32 位十六进制 |
| `trim_id` | text | 飞牛内部 ID，如 `tm225008` / `tt1434` |
| `type` | text | 见上表 |
| `title` | text | 标题（剧集为单集标题） |
| `original_title` | text | 原始标题 |
| `parent_guid` | text | 父级（Episode → Season → TV） |
| `season_number` | int | 季号；电影 / 剧级为 0 |
| `episode_number` | int | 集号；电影 / 剧级为 0 |
| `tmdb_id` | int | **剧 / 电影级** TMDB ID（单集行也带所属剧的 TMDB ID） |
| `imdb_id` | text | **剧 / 电影级** IMDB ID，如 `tt27628576` |
| `episode_imdb_id` | text | 单集自己的 IMDB ID |
| `runtime` | int | 时长，**分钟** |
| `release_date` / `first_air_date` | text | 发行 / 首播日期 |
| `overview` | text | 简介 |
| `posters` / `backdrops` | text | 图片相对路径（飞牛私有格式） |
| `update_time` | int | 元数据更新时间（毫秒） |

> 实测样本（2537 个 item）：`Episode` 1892 条中 1883 条有 `tmdb_id`、`imdb_id`，覆盖率约 99.5%；`Movie` 123 条全部有 TMDB ID。因此绝大多数情况下不需要按标题猜。

### `user` — 飞牛用户

| 字段 | 说明 |
| --- | --- |
| `guid` | 用户主键 |
| `username` | 登录名 |
| `is_admin` | 是否管理员 |
| `status` | `0` 禁用 / `1` 启用 |
| `last_login_time` | 毫秒时间戳 |

`default-user-template` 是模板账号，FN2Trakt 会跳过。

### `item_user_play` — 播放记录

| 字段 | 说明 |
| --- | --- |
| `item_guid` | 媒体 GUID |
| `user_guid` | 用户 GUID |
| `ts` | 播放位置，**秒** |
| `watched` | 是否标记已看（0/1） |
| `media_guid` / `video_guid` / `audio_guid` / `subtitle_guid` | 当前播放的媒体文件与流 |
| `resolution` | 分辨率标签，如 `4k` / `1080p` |
| `bitrate` | 码率 |
| `type` | `Movie` / `Episode` / `Video` |
| `visible` | 是否可见（0/1） |
| `create_time` / `update_time` | 毫秒时间戳；`update_time` 是最后播放时间 |

**没有主键**，业务上以 `(item_guid, user_guid)` 唯一。FN2Trakt 在本地库中也使用这个组合去重。

### `media_stream` — 媒体流

当 `item.runtime` 缺失时，FN2Trakt 会用 `media_stream` 中 `codec_type='video'` 的 `duration`（秒）兜底计算进度。

### `item_ancestor` — 祖先关系

该表主要服务于飞牛内部虚拟节点（样本中 `item_guid` 是 `fv_...` 形式，并不总能对应 `item.guid`）。FN2Trakt **不依赖它**，而是通过 `item.parent_guid` 向上遍历，最多 8 层，避免脏数据造成环。

## 层级解析

```text
Episode (season_number, episode_number)
   └── parent_guid → Season
          └── parent_guid → TV     ← 取这里的 tmdb_id / imdb_id / title
```

- 单集行自身也带有 `tmdb_id`，但含义是「所属剧的 TMDB ID」。
- 电影直接取自身 `tmdb_id` / `imdb_id`。
- `Season` 行不参与 Trakt 匹配，只用于校验层级。

## 时间与进度

- `item.runtime`：分钟（例如 22、111）。
- `item_user_play.ts`：秒。
- 进度：`ts / (runtime × 60) × 100`，上限 100%。
- 时间戳：毫秒（13 位）；FN2Trakt 会兼容秒级并统一转为 UTC。

## 已看完判定

```text
completed = watched == 1
          or progress >= threshold   (默认 80%，可在系统设置调整)
```

阈值变化时，FN2Trakt 会立即重算本地 `play_record.completed`，不需要重新读取飞牛数据库。

## Trakt 映射

| 飞牛 | Trakt `POST /sync/history` |
| --- | --- |
| `Movie` + `tmdb_id` | `movies[].ids.tmdb` |
| `Movie` + `imdb_id` | `movies[].ids.imdb` |
| `Episode` + 剧 `tmdb_id` + 季/集号 | `shows[].ids.tmdb` + `seasons[].episodes[]` |
| `Episode` + 剧 `imdb_id` | `shows[].ids.imdb` + `seasons[].episodes[]` |

`watched_at` 使用 `item_user_play.update_time`，格式为 UTC ISO8601（`2026-11-11T12:31:00Z`）。

## 只读与容错

- 连接串：`file:/path/trimmedia.db?mode=ro`，并设置 `timeout=10`。
- 启动时检查 `item` / `user` / `item_user_play` 是否存在，缺失会在设置页给出明确错误。
- 通过 `PRAGMA table_info` 检测列，缺列时降级处理，兼容不同飞牛版本。
- 跳过 `visible=0`、无法关联到 `item` 或 `user` 的记录，并在刷新结果中报告跳过数量。
