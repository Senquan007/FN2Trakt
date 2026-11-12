<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">仪表盘</h2>
        <p class="page-sub">
          飞牛观影数据概览与 Trakt 同步状态
          <span v-if="data?.fn_users"> · 当前账号 {{ data.fn_users }}</span>
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Upload" :loading="syncing" @click="runSync(router)">立即同步</el-button>
      </div>
    </div>

    <div v-if="notice" class="notice">
      <div class="notice-icon">
        <el-icon><component :is="notice.icon" /></el-icon>
      </div>
      <div class="notice-body">
        <div class="notice-title">{{ notice.title }}</div>
        <div class="notice-desc">{{ notice.desc }}</div>
      </div>
      <el-button size="small" :type="notice.primary ? 'primary' : 'default'" @click="router.push(notice.to)">
        {{ notice.action }}
      </el-button>
    </div>

    <div class="stat-grid">
      <article class="stat">
        <div class="stat-icon"><el-icon><VideoPlay /></el-icon></div>
        <div class="stat-label">播放记录</div>
        <div class="stat-value">{{ stats.total_plays }}</div>
        <div class="stat-foot">来自飞牛影视数据库</div>
      </article>
      <article class="stat">
        <div class="stat-icon"><el-icon><CircleCheck /></el-icon></div>
        <div class="stat-label">已看完</div>
        <div class="stat-value">{{ stats.completed }}</div>
        <div class="stat-foot">watched=1 或进度达标</div>
      </article>
      <article class="stat">
        <div class="stat-icon"><el-icon><UploadFilled /></el-icon></div>
        <div class="stat-label">已同步到 Trakt</div>
        <div class="stat-value">{{ stats.synced }}</div>
        <div class="stat-foot">历史记录写入成功</div>
      </article>
      <article class="stat">
        <div class="stat-icon"><el-icon><Clock /></el-icon></div>
        <div class="stat-label">待处理</div>
        <div class="stat-value">{{ stats.pending + stats.blocked }}</div>
        <div class="stat-foot">未匹配 {{ stats.unmatched }} · 失败 {{ stats.failed }}</div>
      </article>
    </div>

    <div class="dash-row row-types">
      <article class="panel type-card">
        <div class="panel-head type-head">
          <div class="type-title-wrap">
            <span class="type-icon movie"><el-icon><Film /></el-icon></span>
            <div>
              <h3 class="panel-title">电影</h3>
              <p class="panel-desc">Movies</p>
            </div>
          </div>
          <span class="chip info">{{ typeStats.movie.synced }} 已同步</span>
        </div>
        <div class="type-body">
          <div class="type-number">
            <b>{{ typeStats.movie.items }}</b>
            <span>部电影</span>
          </div>
          <div class="type-metrics">
            <div><b>{{ typeStats.movie.plays }}</b><span>播放记录</span></div>
            <div><b>{{ typeStats.movie.completed }}</b><span>已看完</span></div>
            <div><b>{{ typeStats.movie.synced }}</b><span>已同步</span></div>
          </div>
          <div class="type-foot">
            <div class="type-bar"><span :style="{ width: moviePercent + '%' }"></span></div>
            <div class="tiny muted">同步覆盖 {{ moviePercent }}%</div>
          </div>
        </div>
      </article>

      <article class="panel type-card">
        <div class="panel-head type-head">
          <div class="type-title-wrap">
            <span class="type-icon show"><el-icon><VideoCamera /></el-icon></span>
            <div>
              <h3 class="panel-title">剧集</h3>
              <p class="panel-desc">TV Shows</p>
            </div>
          </div>
          <span class="chip info">{{ typeStats.episode.synced }} 已同步</span>
        </div>
        <div class="type-body">
          <div class="type-number">
            <b>{{ typeStats.episode.shows }}</b>
            <span>部剧集 · 共 {{ typeStats.episode.episodes }} 集</span>
          </div>
          <div class="type-metrics">
            <div><b>{{ typeStats.episode.plays }}</b><span>播放记录</span></div>
            <div><b>{{ typeStats.episode.completed }}</b><span>已看完</span></div>
            <div><b>{{ typeStats.episode.synced }}</b><span>已同步</span></div>
          </div>
          <div class="type-foot">
            <div class="type-bar"><span :style="{ width: showPercent + '%' }"></span></div>
            <div class="tiny muted">同步覆盖 {{ showPercent }}%</div>
          </div>
        </div>
      </article>

      <section class="panel top-card">
        <div class="panel-head">
          <div>
            <h3 class="panel-title"><el-icon><Trophy /></el-icon> 看得最多的剧</h3>
            <p class="panel-desc">按已看完的集数排序</p>
          </div>
        </div>
        <div class="top-list">
          <div v-if="!topRows.length" class="empty" style="padding: 30px 10px">暂无数据</div>
          <div v-for="(show, index) in topRows" :key="show.title" class="top-row">
            <span class="rank" :class="{ top: index < 3 }">{{ index + 1 }}</span>
            <div class="top-main">
              <div class="flex-between">
                <span class="top-name ellipsis">{{ show.title }}</span>
                <span class="tiny muted nowrap">{{ show.count }} 集</span>
              </div>
              <div class="rank-bar">
                <span :style="{ width: (show.count / topRows[0].count) * 100 + '%' }"></span>
              </div>
            </div>
          </div>
        </div>
        <div class="top-foot">
          <span class="tiny muted">共 {{ typeStats.episode.shows }} 部剧集</span>
          <el-button text type="primary" size="small" @click="router.push('/history')">查看全部</el-button>
        </div>
      </section>
    </div>

    <div class="dash-row row-chart">
      <section class="panel trend-card">
        <div class="panel-head">
          <div>
            <h3 class="panel-title"><el-icon><TrendCharts /></el-icon> 最近 30 天观看趋势</h3>
            <p class="panel-desc">按飞牛记录的最后播放时间统计</p>
          </div>
          <span class="chip">共 {{ stats.total_plays }} 条</span>
        </div>
        <div class="trend-pad">
          <EChart :option="trendOption" height="252px" />
        </div>
      </section>

      <section class="panel status-card">
        <div class="panel-head">
          <div>
            <h3 class="panel-title"><el-icon><PieChart /></el-icon> 同步状态分布</h3>
            <p class="panel-desc">仅统计已看完的记录</p>
          </div>
        </div>
        <div class="status-pad">
          <EChart v-if="statusTotal > 0" :option="donutOption" height="212px" />
          <div v-else class="empty" style="padding: 30px 10px">
            <el-icon><DataAnalysis /></el-icon>
            <div>暂无已看完的记录</div>
          </div>
        </div>
      </section>
    </div>

    <div class="dash-row row-bottom">
      <section class="panel recent-card">
        <div class="panel-head">
          <div>
            <h3 class="panel-title"><el-icon><Film /></el-icon> 最近观看</h3>
            <p class="panel-desc">最新完成的播放记录</p>
          </div>
          <el-button text type="primary" @click="router.push('/history')">查看全部</el-button>
        </div>
        <el-table :data="recentRows" style="width: 100%" @row-click="() => router.push('/history')">
          <el-table-column label="媒体" :min-width="isMobile ? 150 : 260">
            <template #default="{ row }">
              <div class="media-cell">
                <span class="media-type">{{ row.type === 'Episode' ? '剧' : '影' }}</span>
                <div style="min-width: 0">
                  <div class="media-title ellipsis">{{ row.title }}</div>
                  <div class="tiny muted">{{ row.watched_human }}</div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="!isMobile" label="进度" width="150">
            <template #default="{ row }">
              <div class="progress-wrap">
                <el-progress
                  :percentage="Math.round(row.progress || 0)"
                  :stroke-width="5"
                  :show-text="false"
                  :color="progressColor(row.progress)"
                />
                <span class="tiny muted nowrap">{{ Math.round(row.progress || 0) }}%</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="!isMobile" label="匹配" width="92">
            <template #default="{ row }">
              <span class="chip" :class="matchChipClass(row.match_status)">
                {{ MATCH_STATUS[row.match_status]?.label || row.match_status }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="同步" :width="isMobile ? 96 : 92">
            <template #default="{ row }">
              <span class="chip" :class="syncChipClass(row.sync_status)">
                {{ SYNC_STATUS[row.sync_status]?.label || row.sync_status }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="panel runs-card">
        <div class="panel-head">
          <div>
            <h3 class="panel-title"><el-icon><Refresh /></el-icon> 最近同步</h3>
            <p class="panel-desc">后台任务执行记录</p>
          </div>
          <el-button text type="primary" @click="router.push('/logs')">全部</el-button>
        </div>
        <div class="run-list">
          <div v-if="!runs.length" class="empty" style="padding: 30px 10px">还没有同步记录</div>
          <div v-for="run in runs" :key="run.id" class="run-row">
            <span class="chip" :class="syncChipClass(run.status)">
              {{ SYNC_STATUS[run.status]?.label || run.status }}
            </span>
            <div class="run-main">
              <div class="tiny ellipsis">{{ run.message || '同步任务' }}</div>
              <div class="tiny muted">{{ formatDateTime(run.started_at) }}</div>
            </div>
            <span class="tiny muted nowrap">+{{ run.uploaded }}</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Clock, InfoFilled, Link, Refresh, Upload } from '@element-plus/icons-vue'
import api, { errMsg } from '@/api/client'
import EChart from '@/components/EChart.vue'
import { formatDateTime, matchChipClass, MATCH_STATUS, SYNC_STATUS, syncChipClass } from '@/utils/format'
import { useSync } from '@/composables/useSync'
import { useAuthStore } from '@/stores/auth'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { useThemeStore } from '@/stores/theme'

const router = useRouter()
const auth = useAuthStore()
const theme = useThemeStore()
const isMobile = useMediaQuery('(max-width: 720px)')
const loading = ref(false)
const data = ref(null)
const account = ref(null)
const accountLoaded = ref(false)
const { syncing, runSync } = useSync()

const stats = computed(
  () => data.value?.stats || { total_plays: 0, completed: 0, synced: 0, pending: 0, failed: 0, blocked: 0, unmatched: 0 }
)
const recent = computed(() => data.value?.recent || [])
const recentRows = computed(() => recent.value.slice(0, 6))
const topShows = computed(() => data.value?.top_shows || [])
const topRows = computed(() => topShows.value.slice(0, 5))
const runs = computed(() => (data.value?.runs || []).slice(0, 6))
const statusTotal = computed(() => (data.value?.status_distribution || []).reduce((sum, item) => sum + item.count, 0))
const typeStats = computed(
  () =>
    data.value?.type_stats || {
      movie: { plays: 0, completed: 0, synced: 0, items: 0 },
      episode: { plays: 0, completed: 0, synced: 0, episodes: 0, shows: 0 }
    }
)

const notice = computed(() => {
  if (loading.value) return null
  if (!data.value && !accountLoaded.value) return null
  if (stats.value.total_plays === 0 && auth.isAdmin) {
    return {
      icon: InfoFilled,
      title: '还没有读取飞牛数据',
      desc: '请确认飞牛数据库路径，并在系统设置中重新读取。',
      action: '去设置',
      to: '/settings',
      primary: false
    }
  }
  if (accountLoaded.value && !account.value) {
    return {
      icon: Link,
      title: '还没有绑定 Trakt 账号',
      desc: '观看记录会先保存在本地，绑定后即可一键上传。',
      action: '去绑定',
      to: '/trakt',
      primary: true
    }
  }
  return null
})

function typePercent(kind) {
  const row = typeStats.value[kind]
  if (!row.completed) return 0
  return Math.min(100, Math.round((row.synced / row.completed) * 100))
}

const moviePercent = computed(() => typePercent('movie'))
const showPercent = computed(() => typePercent('episode'))

const chartPalette = computed(() =>
  theme.isDark
    ? {
        primary: '#5b9bff',
        primary2: '#8dbaff',
        success: '#3ecf9a',
        warning: '#e0b05f',
        danger: '#ef7d7d',
        muted: '#8b98ab',
        line: 'rgba(255,255,255,0.08)',
        ink: '#f3f6fb',
        pieBorder: '#141a24'
      }
    : {
        primary: '#2f6feb',
        primary2: '#7aa7ff',
        success: '#0f9d76',
        warning: '#b7791f',
        danger: '#d14343',
        muted: '#8a94a6',
        line: 'rgba(17,24,39,0.07)',
        ink: '#0d1420',
        pieBorder: '#ffffff'
      }
)

function progressColor(value) {
  const percent = Number(value) || 0
  if (percent >= 95) return chartPalette.value.success
  if (percent >= 50) return chartPalette.value.primary
  return chartPalette.value.warning
}

const trendOption = computed(() => {
  const trend = data.value?.trend || []
  const palette = chartPalette.value
  return {
    grid: { left: 4, right: 10, top: 14, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.isDark ? '#1c2634' : '#0f172a',
      borderWidth: 0,
      padding: [8, 10],
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params) => `${params[0].axisValue}<br/>观看 ${params[0].value} 条`
    },
    xAxis: {
      type: 'category',
      data: trend.map((item) => item.date.slice(5)),
      axisLine: { lineStyle: { color: palette.line } },
      axisTick: { show: false },
      axisLabel: { color: palette.muted, fontSize: 10, interval: 4 }
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: palette.line, type: 'dashed' } },
      axisLabel: { color: palette.muted, fontSize: 10 }
    },
    series: [
      {
        type: 'bar',
        data: trend.map((item) => item.count),
        barMaxWidth: 14,
        itemStyle: {
          borderRadius: [4, 4, 0, 0],
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: palette.primary },
              { offset: 1, color: palette.primary2 }
            ]
          }
        }
      }
    ]
  }
})

