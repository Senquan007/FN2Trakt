<template>
  <el-dialog
    append-to-body
    :model-value="modelValue"
    title="手动匹配 Trakt 条目"
    width="680px"
    top="6vh"
    @update:model-value="$emit('update:modelValue', $event)"
    @open="onOpen"
  >
    <div class="match-head">
      <div>
        <div class="tiny muted">飞牛条目</div>
        <div style="font-weight: 650">{{ target?.title || '—' }}</div>
        <div class="tiny muted">
          {{ target?.media_type === 'movie' ? '电影' : '剧集' }}
          <span v-if="target?.year"> · {{ target.year }}</span>
          <span v-if="target?.tmdb_id"> · TMDB {{ target.tmdb_id }}</span>
          <span v-if="target?.imdb_id"> · IMDB {{ target.imdb_id }}</span>
        </div>
      </div>
      <span v-if="current" class="chip info">当前：{{ current.title || '已匹配' }}</span>
    </div>

    <div class="search-bar">
      <el-input
        v-model="query"
        placeholder="搜索 Trakt 上的剧名 / 电影名，可输入英文原名"
        clearable
        @keyup.enter="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="mediaType" style="width: 120px" @change="search">
        <el-option label="剧集" value="show" />
        <el-option label="电影" value="movie" />
      </el-select>
      <el-button type="primary" :loading="loading" @click="search">搜索</el-button>
    </div>

    <div class="results">
      <div v-if="loading" class="empty"><el-icon class="is-loading"><Loading /></el-icon><div>搜索中…</div></div>
      <div v-else-if="!results.length" class="empty">
        <el-icon><Search /></el-icon>
        <div>没有结果，试试英文名或去掉副标题</div>
      </div>
      <div v-for="item in results" :key="item.ids?.trakt || item.title" class="result-item">
        <div class="result-poster">
          {{ item.type === 'movie' ? '影' : '剧' }}
        </div>
        <div style="flex: 1; min-width: 0">
          <div class="result-title">{{ item.title }} <span v-if="item.year" class="muted">({{ item.year }})</span></div>
          <div class="tiny muted ellipsis-2">{{ item.overview || '暂无简介' }}</div>
          <div class="tiny muted" style="margin-top: 4px">
            <span v-if="item.ids?.tmdb">TMDB {{ item.ids.tmdb }}</span>
            <span v-if="item.ids?.imdb"> · IMDB {{ item.ids.imdb }}</span>
            <span v-if="item.ids?.trakt"> · Trakt {{ item.ids.trakt }}</span>
          </div>
        </div>
        <el-button size="small" type="primary" plain @click="choose(item)">选择</el-button>
      </div>
    </div>

    <template #footer>
      <div class="flex-between">
        <el-button text type="danger" @click="reject">忽略该条目</el-button>
        <el-button @click="$emit('update:modelValue', false)">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api, { errMsg } from '@/api/client'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  target: { type: Object, default: null }
})
const emit = defineEmits(['update:modelValue', 'matched'])

const query = ref('')
const mediaType = ref('show')
const results = ref([])
const current = ref(null)
const loading = ref(false)

watch(
  () => props.target,
  (value) => {
    if (value) {
      query.value = value.title || ''
      mediaType.value = value.media_type || 'show'
    }
  }
)

function onOpen() {
  if (props.target) {
    query.value = props.target.title || ''
    mediaType.value = props.target.media_type || 'show'
    search()
  }
}

async function search() {
  if (!query.value.trim()) return
  loading.value = true
  try {
    const data = await api.get('/media/search', {
      params: {
        query: query.value.trim(),
        media_type: mediaType.value,
        media_guid: props.target?.media_guid
      }
    })
    results.value = data.items || []
    current.value = data.current
  } catch (error) {
    ElMessage.error(errMsg(error))
    results.value = []
  } finally {
    loading.value = false
  }
}

async function choose(item) {
  try {
    await api.post('/media/match', {
      media_guid: props.target.media_guid,
      candidate: item
    })
    ElMessage.success('匹配已保存')
    emit('matched')
    emit('update:modelValue', false)
  } catch (error) {
    ElMessage.error(errMsg(error))
  }
}

async function reject() {
  try {
    await api.post('/media/reject', { media_guid: props.target.media_guid })
    ElMessage.success('已忽略该条目')
    emit('matched')
    emit('update:modelValue', false)
  } catch (error) {
    ElMessage.error(errMsg(error))
  }
}
</script>

<style scoped>
.match-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  padding: 13px 15px;
  border-radius: 16px;
  background: var(--glass-soft);
  border: 1px solid var(--glass-border);
}
.search-bar { display: flex; gap: 10px; margin: 16px 0; }
.results { max-height: 420px; overflow-y: auto; padding-right: 4px; }
.result-item {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px;
  border-radius: 16px;
  border: 1px solid var(--glass-border);
  background: var(--glass-soft);
  margin-bottom: 9px;
  transition: border-color 0.18s, box-shadow 0.18s, transform 0.18s;
}
.result-item:hover {
  border-color: color-mix(in srgb, var(--primary) 35%, transparent);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}
.result-poster {
  width: 38px;
  height: 46px;
  flex: none;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 700;
  color: var(--on-primary);
  background: var(--primary-grad);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
}
.result-title { font-weight: 650; font-size: 13.5px; }
.ellipsis-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.45;
}
</style>
