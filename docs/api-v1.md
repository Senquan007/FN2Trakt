# 个人 API（v1）

基址：`http://<host>:8080/api/v1`

所有接口（除 `/health`）使用个人 Bearer Token：

```http
Authorization: Bearer fnt_xxxxxxxxxxxxxxxxx
```

Token 在「开发者 → API Token」创建，完整值只显示一次。权限：

| Scope | 说明 |
| --- | --- |
| `history:read` | 读取观看历史、统计、导出 |
| `library:read` | 读取本地媒体库与播放状态 |
| `history:write` | 从 Trakt 拉取/刷新自己的观看历史 |
| `sync:write` | 触发同步任务（仅管理员） |

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 无需 Token |
| GET | `/me` | 当前用户、Token 权限、Trakt 绑定、历史条数 |
| GET | `/history` | 分页历史；`type=movie\|episode`、`status=matched\|library_only\|not_in_library`、`q`、`from`、`to`、`page`、`page_size`、`order` |
| GET | `/history/recent?limit=10` | 最近观看，适合桌面 Widget / 首页 |
| GET | `/history/stats` | 电影/剧集数量、总时长、月度分布、Top 剧集 |
| GET | `/history/export?format=json\|csv` | 导出当前用户的全部历史 |
| GET | `/library?q=&type=movie\|episode` | 搜索媒体库；返回当前用户是否播放/看完 |
| GET | `/sync/status` | 最近同步任务与同步状态计数 |
| POST | `/sync/run` | 触发一次同步（管理员，`sync:write`） |
| POST | `/history/refresh` | 从 Trakt 拉取全部历史（`history:write`） |

## 示例

```bash
TOKEN="fnt_..."

# 最近 10 条
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/history/recent?limit=10"

# 统计
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/history/stats"

# 导出 CSV
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/history/export?format=csv" -o history.csv

# 搜索媒体库
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/library?q=Example%20Show"
```

历史条目主要字段：

```json
{
  "id": 1,
  "trakt_id": 14624562501,
  "type": "episode",
  "watched_at": "2026-11-11T12:29:00Z",
  "title": "Plan",
  "show_title": "The Long Season",
  "season": 1,
  "episode": 10,
  "match_status": "matched",
  "in_library": true,
  "local_completed": true,
  "media_guid": "...",
  "play_id": 2
}
```

`match_status`：

- `matched`：飞牛库里有这个媒体，并且当前用户有本地播放记录
- `library_only`：飞牛库里有，但当前用户还没有播放记录（回填时会新建一条本地播放记录）
- `not_in_library`：飞牛库里没有（只保存在本地 Trakt 历史镜像中）

分页响应包含 `page`、`page_size`、`total`、`has_more`。错误格式为 `{"detail": "..."}`；无效或撤销的 Token 返回 401。

完整 OpenAPI 文档：<http://localhost:8080/docs>