const donutOption = computed(() => {
  const dist = data.value?.status_distribution || []
  const palette = chartPalette.value
  const colors = {
    success: palette.success,
    failed: palette.danger,
    pending: palette.primary2,
    blocked: palette.muted
  }
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: {
      bottom: 0,
      icon: 'circle',
      itemWidth: 7,
      itemHeight: 7,
      itemGap: 14,
      textStyle: { fontSize: 11, color: palette.muted }
    },
    series: [
      {
        type: 'pie',
        radius: ['58%', '80%'],
        center: ['50%', '43%'],
        avoidLabelOverlap: true,
        label: { show: false },
        itemStyle: { borderColor: palette.pieBorder, borderWidth: 3, borderRadius: 4 },
        data: dist.map((item) => ({
          name: SYNC_STATUS[item.status]?.label || item.status,
          value: item.count,
          itemStyle: { color: colors[item.status] || palette.muted }
        }))
      }
    ],
    graphic: [
      {
        type: 'text',
        left: 'center',
        top: '34%',
        style: { text: String(statusTotal.value), fontSize: 24, fontWeight: 700, fill: palette.ink, textAlign: 'center' }
      },
      {
        type: 'text',
        left: 'center',
        top: '47%',
        style: { text: '已看完', fontSize: 11, fill: palette.muted, textAlign: 'center' }
      }
    ]
  }
})

