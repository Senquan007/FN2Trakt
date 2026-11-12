<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">{{ isAdmin ? '开发者' : 'API 访问' }}</h2>
        <p class="page-sub">
          {{ isAdmin
            ? 'Trakt 观看历史回填、个人 API Token 与 Webhook 通知。'
            : '创建个人 API Token，用只读接口读取你的 Trakt 观看历史与媒体库状态。' }}
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
        <el-button tag="a" href="/docs" target="_blank" :icon="Document">API 文档</el-button>
      </div>
    </div>

    <el-tabs v-model="tab" class="dev-tabs">
      <el-tab-pane v-if="isAdmin" label="Trakt 回填" name="backfill">
        <el-alert type="warning" :closable="false" show-icon class="mb-16 backfill-alert">
          <template #title>回填会修改或新增本地观看记录</template>
          <template #default>
            <div class="alert-line">
              点击「开始回填」时，会先自动备份本地数据库到
              <code>{{ summary.backup_dir || 'data/backups' }}</code>，然后才写入记录。
              已有播放记录会被覆盖进度与时间；在飞牛库但还没有播放记录的条目，会新建一条回填记录。
            </div>
          </template>
        </el-alert>

        <div class="dev-toolbar">
          <el-select
            v-if="accounts.length > 1"
            v-model="accountId"
            placeholder="选择 Trakt 账号"
            style="width: 240px"
            @change="loadBackfill"
          >
            <el-option
              v-for="item in accounts"
              :key="item.id"
              :label="`${item.username || '未知用户'} · @${item.trakt_username || '未绑定'}`"
              :value="item.id"
            />
          </el-select>
          <span v-else-if="accounts.length === 1" class="tiny muted">
            当前账号：{{ accounts[0].username }} · @{{ accounts[0].trakt_username }}
          </span>
          <span v-else class="tiny muted">还没有绑定 Trakt 账号</span>
          <div class="toolbar-actions">
            <el-button :icon="Download" :loading="pulling" :disabled="!accountId" @click="pullHistory">
              拉取 Trakt 历史
            </el-button>
            <el-button :icon="View" :loading="previewing" :disabled="!accountId" @click="loadPreview">
              预览回填
            </el-button>
            <el-button type="primary" :icon="Upload" :disabled="!preview.can_apply" @click="openApply">
              开始回填
            </el-button>
          </div>
        </div>

        <div class="mini-stats">
          <div class="mini-stat">
            <span>已存 Trakt 历史</span>
            <b>{{ summary.total || 0 }}</b>
            <small>{{ summary.last_pull_at ? '拉取于 ' + formatDateTime(summary.last_pull_at) : '尚未拉取' }}</small>
          </div>
          <div class="mini-stat accent">
            <span>可回填本地记录</span>
            <b>{{ (preview.summary?.update || 0) + (preview.summary?.create || 0) }}</b>
            <small>{{ preview.summary?.update || 0 }} 更新 · {{ preview.summary?.create || 0 }} 新建</small>
          </div>
          <div class="mini-stat">
            <span>在库但无本地记录</span>
            <b>{{ preview.summary?.create || 0 }}</b>
            <small>将新建播放记录</small>
          </div>
          <div class="mini-stat">
            <span>不在飞牛媒体库</span>
            <b>{{ preview.summary?.not_in_library || 0 }}</b>
            <small>只保存在 Trakt 历史镜像中</small>
          </div>
        </div>

        <div v-if="applyResult" class="apply-result">
          <el-icon><CircleCheckFilled /></el-icon>
          <div>
            <b>{{ applyResult.message }}</b>
            <div class="tiny muted">备份文件：<code>{{ applyResult.backup_path }}</code></div>
          </div>
        </div>

        <div class="panel mt-16">
          <div class="panel-head">
            <div>
              <h3 class="panel-title"><el-icon><List /></el-icon> 回填预览</h3>
              <p class="panel-desc">预览只显示前 20 条；实际回填会处理全部匹配记录。不在飞牛库的记录会被忽略。</p>
            </div>
            <span class="chip info">将处理 {{ (preview.summary?.update || 0) + (preview.summary?.create || 0) }} 条</span>
          </div>
          <el-table :data="preview.items || []" style="width: 100%" empty-text="暂无待回填记录">
            <el-table-column label="媒体" min-width="240">
              <template #default="{ row }">
                <div class="media-cell">
                  <span class="media-type">{{ row.type === 'episode' ? '剧' : '影' }}</span>
                  <div style="min-width: 0">
                    <div class="ellipsis">
                      {{ row.type === 'episode'
                        ? `${row.show_title || '未知剧集'} - S${String(row.season || 0).padStart(2, '0')}E${String(row.episode || 0).padStart(2, '0')}`
                        : row.title }}
                    </div>
                    <div class="tiny muted">{{ row.title }}</div>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="Trakt 观看时间" width="180">
              <template #default="{ row }">{{ formatDateTime(row.watched_at) }}</template>
            </el-table-column>
            <el-table-column label="本地当前状态" width="160">
              <template #default="{ row }">
                <span class="tiny muted">
                  <template v-if="row.state === 'create'">无本地记录</template>
                  <template v-else>{{ row.current_completed ? '已看完' : '未看完' }} · {{ row.current_progress ?? 0 }}%</template>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="结果" width="100">
              <template #default="{ row }">
                <span class="chip info">
                  {{ row.state === 'create' ? '将创建' : '将更新' }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="API Token" name="api">
        <div class="api-hero">
          <div>
            <h3>用个人 Token 读取本地 Trakt 历史</h3>
            <p>
              所有 <code>/api/v1</code> 接口使用 Bearer Token：
              <code>Authorization: Bearer fnt_...</code>。Token 只显示一次，保存后仅保留前缀。
            </p>
            <div class="api-base">
              <span>Base URL</span>
              <code>{{ apiBase }}</code>
            </div>
          </div>
          <el-button type="primary" :icon="Plus" @click="openTokenCreate">新建 Token</el-button>
        </div>

        <div class="panel mt-16">
          <div class="panel-head">
            <div>
              <h3 class="panel-title"><el-icon><Key /></el-icon> 我的 Token</h3>
              <p class="panel-desc">只显示 Token 前缀；撤销后立即失效。</p>
            </div>
          </div>
          <el-table :data="tokens" style="width: 100%" empty-text="还没有 API Token">
            <el-table-column label="名称" min-width="160">
              <template #default="{ row }"><b>{{ row.name }}</b></template>
            </el-table-column>
            <el-table-column label="前缀" width="140">
              <template #default="{ row }"><code>{{ row.prefix }}…</code></template>
            </el-table-column>
            <el-table-column label="权限" min-width="220">
              <template #default="{ row }">
                <span v-for="scope in row.scopes" :key="scope" class="chip muted" style="margin-right: 4px">
                  {{ scope }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="最近使用" width="170">
              <template #default="{ row }">{{ row.last_used_at ? formatDateTime(row.last_used_at) : '从未' }}</template>
            </el-table-column>
            <el-table-column label="创建于" width="170">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button text type="danger" size="small" @click="revokeToken(row)">撤销</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="panel mt-16">
          <div class="panel-head">
            <div>
              <h3 class="panel-title"><el-icon><Connection /></el-icon> 可用接口</h3>
              <p class="panel-desc">完整 OpenAPI 文档在 <a href="/docs" target="_blank">/docs</a>，可以直接调试。</p>
            </div>
          </div>
          <div class="endpoint-list">
            <div v-for="item in endpoints" :key="item.path" class="endpoint-row">
              <span class="method" :class="item.method.toLowerCase()">{{ item.method }}</span>
              <code>{{ item.path }}</code>
              <span class="tiny muted">{{ item.desc }}</span>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane v-if="isAdmin" label="Webhook" name="webhooks">
        <div class="dev-toolbar">
          <div>
            <b>任务失败与未匹配通知</b>
            <div class="tiny muted">同步失败、存在未匹配记录、回填完成时推送到指定 URL；支持 HMAC 签名与失败重试。</div>
          </div>
          <el-button type="primary" :icon="Plus" @click="openWebhookCreate">新建 Webhook</el-button>
        </div>

        <div class="panel mt-16">
          <el-table :data="webhooks" style="width: 100%" empty-text="还没有 Webhook">
            <el-table-column label="名称" min-width="150">
              <template #default="{ row }"><b>{{ row.name }}</b></template>
            </el-table-column>
            <el-table-column label="URL" min-width="260">
              <template #default="{ row }"><span class="mono tiny">{{ row.url }}</span></template>
            </el-table-column>
            <el-table-column label="事件" min-width="220">
              <template #default="{ row }">
                <span v-for="event in row.events" :key="event" class="chip muted" style="margin-right: 4px">
                  {{ eventLabel(event) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <span class="chip" :class="row.enabled ? 'success' : 'muted'">{{ row.enabled ? '启用' : '停用' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="最近投递" width="180">
              <template #default="{ row }">
                <span class="chip" :class="row.last_status === 'success' ? 'success' : row.last_status ? 'danger' : 'muted'">
                  {{ row.last_status || '未投递' }}
                </span>
                <div class="tiny muted">{{ row.last_delivery_at ? formatDateTime(row.last_delivery_at) : '—' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220">
              <template #default="{ row }">
                <el-button text size="small" type="primary" @click="testWebhook(row)">测试</el-button>
                <el-button text size="small" @click="openWebhookEdit(row)">编辑</el-button>
                <el-button text size="small" type="danger" @click="removeWebhook(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="panel mt-16">
          <div class="panel-head">
            <div>
              <h3 class="panel-title"><el-icon><Refresh /></el-icon> 最近投递</h3>
              <p class="panel-desc">失败会在 5 分钟后自动重试，最多 3 次。</p>
            </div>
            <el-button text type="primary" @click="loadDeliveries">刷新</el-button>
          </div>
          <el-table :data="deliveries" style="width: 100%" empty-text="还没有投递记录">
            <el-table-column label="事件" width="160">
              <template #default="{ row }">{{ eventLabel(row.event) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <span class="chip" :class="row.status === 'success' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">
                  {{ row.status }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="尝试" width="70" prop="attempts" />
            <el-table-column label="响应" width="100">
              <template #default="{ row }">{{ row.response_status || '—' }}</template>
            </el-table-column>
            <el-table-column label="信息" min-width="220">
              <template #default="{ row }">
                <span class="tiny muted ellipsis">{{ row.error || row.response_body || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button v-if="row.status !== 'success' && row.attempts < 3" text size="small" type="primary" @click="retryDelivery(row)">
                  重试
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- apply backfill -->
    <el-dialog append-to-body v-model="applyVisible" title="确认回填本地观看记录" width="520px">
      <el-alert type="warning" :closable="false" show-icon title="此操作会修改数据库" />
      <p class="tiny" style="line-height: 1.8; margin: 14px 0">
        将更新 <b>{{ preview.summary?.update || 0 }}</b> 条、新建 <b>{{ preview.summary?.create || 0 }}</b> 条本地记录：把进度改为 100%、标记为已看完，并写入 Trakt 观看时间。
        执行前会自动备份到 <code>{{ summary.backup_dir || 'data/backups' }}</code>。
      </p>
      <el-checkbox v-model="applyAck">我已了解并同意修改/新增本地观看记录</el-checkbox>
      <template #footer>
        <el-button @click="applyVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!applyAck" :loading="applying" @click="applyBackfill">开始回填</el-button>
      </template>
    </el-dialog>

    <!-- token create -->
    <el-dialog append-to-body v-model="tokenVisible" title="新建 API Token" width="520px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="tokenForm.name" placeholder="例如：Home Assistant / 个人脚本" />
        </el-form-item>
        <el-form-item label="权限">
          <el-checkbox-group v-model="tokenForm.scopes">
            <el-checkbox v-for="scope in tokenScopes" :key="scope.key" :value="scope.key">
              {{ scope.label }}
              <span class="tiny muted">（{{ scope.key }}）</span>
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tokenVisible = false">取消</el-button>
        <el-button type="primary" :loading="creatingToken" @click="createToken">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog append-to-body v-model="tokenResultVisible" title="Token 已创建" width="560px">
      <el-alert type="warning" :closable="false" show-icon title="只显示这一次，请现在复制保存" />
      <div class="token-result">
        <code>{{ newToken }}</code>
        <el-button :icon="CopyDocument" @click="copyToken">复制</el-button>
      </div>
      <p class="tiny muted">之后列表只显示前缀，无法再次查看完整 Token。</p>
      <template #footer>
        <el-button type="primary" @click="tokenResultVisible = false">我已保存</el-button>
      </template>
    </el-dialog>

    <!-- webhook create/edit -->
    <el-dialog append-to-body v-model="webhookVisible" :title="webhookForm.id ? '编辑 Webhook' : '新建 Webhook'" width="560px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="webhookForm.name" placeholder="例如：Home Assistant" />
        </el-form-item>
        <el-form-item label="URL">
          <el-input v-model="webhookForm.url" placeholder="https://example.com/fn2trakt" spellcheck="false" />
        </el-form-item>
        <el-form-item label="事件">
          <el-checkbox-group v-model="webhookForm.events">
            <el-checkbox v-for="event in webhookEvents" :key="event.key" :value="event.key">
              {{ event.label }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item :label="webhookForm.id ? 'Secret（留空保持不变）' : 'Secret（可选）'">
          <el-input v-model="webhookForm.secret" type="password" show-password placeholder="用于 HMAC-SHA256 签名" />
        </el-form-item>
        <el-form-item v-if="webhookForm.id">
          <el-checkbox v-model="webhookForm.clear_secret">清除已保存的 Secret</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-switch v-model="webhookForm.enabled" active-text="启用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="webhookVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingWebhook" @click="saveWebhook">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CircleCheckFilled,
  Connection,
  CopyDocument,
  Document,
  Download,
  Key,
  List,
  Plus,
  Refresh,
  Upload,
  View
} from '@element-plus/icons-vue'
import api, { errMsg } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'

const auth = useAuthStore()
const isAdmin = computed(() => auth.isAdmin)
const tab = ref(isAdmin.value ? 'backfill' : 'api')
const loading = ref(false)

const accounts = ref([])
const accountId = ref(null)
const summary = ref({})
const preview = ref({ summary: {}, items: [] })
const pulling = ref(false)
const previewing = ref(false)
const applying = ref(false)
const applyVisible = ref(false)
const applyAck = ref(false)
const applyResult = ref(null)

const tokens = ref([])
const tokenScopes = ref([])
const tokenVisible = ref(false)
const tokenResultVisible = ref(false)
const creatingToken = ref(false)
const newToken = ref('')
const tokenForm = reactive({ name: '', scopes: ['history:read', 'library:read'] })

const webhooks = ref([])
const webhookEvents = ref([])
const deliveries = ref([])
const webhookVisible = ref(false)
const savingWebhook = ref(false)
const webhookForm = reactive({
  id: null,
  name: '',
  url: '',
  events: ['sync.failed', 'sync.unmatched'],
  secret: '',
  clear_secret: false,
  enabled: true
})

const apiBase = computed(() => `${window.location.origin}/api/v1`)
const endpoints = [
  { method: 'GET', path: '/api/v1/history', desc: '分页查询观看历史，支持类型、匹配状态、关键词、日期范围' },
  { method: 'GET', path: '/api/v1/history/recent', desc: '最近观看记录，适合仪表盘或 Widget' },
  { method: 'GET', path: '/api/v1/history/stats', desc: '电影/剧集数量、总时长、月度分布、Top 剧集' },
  { method: 'GET', path: '/api/v1/history/export', desc: '导出 JSON 或 CSV' },
  { method: 'GET', path: '/api/v1/library', desc: '搜索本地媒体库，并返回当前用户的播放状态' },
  { method: 'GET', path: '/api/v1/sync/status', desc: '最近同步任务与同步状态计数' },
  { method: 'POST', path: '/api/v1/history/refresh', desc: '从 Trakt 拉取自己的观看历史（需要 history:write）' },
  { method: 'POST', path: '/api/v1/sync/run', desc: '触发一次同步（管理员，需要 sync:write）' },
  { method: 'GET', path: '/api/v1/me', desc: 'Token 信息、权限和 Trakt 绑定状态' }
]

function eventLabel(key) {
  return webhookEvents.value.find((item) => item.key === key)?.label || key
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadTokens(), isAdmin.value ? loadWebhooks() : Promise.resolve()])
    if (isAdmin.value) await loadAccounts()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    loading.value = false
  }
}

async function loadAccounts() {
  const data = await api.get('/trakt/history/accounts')
  accounts.value = data.items || []
  if (!accountId.value && accounts.value.length) {
    const own = accounts.value.find((item) => item.app_user_id === auth.user?.id)
    accountId.value = (own || accounts.value[0]).id
  }
  if (accountId.value) await loadBackfill()
}

async function loadBackfill() {
  if (!accountId.value) return
  const [sum, prev] = await Promise.all([
    api.get('/trakt/history/summary', { params: { account_id: accountId.value } }),
    api.get('/trakt/history/preview', { params: { account_id: accountId.value } })
  ])
  summary.value = sum
  preview.value = prev
}

async function pullHistory() {
  pulling.value = true
  try {
    const result = await api.post('/trakt/history/pull', { account_id: accountId.value })
    ElMessage.success(`已拉取 ${result.fetched} 条 Trakt 历史`)
    await loadBackfill()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    pulling.value = false
  }
}

async function loadPreview() {
  previewing.value = true
  try {
    const data = await api.get('/trakt/history/preview', { params: { account_id: accountId.value } })
    preview.value = data
    ElMessage.success(`将更新 ${data.summary?.update || 0} 条、新建 ${data.summary?.create || 0} 条记录`)
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    previewing.value = false
  }
}

function openApply() {
  applyAck.value = false
  applyVisible.value = true
}

async function applyBackfill() {
  applying.value = true
  try {
    const result = await api.post('/trakt/history/apply', {
      account_id: accountId.value,
      confirm: true
    })
    applyResult.value = result
    applyVisible.value = false
    ElMessage.success(result.message)
    await loadBackfill()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    applying.value = false
  }
}

async function loadTokens() {
  const data = await api.get('/tokens')
  tokens.value = data.items || []
  tokenScopes.value = (data.scopes || []).filter(
    (scope) => isAdmin.value || scope.key !== 'sync:write'
  )
}

function openTokenCreate() {
  tokenForm.name = ''
  tokenForm.scopes = ['history:read', 'library:read']
  tokenVisible.value = true
}

async function createToken() {
  if (!tokenForm.name.trim()) {
    ElMessage.warning('请填写 Token 名称')
    return
  }
  creatingToken.value = true
  try {
    const data = await api.post('/tokens', {
      name: tokenForm.name.trim(),
      scopes: tokenForm.scopes
    })
    newToken.value = data.token
    tokenVisible.value = false
    tokenResultVisible.value = true
    await loadTokens()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    creatingToken.value = false
  }
}

async function copyToken() {
  try {
    await navigator.clipboard.writeText(newToken.value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择')
  }
}

async function revokeToken(row) {
  try {
    await ElMessageBox.confirm(`撤销 Token「${row.name}」？使用它的调用会立即收到 401。`, '撤销 Token', {
      type: 'warning'
    })
    await api.delete(`/tokens/${row.id}`)
    ElMessage.success('已撤销')
    await loadTokens()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(errMsg(error))
  }
}

async function loadWebhooks() {
  const data = await api.get('/webhooks')
  webhooks.value = data.items || []
  webhookEvents.value = data.events || []
  await loadDeliveries()
}

async function loadDeliveries() {
  const data = await api.get('/webhooks/deliveries', { params: { limit: 30 } })
  deliveries.value = data.items || []
}

function openWebhookCreate() {
  Object.assign(webhookForm, {
    id: null,
    name: '',
    url: '',
    events: ['sync.failed', 'sync.unmatched'],
    secret: '',
    clear_secret: false,
    enabled: true
  })
  webhookVisible.value = true
}

function openWebhookEdit(row) {
  Object.assign(webhookForm, {
    id: row.id,
    name: row.name,
    url: row.url,
    events: [...(row.events || [])],
    secret: '',
    clear_secret: false,
    enabled: row.enabled
  })
  webhookVisible.value = true
}

async function saveWebhook() {
  if (!webhookForm.name.trim() || !webhookForm.url.trim()) {
    ElMessage.warning('请填写名称和 URL')
    return
  }
  if (!webhookForm.events.length) {
    ElMessage.warning('至少选择一个事件')
    return
  }
  savingWebhook.value = true
  try {
    const payload = {
      name: webhookForm.name.trim(),
      url: webhookForm.url.trim(),
      events: webhookForm.events,
      enabled: webhookForm.enabled
    }
    if (webhookForm.secret.trim()) payload.secret = webhookForm.secret.trim()
    if (webhookForm.id) {
      payload.clear_secret = webhookForm.clear_secret
      await api.patch(`/webhooks/${webhookForm.id}`, payload)
    } else {
      await api.post('/webhooks', payload)
    }
    ElMessage.success('已保存')
    webhookVisible.value = false
    await loadWebhooks()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    savingWebhook.value = false
  }
}

async function testWebhook(row) {
  try {
    await api.post(`/webhooks/${row.id}/test`)
    ElMessage.success('测试请求已发送')
    setTimeout(loadDeliveries, 1200)
  } catch (error) {
    ElMessage.error(errMsg(error))
  }
}

async function removeWebhook(row) {
  try {
    await ElMessageBox.confirm(`删除 Webhook「${row.name}」？`, '删除 Webhook', { type: 'warning' })
    await api.delete(`/webhooks/${row.id}`)
    ElMessage.success('已删除')
    await loadWebhooks()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(errMsg(error))
  }
}

async function retryDelivery(row) {
  try {
    await api.post(`/webhooks/deliveries/${row.id}/retry`)
    ElMessage.success('已重新投递')
    setTimeout(loadDeliveries, 1000)
  } catch (error) {
    ElMessage.error(errMsg(error))
  }
}

onMounted(loadAll)
</script>

<style scoped>
.dev-tabs :deep(.el-tabs__header) { margin-bottom: 22px; }
.dev-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}
.toolbar-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.backfill-alert {
  margin-bottom: 20px;
  background: var(--glass-soft) !important;
  border: 1px solid var(--glass-border) !important;
}
.backfill-alert :deep(.el-alert__title) { color: var(--ink-strong); }
.backfill-alert :deep(.el-alert__description) { color: var(--muted); }
.backfill-alert :deep(.el-alert__icon) { color: var(--danger); }
.alert-line { line-height: 1.8; }
.alert-line code, .apply-result code, .token-result code { font-family: "SFMono-Regular", ui-monospace, monospace; }

.mini-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}
.mini-stat {
  padding: 16px 18px;
  border-radius: 16px;
  border: 1px solid var(--glass-border);
  background: var(--glass);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mini-stat span { font-size: 12px; color: var(--muted); }
.mini-stat b { font-size: 28px; letter-spacing: -0.04em; color: var(--ink-strong); line-height: 1.1; }
.mini-stat small { font-size: 11px; color: var(--muted); }
.mini-stat.accent { border-color: color-mix(in srgb, var(--primary) 24%, var(--glass-border)); }
.mini-stat.accent b { color: var(--primary-deep); }

.apply-result {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 14px;
  padding: 13px 15px;
  border-radius: 14px;
  background: var(--success-soft);
  border: 1px solid color-mix(in srgb, var(--success) 22%, transparent);
  color: var(--success-ink);
}
.apply-result .el-icon { margin-top: 2px; font-size: 18px; }

.api-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 24px;
  border-radius: 18px;
  background:
    linear-gradient(110deg, rgba(47, 111, 235, 0.07), transparent 55%),
    var(--glass);
  border: 1px solid color-mix(in srgb, var(--primary) 14%, var(--glass-border));
  box-shadow: var(--shadow-sm);
}
.api-hero h3 { margin: 0 0 6px; font-size: 16px; color: var(--ink-strong); }
.api-hero p { margin: 0; font-size: 12.5px; line-height: 1.75; color: var(--muted); }
.api-base { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 12px; color: var(--muted); }
.api-base code { padding: 5px 8px; border-radius: 7px; background: var(--glass-soft); color: var(--ink); }

.endpoint-list { padding: 8px 20px 18px; display: flex; flex-direction: column; }
.endpoint-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px dashed var(--line);
  font-size: 12.5px;
}
.endpoint-row:last-child { border-bottom: none; }
.endpoint-row code { min-width: 220px; color: var(--ink); }
.method {
  width: 48px;
  flex: none;
  text-align: center;
  font-size: 10.5px;
  font-weight: 700;
  padding: 3px 0;
  border-radius: 5px;
  color: var(--success-ink);
  background: var(--success-soft);
}
.method.post { color: var(--warning-ink); background: var(--warning-soft); }

.token-result { display: flex; gap: 10px; align-items: center; margin: 14px 0 8px; }
.token-result code {
  flex: 1;
  padding: 11px 13px;
  border-radius: 10px;
  background: var(--glass-soft);
  border: 1px solid var(--glass-border);
  word-break: break-all;
  font-size: 12px;
}

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
.ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

@media (max-width: 900px) {
  .mini-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .api-hero { flex-direction: column; }
  .endpoint-row { flex-wrap: wrap; }
  .endpoint-row code { min-width: 0; width: 100%; }
}
@media (max-width: 560px) {
  .mini-stats { grid-template-columns: minmax(0, 1fr); }
  .dev-toolbar { align-items: stretch; }
  .toolbar-actions { width: 100%; }
  .toolbar-actions .el-button { flex: 1; }
}
</style>
