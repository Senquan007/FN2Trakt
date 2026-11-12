<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">同步记录</h2>
        <p class="page-sub">查看每次同步任务的结果，以及单条记录的失败原因并重试。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="refresh">刷新</el-button>
        <el-button type="primary" :icon="Upload" :loading="syncing" @click="runSync(router)">立即同步</el-button>
      </div>
    </div>

    <el-tabs v-model="tab" class="logs-tabs" @tab-change="onTabChange">
      <el-tab-pane label="同步任务" name="runs">
        <div class="panel">
          <el-table v-loading="loading" :data="runs" style="width: 100%">
            <el-table-column label="#" prop="id" width="70" />
            <el-table-column label="用户" width="110">
              <template #default="{ row }">{{ row.username || '—' }}</template>
            </el-table-column>
            <el-table-column label="触发" width="90">
              <template #default="{ row }">
                <span class="chip muted">{{ triggerLabel(row.trigger) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <span class="chip" :class="syncChipClass(row.status)">{{ SYNC_STATUS[row.status]?.label || row.status }}</span>
              </template>
            </el-table-column>
            <el-table-column label="扫描 / 已看" width="110">
              <template #default="{ row }">{{ row.scanned }} / {{ row.completed }}</template>
            </el-table-column>
            <el-table-column label="上传 / 失败" width="110">
              <template #default="{ row }">
                <span style="color: #0b8a62; font-weight: 650">+{{ row.uploaded }}</span>
                <span class="muted"> / </span>
                <span :style="{ color: row.failed ? '#c53030' : 'inherit' }">{{ row.failed }}</span>
              </template>
            </el-table-column>
            <el-table-column label="开始时间" width="160">
              <template #default="{ row }">{{ formatDateTime(row.started_at) }}</template>
            </el-table-column>
            <el-table-column label="耗时" width="90">
              <template #default="{ row }">{{ row.duration_seconds != null ? row.duration_seconds.toFixed(1) + 's' : '—' }}</template>
            </el-table-column>
            <el-table-column label="信息" min-width="220">
              <template #default="{ row }"><span class="tiny muted">{{ row.message || '—' }}</span></template>
            </el-table-column>
            <template #empty>
              <div class="empty"><el-icon><Refresh /></el-icon><div>还没有同步任务</div></div>
            </template>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="条目记录" name="records">
        <div class="panel">
          <div class="filter-bar">
            <el-radio-group v-model="recordStatus" @change="loadRecords">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button value="success">成功</el-radio-button>
              <el-radio-button value="failed">失败</el-radio-button>
              <el-radio-button value="blocked">待匹配</el-radio-button>
              <el-radio-button value="pending">待上传</el-radio-button>
            </el-radio-group>
            <span class="tiny muted">共 {{ recordTotal }} 条</span>
          </div>
          <el-table v-loading="loading" :data="records" style="width: 100%">
            <el-table-column label="媒体" min-width="260">
              <template #default="{ row }">
                <div style="font-weight: 600">{{ row.title }}</div>
                <div class="tiny muted">{{ row.username || '—' }} → @{{ row.trakt_username || '—' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <span class="chip" :class="syncChipClass(row.status)">{{ SYNC_STATUS[row.status]?.label || row.status }}</span>
              </template>
            </el-table-column>
            <el-table-column label="观看时间" width="160">
              <template #default="{ row }">{{ formatDateTime(row.watched_at) }}</template>
            </el-table-column>
            <el-table-column label="尝试" width="70" prop="attempts" />
            <el-table-column label="更新时间" width="150">
              <template #default="{ row }">{{ row.updated_human || '—' }}</template>
            </el-table-column>
            <el-table-column label="错误" min-width="220">
              <template #default="{ row }">
                <span class="tiny" :style="{ color: row.error ? '#c53030' : '#94a3b8' }">{{ row.error || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button v-if="row.status !== 'success'" size="small" type="primary" plain @click="retry(row)">重试</el-button>
                <span v-else class="tiny muted">—</span>
              </template>
            </el-table-column>
            <template #empty>
              <div class="empty"><el-icon><Document /></el-icon><div>没有条目记录</div></div>
            </template>
          </el-table>
          <div class="pager">
            <span class="tiny muted">第 {{ recordPage }} 页</span>
            <el-pagination
              v-model:current-page="recordPage"
              :page-size="20"
              :total="recordTotal"
              layout="prev, pager, next"
              background
              @current-change="loadRecords"
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, Upload } from '@element-plus/icons-vue'
import api, { errMsg } from '@/api/client'
import { useSync } from '@/composables/useSync'
import { formatDateTime, SYNC_STATUS, syncChipClass } from '@/utils/format'

const router = useRouter()
const tab = ref('runs')
const loading = ref(false)
const runs = ref([])
const records = ref([])
const recordStatus = ref('')
const recordPage = ref(1)
const recordTotal = ref(0)
const { syncing, runSync } = useSync()
let timer = null

function triggerLabel(trigger) {
  return { manual: '手动', scheduled: '定时', retry: '重试' }[trigger] || trigger
}

async function loadRuns() {
  loading.value = true
  try {
    const data = await api.get('/sync/runs', { params: { page: 1, page_size: 50 } })
    runs.value = data.items
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    loading.value = false
  }
}

async function loadRecords() {
  loading.value = true
  try {
    const data = await api.get('/sync/records', {
      params: { page: recordPage.value, page_size: 20, status: recordStatus.value || undefined }
    })
    records.value = data.items
    recordTotal.value = data.total
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    loading.value = false
  }
}

async function refresh() {
  if (tab.value === 'runs') await loadRuns()
  else await loadRecords()
}

function onTabChange() {
  refresh()
}

async function retry(row) {
  try {
    await api.post(`/sync/records/${row.id}/retry`)
    ElMessage.success('已加入重试队列')
    setTimeout(refresh, 1200)
  } catch (error) {
    ElMessage.error(errMsg(error))
  }
}

onMounted(() => {
  loadRuns()
  timer = setInterval(() => {
    if (runs.value.some((run) => ['running', 'queued'].includes(run.status))) {
      if (tab.value === 'runs') loadRuns()
    }
  }, 5000)
})

onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.logs-tabs :deep(.el-tabs__header) { margin-bottom: 16px; }
.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
  flex-wrap: wrap;
}
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-top: 1px solid var(--line);
}
</style>