async function load() {
  loading.value = true
  try {
    data.value = await api.get('/dashboard')
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    loading.value = false
  }
}

async function loadAccount() {
  try {
    const result = await api.get('/trakt/account')
    account.value = result.account
  } finally {
    accountLoaded.value = true
  }
}

onMounted(() => {
  load()
  loadAccount()
})
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.dash-row {
  display: grid;
  gap: 16px;
  margin-top: 16px;
}
.row-types { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr); }
.row-chart { grid-template-columns: minmax(0, 1.72fr) minmax(0, 1fr); }
.row-bottom { grid-template-columns: minmax(0, 1.72fr) minmax(0, 1fr); }

.notice {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 14px;
  background:
    linear-gradient(100deg, rgba(47, 111, 235, 0.06), rgba(47, 111, 235, 0) 46%),
    var(--glass);
  border: 1px solid color-mix(in srgb, var(--primary) 14%, var(--glass-border));
  box-shadow: var(--shadow-sm);
}
.notice-icon {
  width: 34px;
  height: 34px;
  flex: none;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 16px;
}
.notice-body { flex: 1; min-width: 0; }
.notice-title { font-size: 13.5px; font-weight: 650; color: var(--ink-strong); }
.notice-desc { font-size: 12px; color: var(--muted); margin-top: 2px; }

