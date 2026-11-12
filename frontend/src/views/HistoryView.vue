<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">观看记录</h2>
        <p class="page-sub">来自飞牛影视的播放历史，按最后播放时间排序；点击行查看详情。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Upload" :loading="syncing" @click="runSync(router)">同步到 Trakt</el-button>
      </div>
    </div>

    <div class="summary-strip">
      <div v-for="item in summaryItems" :key="item.key" class="summary-item">
        <span class="summary-dot" :style="{ background: item.color }"></span>
        <div>
          <div class="summary-value">{{ item.value }}</div>
          <div class="summary-label">{{ item.label }}</div>
        </div>
      </div>
    </div>

    <div class="panel">
      <div class="filter-bar">
        <el-radio-group v-model="filters.status" size="default" @change="onFilterChange">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="completed">已看完</el-radio-button>
          <el-radio-button value="pending">待同步</el-radio-button>
          <el-radio-button value="synced">已同步</el-radio-button>
          <el-radio-button value="failed">失败</el-radio-button>
          <el-radio-button value="unmatched">未匹配</el-radio-button>
        </el-radio-group>

        <div class="filter-right">
          <el-select
            v-if="isAdmin"
            v-model="filters.fn_user_guid"
            placeholder="全部用户"
            clearable
            style="width: 150px"
            @change="onFilterChange"
          >
            <el-option v-for="u in users" :key="u.guid" :label="u.username" :value="u.guid" />
          </el-select>
          <el-select v-model="filters.media_type" placeholder="全部类型" clearable style="width: 120px" @change="onFilterChange">
            <el-option label="电影" value="movie" />
            <el-option label="剧集" value="episode" />
          </el-select>
          <el-date-picker
            v-model="filters.range"
            type="daterange"
            unlink-panels
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
            style="width: 240px"
            @change="onFilterChange"
          />
          <el-input
            v-model="filters.query"
            placeholder="搜索标题"
            clearable
            style="width: 190px"
            @keyup.enter="onFilterChange"
            @clear="onFilterChange"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="rows"
        style="width: 100%"
        row-key="id"
        @row-click="openDetail"
      >
        <el-table-column
          label="媒体"
          :width="isMobile ? 140 : undefined"
          :min-width="isMobile ? undefined : 280"
        >
          <template #default="{ row }">
            <div class="media-cell">
              <span class="media-type" :class="{ movie: row.type === 'Movie' }">
                {{ row.type === 'Episode' ? '剧' : row.type === 'Movie' ? '影' : '?' }}
              </span>
              <div style="min-width: 0">
                <div class="media-title">{{ row.display_title }}</div>
                <div class="tiny muted">
                  {{ row.year || '—' }}
                  <span v-if="row.tmdb_id && !isMobile"> · TMDB {{ row.tmdb_id }}</span>
                  <span v-if="row.resolution"> · {{ row.resolution }}</span>
                  <span v-if="isMobile"> · {{ Math.round(row.progress_percent || 0) }}%</span>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column v-if="isAdmin && !isMobile" label="用户" width="110">
          <template #default="{ row }">
            <span class="chip muted">{{ row.username || '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column v-if="!isMobile" label="进度" width="170">
          <template #default="{ row }">
            <div class="progress-cell">
              <div class="flex-between" style="margin-bottom: 4px">
                <span class="tiny" :class="{ muted: !row.completed }">
                  {{ row.completed ? '已看完' : '未看完' }}
                </span>
                <span class="tiny muted">{{ Math.round(row.progress_percent || 0) }}%</span>
              </div>
              <el-progress
                :percentage="Math.min(100, Math.round(row.progress_percent || 0))"
                :stroke-width="6"
                :show-text="false"
                :color="progressColor(row.progress_percent)"
              />
              <div class="tiny muted" style="margin-top: 3px">
                {{ formatSeconds(row.position_seconds) }} / {{ formatSeconds(row.runtime_seconds) }}
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column v-if="!isMobile" label="匹配" width="130">
          <template #default="{ row }">
            <div>
              <span class="chip" :class="matchChipClass(row.match?.status || 'unmatched')">
                {{ MATCH_STATUS[row.match?.status || 'unmatched']?.label }}
              </span>
              <div class="tiny muted ellipsis" style="max-width: 120px; margin-top: 3px">
                {{ row.match?.title || '—' }}
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="同步" :width="isMobile ? 88 : 130">
          <template #default="{ row }">
            <div>
              <span class="chip" :class="syncChipClass(rowState(row))">{{ SYNC_STATUS[rowState(row)]?.label }}</span>
              <div class="tiny muted" style="margin-top: 3px">{{ row.sync?.updated_human || '—' }}</div>
            </div>
          </template>
        </el-table-column>

        <el-table-column v-if="!isMobile" label="最后播放" width="150">
          <template #default="{ row }">
            <div>{{ formatDateTime(row.fn_update_time) }}</div>
            <div class="tiny muted">{{ row.last_play_human }}</div>
          </template>
        </el-table-column>

        <el-table-column label="操作" :width="isMobile ? 120 : 150">
          <template #default="{ row }">
            <div class="row-actions" @click.stop>
              <el-tooltip v-if="canSync(row)" content="上传这一条">
                <el-button text circle :icon="Upload" @click="syncOne(row)" />
              </el-tooltip>
              <el-tooltip v-if="isAdmin" content="手动匹配">
                <el-button text circle :icon="Connection" @click="openMatch(row)" />
              </el-tooltip>
              <el-tooltip content="详情">
                <el-button text circle :icon="View" @click="openDetail(row)" />
              </el-tooltip>
              <el-tooltip v-if="row.trakt_url" content="在 Trakt 打开">
                <el-button text circle :icon="TopRight" tag="a" :href="row.trakt_url" target="_blank" />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="empty">
            <el-icon><Film /></el-icon>
            <div>没有符合条件的记录</div>
          </div>
        </template>
      </el-table>

      <div class="pager">
        <span class="tiny muted">共 {{ total }} 条</span>
        <el-pagination
          v-model:current-page="filters.page"
          v-model:page-size="filters.page_size"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="sizes, prev, pager, next, jumper"
          background
          @change="load"
        />
      </div>
    </div>

    <MatchDialog v-model="matchVisible" :target="matchTarget" @matched="load" />

    <el-drawer append-to-body v-model="detailVisible" size="520px" :title="detail?.display_title || '记录详情'">
      <div v-if="detail">
        <div class="detail-hero">
          <span class="media-type" :class="{ movie: detail.type === 'Movie' }">
            {{ detail.type === 'Episode' ? '剧' : detail.type === 'Movie' ? '影' : '?' }}
          </span>
          <div>
            <div style="font-weight: 700">{{ detail.display_title }}</div>
            <div class="tiny muted">
              {{ detail.year || '—' }} · {{ typeLabel(detail.type) }} · {{ detail.username }}
            </div>
          </div>
          <el-progress
            type="circle"
            :percentage="Math.min(100, Math.round(detail.progress_percent || 0))"
            :width="52"
            :stroke-width="6"
            :color="progressColor(detail.progress_percent)"
          />
        </div>

        <div class="flex" style="gap: 8px; flex-wrap: wrap; margin: 14px 0 18px">
          <span class="chip" :class="matchChipClass(detail.match?.status || 'unmatched')">
            匹配：{{ MATCH_STATUS[detail.match?.status || 'unmatched']?.label }}
          </span>
          <span class="chip" :class="syncChipClass(rowState(detail))">
            同步：{{ SYNC_STATUS[rowState(detail)]?.label }}
          </span>
          <span v-if="detail.resolution" class="chip muted">{{ detail.resolution }}</span>
        </div>

        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="媒体标题">{{ detail.show_title || detail.title }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.type === 'Episode'" label="季 / 集">
            S{{ String(detail.season_number || 0).padStart(2, '0') }}E{{ String(detail.episode_number || 0).padStart(2, '0') }}
          </el-descriptions-item>
          <el-descriptions-item label="播放位置">
            {{ formatSeconds(detail.position_seconds) }} / {{ formatSeconds(detail.runtime_seconds) }}
          </el-descriptions-item>
          <el-descriptions-item label="进度">{{ detail.progress_percent ?? 0 }}%</el-descriptions-item>
          <el-descriptions-item label="飞牛 watched">{{ detail.watched ? 'true' : 'false' }}</el-descriptions-item>
          <el-descriptions-item label="开始播放">{{ formatDateTime(detail.fn_create_time) }}</el-descriptions-item>
          <el-descriptions-item label="最后播放">{{ formatDateTime(detail.fn_update_time) }}</el-descriptions-item>
          <el-descriptions-item label="TMDB">{{ detail.tmdb_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="IMDB">{{ detail.imdb_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="Trakt 匹配">
            {{ detail.match?.title || '未匹配' }}
            <span v-if="detail.match?.source"> · {{ detail.match.source }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="同步时间">{{ formatDateTime(detail.sync?.updated_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.sync?.error" label="同步错误">
            <span style="color: #c53030">{{ detail.sync.error }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <div class="flex mt-16" style="flex-wrap: wrap">
          <el-button v-if="canSync(detail)" size="small" type="primary" :icon="Upload" @click="syncOne(detail)">
            上传这一条
          </el-button>
          <el-button v-if="isAdmin" size="small" :icon="Connection" @click="openMatch(detail)">手动匹配</el-button>
          <el-button v-if="detail.trakt_url" size="small" :icon="TopRight" tag="a" :href="detail.trakt_url" target="_blank">
            在 Trakt 查看
          </el-button>
        </div>

        <div class="mt-24">
          <div class="detail-label">同步请求</div>
          <pre class="code-block">{{ pretty(detail.sync_request) }}</pre>
        </div>
        <div class="mt-16">
          <div class="detail-label">飞牛原始记录</div>
          <pre class="code-block">{{ pretty(detail.raw) }}</pre>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Refresh, Search, TopRight, Upload, View } from '@element-plus/icons-vue'
import api, { errMsg } from '@/api/client'
import MatchDialog from '@/components/MatchDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { useSync } from '@/composables/useSync'
import {
  formatDateTime,
  formatSeconds,
  matchChipClass,
  MATCH_STATUS,
  SYNC_STATUS,
  syncChipClass,
  typeLabel
} from '@/utils/format'

const auth = useAuthStore()
const router = useRouter()
const isAdmin = computed(() => auth.isAdmin)
const isMobile = useMediaQuery('(max-width: 720px)')
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const summary = ref({ total: 0, completed: 0, synced: 0, pending: 0, failed: 0, blocked: 0, unmatched: 0 })
const users = ref([])
const detailVisible = ref(false)
const detail = ref(null)
const matchVisible = ref(false)
const matchTarget = ref(null)
const { syncing, runSync } = useSync()

const filters = reactive({
  status: 'all',
  media_type: '',
  query: '',
  fn_user_guid: '',
  range: null,
  page: 1,
  page_size: 20
})

const summaryItems = computed(() => [
  { key: 'total', label: '全部记录', value: summary.value.total, color: '#2f6feb' },
  { key: 'completed', label: '已看完', value: summary.value.completed, color: '#5b9bff' },
  { key: 'synced', label: '已同步', value: summary.value.synced, color: '#0f9d76' },
  { key: 'pending', label: '待同步', value: summary.value.pending, color: '#b7791f' },
  { key: 'failed', label: '同步失败', value: summary.value.failed, color: '#d14343' },
  { key: 'unmatched', label: '未匹配', value: summary.value.unmatched, color: '#98a2b3' }
])

function rowState(row) {
  if (row.state) return row.state
  if (!row.completed) return 'incomplete'
  if (!row.match || ['unmatched', 'rejected'].includes(row.match.status)) return 'unmatched'
  if (row.sync?.status) return row.sync.status
  return 'pending'
}

function progressColor(value) {
  const percent = Number(value) || 0
  if (percent >= 95) return '#0f9d76'
  if (percent >= 50) return '#2f6feb'
  return '#b7791f'
}

function pretty(value) {
  if (!value) return '—'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function canSync(row) {
  return (
    row.completed &&
    row.match &&
    !['unmatched', 'rejected'].includes(row.match.status) &&
    row.sync?.status !== 'success'
  )
}

async function syncOne(row) {
  try {
    await ElMessageBox.confirm(`将「${row.display_title}」按记录时间写入 Trakt 观看历史？`, '上传单条记录', {
      type: 'info',
      confirmButtonText: '上传'
    })
  } catch {
    return
  }
  try {
    const data = await api.post(`/sync/play/${row.id}`)
    ElMessage.success(data.message || '已上传')
    await load()
    if (detailVisible.value && detail.value?.id === row.id) {
      detail.value = await api.get(`/plays/${row.id}`)
    }
  } catch (error) {
    ElMessage.error(errMsg(error))
  }
}

function onFilterChange() {
  filters.page = 1
  load()
}

async function load() {
  loading.value = true
  try {
    const data = await api.get('/plays', {
      params: {
        page: filters.page,
        page_size: filters.page_size,
        status: filters.status,
        media_type: filters.media_type || undefined,
        query: filters.query || undefined,
        fn_user_guid: filters.fn_user_guid || undefined,
        date_from: filters.range?.[0] || undefined,
        date_to: filters.range?.[1] || undefined
      }
    })
    rows.value = data.items
    total.value = data.total
    summary.value = data.summary
    users.value = data.users || []
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    loading.value = false
  }
}

async function openDetail(row) {
  detailVisible.value = true
  detail.value = row
  try {
    detail.value = await api.get(`/plays/${row.id}`)
  } catch (error) {
    ElMessage.error(errMsg(error))
  }
}

function openMatch(row) {
  matchTarget.value = {
    media_guid: row.match_media_guid || row.item_guid,
    title: row.type === 'Episode' ? row.show_title || row.title : row.title,
    media_type: row.type === 'Movie' ? 'movie' : 'show',
    year: row.year,
    tmdb_id: row.tmdb_id,
    imdb_id: row.imdb_id
  }
  matchVisible.value = true
}

onMounted(load)
</script>

<style scoped>
.summary-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  margin-bottom: 16px;
  padding: 4px 6px;
  border-radius: 14px;
  background: var(--glass);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-sm);
}
.summary-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 12px 16px;
  border-right: 1px solid var(--line);
}
.summary-item:last-child { border-right: none; }
.summary-dot { width: 6px; height: 6px; border-radius: 50%; flex: none; }
.summary-value { font-size: 18px; font-weight: 700; line-height: 1.2; color: var(--ink-strong); }
.summary-label { font-size: 11px; color: var(--muted); margin-top: 1px; }
@media (max-width: 1100px) {
  .summary-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .summary-item:nth-child(3n) { border-right: none; }
  .summary-item:nth-child(-n + 3) { border-bottom: 1px solid var(--line); }
}
@media (max-width: 560px) {
  .summary-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-item { border-right: none; border-bottom: 1px solid var(--line); padding: 10px 12px; }
  .summary-item:nth-last-child(-n + 2) { border-bottom: none; }
  .summary-item:nth-child(3n) { border-right: none; }
}

.filter-bar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}
.filter-right { display: flex; gap: 10px; flex-wrap: wrap; }

.media-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.media-type {
  flex: none;
  width: 28px;
  height: 28px;
  border: 1px solid color-mix(in srgb, var(--primary) 12%, transparent);
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-soft);
}
.media-type.movie { color: var(--primary-deep); background: var(--primary-soft); }
.media-title { font-weight: 600; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-actions { display: flex; gap: 2px; }
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
  flex-wrap: wrap;
}
.detail-hero { display: flex; align-items: center; gap: 12px; }
.detail-hero .media-type { width: 40px; height: 40px; font-size: 13px; }
.detail-label { font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 6px; }
@media (max-width: 720px) {
  .filter-bar { padding: 12px; gap: 10px; }
  .filter-bar :deep(.el-radio-group) { width: 100%; }
  .filter-bar :deep(.el-radio-button__inner) { padding: 6px 7px; font-size: 11.5px; }
  .filter-right { width: 100%; }
  .filter-right > * { width: 100% !important; }
  .filter-right > .el-select { width: calc(50% - 5px) !important; }
  .row-actions :deep(.el-button) { width: 27px; height: 27px; }
  .pager { padding: 10px 12px; }
  .pager :deep(.el-pagination) { max-width: 100%; flex-wrap: wrap; row-gap: 6px; }
  .pager :deep(.el-pagination__sizes),
  .pager :deep(.el-pagination__jump) { display: none; }
}
.code-block {
  background: linear-gradient(160deg, #0b1220, #101a2c);
  color: #cbd5e1;
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 11.5px;
  line-height: 1.6;
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
