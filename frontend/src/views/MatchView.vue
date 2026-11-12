<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">媒体匹配</h2>
        <p class="page-sub">把飞牛条目映射到 Trakt。优先使用 TMDB / IMDB ID，失败时按标题搜索或手动指定。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="MagicStick" :loading="rematching" @click="rematch">重新自动匹配</el-button>
      </div>
    </div>

    <div class="match-summary">
      <div v-for="item in summaryCards" :key="item.status" class="ms-card" :class="{ active: filters.status === item.status }" @click="changeStatus(item.status)">
        <div class="ms-value">{{ item.value }}</div>
        <div class="ms-label">{{ item.label }}</div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head" style="padding-bottom: 14px">
        <div>
          <h3 class="panel-title"><el-icon><Connection /></el-icon> 需要处理的媒体</h3>
          <p class="panel-desc">按该媒体下的已看完记录数排序</p>
        </div>
        <el-input v-model="keyword" placeholder="过滤标题" clearable style="width: 220px">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>

      <el-table v-loading="loading" :data="filtered" style="width: 100%">
        <el-table-column label="媒体" min-width="280">
          <template #default="{ row }">
            <div class="media-cell">
              <span class="media-type" :class="{ movie: row.media_type === 'movie' }">
                {{ row.media_type === 'movie' ? '影' : '剧' }}
              </span>
              <div style="min-width: 0">
                <div class="media-title">{{ row.title }}</div>
                <div class="tiny muted">
                  {{ row.year || '—' }}
                  <span v-if="row.tmdb_id"> · TMDB {{ row.tmdb_id }}</span>
                  <span v-if="row.imdb_id"> · IMDB {{ row.imdb_id }}</span>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="已看完" width="90">
          <template #default="{ row }"><b>{{ row.count }}</b> 条</template>
        </el-table-column>
        <el-table-column label="匹配状态" width="120">
          <template #default="{ row }">
            <span class="chip" :class="matchChipClass(row.match.status)">
              {{ MATCH_STATUS[row.match.status]?.label || row.match.status }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="Trakt 条目" min-width="200">
          <template #default="{ row }">
            <div v-if="row.match.title">
              {{ row.match.title }}
              <span v-if="row.match.year" class="muted">({{ row.match.year }})</span>
              <div class="tiny muted">{{ row.match.source === 'id' ? '按外部 ID 匹配' : row.match.source === 'search' ? '按标题自动匹配' : '手动指定' }}</div>
            </div>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="openMatch(row)">手动匹配</el-button>
            <el-button size="small" text type="danger" @click="reject(row)">忽略</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty">
            <el-icon><CircleCheck /></el-icon>
            <div>这里空空如也，所有媒体都已匹配</div>
          </div>
        </template>
      </el-table>
    </div>

    <MatchDialog v-model="matchVisible" :target="matchTarget" @matched="load" />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, MagicStick, Refresh, Search } from '@element-plus/icons-vue'
import api, { errMsg } from '@/api/client'
import MatchDialog from '@/components/MatchDialog.vue'
import { matchChipClass, MATCH_STATUS } from '@/utils/format'

const loading = ref(false)
const rematching = ref(false)
const items = ref([])
const summary = ref({ unmatched: 0, auto: 0, manual: 0, rejected: 0 })
const keyword = ref('')
const matchVisible = ref(false)
const matchTarget = ref(null)
const filters = reactive({ status: 'unmatched' })

const summaryCards = computed(() => [
  { status: 'unmatched', label: '未匹配', value: summary.value.unmatched },
  { status: 'auto', label: '自动匹配', value: summary.value.auto },
  { status: 'manual', label: '手动匹配', value: summary.value.manual },
  { status: 'rejected', label: '已忽略', value: summary.value.rejected },
  { status: 'all', label: '全部', value: summary.value.unmatched + summary.value.auto + summary.value.manual + summary.value.rejected }
])

const filtered = computed(() => {
  if (!keyword.value.trim()) return items.value
  const needle = keyword.value.trim().toLowerCase()
  return items.value.filter((item) => (item.title || '').toLowerCase().includes(needle))
})

function changeStatus(status) {
  filters.status = status
  load()
}

async function load() {
  loading.value = true
  try {
    const data = await api.get('/media/targets', { params: { status: filters.status } })
    items.value = data.items
    summary.value = data.summary
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    loading.value = false
  }
}

async function rematch() {
  rematching.value = true
  try {
    const data = await api.post('/media/rematch')
    ElMessage.success(`自动匹配完成：${data.by_id} 个按 ID，${data.by_search} 个按标题，${data.unmatched} 个待处理`)
    await load()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    rematching.value = false
  }
}

function openMatch(row) {
  matchTarget.value = {
    media_guid: row.media_guid,
    title: row.title,
    media_type: row.media_type,
    year: row.year,
    tmdb_id: row.tmdb_id,
    imdb_id: row.imdb_id
  }
  matchVisible.value = true
}

async function reject(row) {
  try {
    await api.post('/media/reject', { media_guid: row.media_guid })
    ElMessage.success('已忽略')
    await load()
  } catch (error) {
    ElMessage.error(errMsg(error))
  }
}

onMounted(load)
</script>

<style scoped>
.match-summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
@media (max-width: 900px) { .match-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.ms-card {
  padding: 15px 17px;
  border-radius: 18px;
  background: var(--glass);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-sm), var(--shadow-inset);
  backdrop-filter: blur(16px);
  cursor: pointer;
  transition: all 0.18s ease;
}
.ms-card:hover { border-color: color-mix(in srgb, var(--primary) 32%, transparent); transform: translateY(-1px); }
.ms-card.active { border-color: color-mix(in srgb, var(--primary) 55%, transparent); box-shadow: 0 0 0 3px var(--primary-soft), var(--shadow-sm); }
.ms-value { font-size: 22px; font-weight: 750; color: var(--ink-strong); }
.ms-label { font-size: 12px; color: var(--muted); margin-top: 2px; }
.media-cell { display: flex; align-items: center; gap: 10px; }
.media-type {
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-soft);
}
.media-type.movie { color: var(--warning-ink); background: var(--warning-soft); }
.media-title { font-weight: 620; font-size: 13.5px; }
</style>