.type-card { display: flex; flex-direction: column; overflow: hidden; }
.type-head { padding: 18px 18px 0; align-items: flex-start; }
.type-title-wrap { display: flex; align-items: center; gap: 10px; }
.type-icon {
  width: 36px;
  height: 36px;
  flex: none;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 17px;
  color: var(--primary);
  background: var(--primary-soft);
  border: 1px solid color-mix(in srgb, var(--primary) 12%, transparent);
}
.type-icon.show { color: var(--primary-deep); }
.type-body {
  padding: 14px 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex: 1;
}
.type-number { display: flex; align-items: baseline; gap: 7px; min-height: 44px; }
.type-number b {
  font-size: 38px;
  font-weight: 750;
  letter-spacing: -0.05em;
  line-height: 1;
  color: var(--ink-strong);
}
.type-number span { font-size: 12px; color: var(--muted); }
.type-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
.type-metrics div { display: flex; flex-direction: column; gap: 2px; }
.type-metrics b { font-size: 15px; font-weight: 650; color: var(--ink-strong); line-height: 1.2; }
.type-metrics span { font-size: 11px; color: var(--muted); }
.type-foot { margin-top: auto; }
.type-bar { height: 4px; border-radius: 99px; background: var(--line); overflow: hidden; margin-bottom: 6px; }
.type-bar span {
  display: block;
  height: 100%;
  border-radius: 99px;
  background: linear-gradient(90deg, var(--primary-2), var(--primary));
  transition: width 0.4s ease;
}

.status-card { display: flex; flex-direction: column; overflow: hidden; }
.status-pad { flex: 1; display: flex; align-items: center; justify-content: center; padding: 2px 10px 6px; }

.trend-card { overflow: hidden; }
.trend-pad { padding: 10px 16px 14px; }

.top-card { display: flex; flex-direction: column; overflow: hidden; }
.top-list {
  display: flex;
  flex-direction: column;
  justify-content: center;
  flex: 1;
  padding: 4px 18px;
}
.top-row { display: flex; align-items: center; gap: 10px; min-height: 54px; padding: 6px 0; }
.top-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 18px;
  border-top: 1px solid var(--line);
}
.rank {
  width: 20px;
  height: 20px;
  flex: none;
  border-radius: 6px;
  display: grid;
  place-items: center;
  font-size: 10.5px;
  font-weight: 700;
  color: var(--muted);
  background: var(--glass-soft);
  border: 1px solid var(--glass-border);
}
.rank.top { color: var(--primary); background: var(--primary-soft); border-color: color-mix(in srgb, var(--primary) 16%, transparent); }
.top-main { flex: 1; min-width: 0; }
.top-name { font-size: 13px; font-weight: 600; color: var(--ink); max-width: 72%; }
.rank-bar { height: 4px; background: var(--line); border-radius: 99px; margin-top: 6px; overflow: hidden; }
.rank-bar span {
  display: block;
  height: 100%;
  border-radius: 99px;
  background: linear-gradient(90deg, var(--primary), var(--primary-2));
}

.recent-card { overflow: hidden; }
.recent-card :deep(.el-table .cell) { padding-left: 12px; padding-right: 12px; }
.recent-card :deep(.el-table th:first-child .cell),
.recent-card :deep(.el-table td:first-child .cell) { padding-left: 20px; }
.recent-card :deep(.el-table th:last-child .cell),
.recent-card :deep(.el-table td:last-child .cell) { padding-right: 20px; }
.media-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.media-type {
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-soft);
}
.media-title { font-size: 13px; font-weight: 600; }
.ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.progress-wrap { display: flex; align-items: center; gap: 8px; }
.progress-wrap :deep(.el-progress) { flex: 1; }

.runs-card { display: flex; flex-direction: column; overflow: hidden; }
.run-list { display: flex; flex-direction: column; flex: 1; padding: 8px 18px 12px; }
.run-row {
  display: flex;
  align-items: center;
  gap: 9px;
  flex: 1;
  min-height: 40px;
  padding: 4px 0;
  border-bottom: 1px dashed var(--line);
}
.run-row:last-child { border-bottom: none; }
.run-main { flex: 1; min-width: 0; }

@media (max-width: 1180px) {
  .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .row-types { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  .row-types .top-card { grid-column: 1 / -1; }
  .row-chart { grid-template-columns: minmax(0, 1fr); }
  .row-bottom { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 720px) {
  .stat-grid { gap: 10px; }
  .recent-card :deep(.el-table .cell) { padding-left: 8px; padding-right: 8px; }
  .recent-card :deep(.el-table td:first-child .cell),
  .recent-card :deep(.el-table th:first-child .cell) { padding-left: 16px; }
  .recent-card :deep(.el-table td:last-child .cell),
  .recent-card :deep(.el-table th:last-child .cell) { padding-right: 12px; }
  .dash-row { gap: 12px; margin-top: 12px; }
  .row-types { grid-template-columns: minmax(0, 1fr); }
  .row-types .top-card { grid-column: auto; }
  .notice { align-items: flex-start; flex-wrap: wrap; }
  .notice .el-button { margin-left: 46px; }
  .type-number b { font-size: 32px; }
}
</style>
