<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">系统设置</h2>
        <p class="page-sub">配置飞牛数据库、同步策略与 Trakt 应用凭据。凭据保存后不会在前端再次显示。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>

    <div class="grid grid-2 settings-top">
      <!-- fnTV db -->
      <div class="panel db-card">
        <div class="panel-head">
          <div>
            <h3 class="panel-title"><el-icon><Coin /></el-icon> 飞牛影视数据库</h3>
            <p class="panel-desc">只读访问 trimmedia.db，不会修改飞牛数据</p>
          </div>
          <span class="chip" :class="dbStatus?.database?.ok ? 'success' : 'danger'">
            {{ dbStatus?.database?.ok ? '连接正常' : '不可用' }}
          </span>
        </div>
        <div class="panel-pad">
          <el-form label-position="top">
            <el-form-item label="数据库路径">
              <el-input v-model="form.fntv_db_path" placeholder="/path/to/trimmedia.db" spellcheck="false">
                <template #append>
                  <el-button @click="testPath">测试</el-button>
                </template>
              </el-input>
              <div class="tiny muted" style="margin-top: 6px">
                飞牛 NAS 默认：/usr/local/apps/@appdata/trim.media/database/trimmedia.db
                <br />
                Docker 中通常挂载为 /fntv/trimmedia.db
              </div>
            </el-form-item>
          </el-form>

          <el-alert
            v-if="testResult"
            :type="testResult.ok ? 'success' : 'error'"
            :title="testResult.ok ? '数据库可用' : '数据库不可用'"
            :description="
              testResult.ok
                ? `媒体 ${testResult.counts?.item ?? 0} 个 · 用户 ${testResult.counts?.user ?? 0} 个 · 播放 ${testResult.counts?.item_user_play ?? 0} 条`
                : testResult.error || '请检查路径与文件权限'
            "
            show-icon
            :closable="false"
            class="mt-16"
          />

          <div class="stat-mini mt-16">
            <div><b>{{ dbStatus?.cached?.plays ?? 0 }}</b><span>本地播放记录</span></div>
            <div><b>{{ dbStatus?.cached?.completed ?? 0 }}</b><span>已看完</span></div>
            <div><b>{{ dbStatus?.cached?.unmatched ?? 0 }}</b><span>未匹配媒体</span></div>
          </div>

          <div class="flex mt-16 db-actions" style="flex-wrap: wrap">
            <el-button type="primary" :loading="savingPath" @click="savePath">保存路径</el-button>
            <el-button :loading="refreshing" :icon="Download" @click="refreshData">重新读取飞牛数据</el-button>
          </div>
          <div v-if="refreshResult" class="tiny muted mt-8">
            最近刷新：{{ refreshResult }}
          </div>
        </div>
      </div>

      <!-- sync strategy -->
      <div class="panel">
        <div class="panel-head">
          <div>
            <h3 class="panel-title"><el-icon><Refresh /></el-icon> 同步策略</h3>
            <p class="panel-desc">后台定时扫描新完成的记录并自动上传</p>
          </div>
          <el-switch v-model="form.sync_enabled" />
        </div>
        <div class="panel-pad">
          <el-form label-position="top">
            <el-form-item label="同步间隔（分钟）">
              <el-input-number v-model="form.sync_interval_minutes" :min="1" :max="1440" style="width: 100%" />
              <div class="tiny muted" style="margin-top: 6px">默认 5 分钟；修改后定时任务立即生效。</div>
            </el-form-item>
            <el-form-item :label="`上传进度阈值：${form.watched_threshold}%`" class="threshold-item">
              <el-slider v-model="form.watched_threshold" :min="50" :max="100" :step="1" />
              <div class="tiny muted" style="margin-top: 14px">
                飞牛 watched=1，或播放进度达到该阈值（默认 80%），即视为已看完并纳入上传。
              </div>
            </el-form-item>
          </el-form>


          <el-button type="primary" class="mt-16" :loading="savingSync" @click="saveSync">保存同步设置</el-button>
        </div>
      </div>
    </div>

    <!-- Trakt credentials -->
    <div class="panel mt-16">
      <div class="panel-head">
        <div>
          <h3 class="panel-title"><el-icon><Key /></el-icon> Trakt 应用凭据</h3>
          <p class="panel-desc">
            支持保存多套命名凭据；设备授权默认使用标记为「默认」的一套
          </p>
        </div>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建凭据</el-button>
      </div>
      <div class="panel-pad" style="padding-bottom: 8px">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="Client ID / Client Secret 保存后不会再次显示"
        >
          <template #default>
            <span class="tiny">
              新建时填写一次即可；后续如需修改，请在编辑框中重新输入。列表只显示名称、是否配置 Secret、Redirect URI 和使用情况。
            </span>
          </template>
        </el-alert>
      </div>
      <el-table v-loading="credentialLoading" :data="credentials" style="width: 100%">
        <el-table-column label="名称" min-width="180">
          <template #default="{ row }">
            <div class="flex" style="gap: 8px">
              <span style="font-weight: 650">{{ row.name }}</span>
              <span v-if="row.is_default" class="chip info">默认</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Client Secret" width="120">
          <template #default="{ row }">
            <span class="chip" :class="row.has_secret ? 'success' : 'muted'">
              {{ row.has_secret ? '已设置' : '无（PKCE）' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="Redirect URI" min-width="220">
          <template #default="{ row }">
            <span class="mono tiny">{{ row.redirect_uri }}</span>
          </template>
        </el-table-column>
        <el-table-column label="使用账号" width="100">
          <template #default="{ row }">{{ row.account_count }} 个</template>
        </el-table-column>
        <el-table-column label="更新时间" width="160">
          <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230">
          <template #default="{ row }">
            <el-button v-if="!row.is_default" size="small" text type="primary" @click="makeDefault(row)">
              设为默认
            </el-button>
            <el-button size="small" text type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="removeCredential(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty">
            <el-icon><Key /></el-icon>
            <div>还没有 Trakt 应用凭据，点击右上角「新建凭据」开始</div>
          </div>
        </template>
      </el-table>
    </div>

    <div class="grid grid-2 settings-bottom mt-16">
      <!-- active trakt -->
      <div class="panel">
        <div class="panel-head">
          <div>
            <h3 class="panel-title"><el-icon><Link /></el-icon> Trakt 绑定</h3>
            <p class="panel-desc">普通用户可以自行完成设备授权，但看不到应用凭据</p>
          </div>
          <span class="chip" :class="settings?.trakt?.configured ? 'success' : 'warning'">
            {{ settings?.trakt?.configured ? '已配置' : '未配置' }}
          </span>
        </div>
        <div class="panel-pad">
          <div class="info-row">
            <span class="info-label">当前默认凭据</span>
            <span>{{ settings?.trakt?.name || '—' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">凭据来源</span>
            <span>{{
              settings?.trakt?.source === 'environment'
                ? '环境变量'
                : settings?.trakt?.source === 'database'
                  ? '本地数据库'
                  : '未配置'
            }}</span>
          </div>
          <div class="info-row" style="border-bottom: none">
            <span class="info-label">Secret</span>
            <span>{{ settings?.trakt?.has_secret ? '已设置' : '未设置（PKCE 正常）' }}</span>
          </div>
          <el-button type="primary" plain :icon="Link" class="mt-16" @click="$router.push('/trakt')">
            前往 Trakt 绑定页
          </el-button>
        </div>
      </div>

      <!-- about -->
      <div class="panel">
        <div class="panel-head">
          <div>
            <h3 class="panel-title"><el-icon><InfoFilled /></el-icon> 运行信息</h3>
            <p class="panel-desc">版本与数据位置</p>
          </div>
        </div>
        <div class="panel-pad">
          <div class="info-row"><span class="info-label">版本</span><span>FN2Trakt v3.0.0</span></div>
          <div class="info-row"><span class="info-label">飞牛数据库</span><span class="mono tiny">{{ settings?.fntv_db_path || '—' }}</span></div>
          <div class="info-row"><span class="info-label">应用数据库</span><span class="mono tiny">data/fn2trakt.db</span></div>
          <div class="info-row"><span class="info-label">定时任务</span><span>{{ settings?.scheduler?.interval_minutes || 5 }} 分钟</span></div>
          <div class="info-row"><span class="info-label">下次同步</span><span>{{ settings?.scheduler?.next_run_at ? formatDateTime(settings.scheduler.next_run_at) : '—' }}</span></div>
          <div class="info-row" style="border-bottom: none">
            <span class="info-label">凭据数量</span>
            <span>{{ settings?.trakt?.credential_count ?? 0 }} 套</span>
          </div>
        </div>
      </div>
    </div>

    <!-- create dialog -->
    <el-dialog append-to-body v-model="createVisible" title="新建 Trakt 应用凭据" width="520px" top="8vh">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="保存后不会再次显示 Client ID / Secret"
        description="请确认内容无误后再保存；后续修改需要重新输入。"
      />
      <el-form label-position="top" class="mt-16">
        <el-form-item label="凭据名称">
          <el-input v-model="createForm.name" placeholder="例如：个人 Trakt 应用" />
        </el-form-item>
        <el-form-item label="Client ID">
          <el-input v-model="createForm.client_id" placeholder="Trakt 应用的 Client ID" spellcheck="false" />
        </el-form-item>
        <el-form-item label="Client Secret（可选）">
          <el-input
            v-model="createForm.client_secret"
            type="password"
            show-password
            placeholder="新版 PKCE 应用没有 Secret，留空即可"
          />
        </el-form-item>
        <el-form-item label="Redirect URI">
          <el-input v-model="createForm.redirect_uri" placeholder="urn:ietf:wg:oauth:2.0:oob" spellcheck="false" />
          <div class="tiny muted" style="margin-top: 6px">
            必须与 Trakt 应用详情里的 Redirect URI 完全一致；刷新 Token 时会校验。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingCredential" @click="saveCreate">保存</el-button>
      </template>
    </el-dialog>

    <!-- edit dialog -->
    <el-dialog append-to-body v-model="editVisible" :title="`编辑凭据：${editForm.name}`" width="520px" top="8vh">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="Client ID / Secret 不回显"
        description="留空表示保持原值；只有填写新值才会覆盖。"
      />
      <el-form label-position="top" class="mt-16">
        <el-form-item label="凭据名称">
          <el-input v-model="editForm.name" />
        </el-form-item>
        <el-form-item label="Client ID（留空保持不变）">
          <el-input v-model="editForm.client_id" placeholder="重新输入才会覆盖当前值" spellcheck="false" />
          <div class="tiny" style="color: #b26a00; margin-top: 6px">
            修改 Client ID 后，已经用旧凭据授权的账号可能需要重新授权。
          </div>
        </el-form-item>
        <el-form-item label="Client Secret（留空保持不变）">
          <el-input
            v-model="editForm.client_secret"
            type="password"
            show-password
            placeholder="重新输入才会覆盖当前值"
          />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="editForm.clear_secret">清除已保存的 Client Secret</el-checkbox>
        </el-form-item>
        <el-form-item label="Redirect URI">
          <el-input v-model="editForm.redirect_uri" spellcheck="false" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingCredential" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Key, Link, Plus, Refresh } from '@element-plus/icons-vue'
import api, { errMsg } from '@/api/client'
import { formatDateTime } from '@/utils/format'

const loading = ref(false)
const savingPath = ref(false)
const savingSync = ref(false)
const refreshing = ref(false)
const settings = ref(null)
const dbStatus = ref(null)
const testResult = ref(null)
const refreshResult = ref('')

const credentials = ref([])
const credentialLoading = ref(false)
const createVisible = ref(false)
const editVisible = ref(false)
const savingCredential = ref(false)

const form = reactive({
  fntv_db_path: '',
  sync_enabled: true,
  sync_interval_minutes: 5,
  watched_threshold: 80
})

const createForm = reactive({
  name: '',
  client_id: '',
  client_secret: '',
  redirect_uri: 'urn:ietf:wg:oauth:2.0:oob'
})

const editForm = reactive({
  id: null,
  name: '',
  client_id: '',
  client_secret: '',
  clear_secret: false,
  redirect_uri: 'urn:ietf:wg:oauth:2.0:oob'
})

async function load() {
  loading.value = true
  try {
    const [settingData, statusData, credentialData] = await Promise.all([
      api.get('/settings'),
      api.get('/fntv/status'),
      api.get('/trakt/credentials')
    ])
    settings.value = settingData
    dbStatus.value = statusData
    credentials.value = credentialData.items || []
    form.fntv_db_path = settingData.fntv_db_path
    form.sync_enabled = settingData.sync.enabled
    form.sync_interval_minutes = settingData.sync.interval_minutes
    form.watched_threshold = settingData.sync.watched_threshold
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    loading.value = false
  }
}

async function testPath() {
  try {
    testResult.value = await api.post('/settings/test-fntv', { path: form.fntv_db_path })
  } catch (error) {
    testResult.value = { ok: false, error: errMsg(error) }
  }
}

async function savePath() {
  savingPath.value = true
  try {
    await api.put('/settings', { fntv_db_path: form.fntv_db_path })
    ElMessage.success('路径已保存')
    await load()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    savingPath.value = false
  }
}

async function refreshData() {
  refreshing.value = true
  try {
    const data = await api.post('/fntv/refresh', { run_matching: true })
    const snap = data.snapshot
    refreshResult.value = `${new Date().toLocaleTimeString('zh-CN')} · 读取 ${snap.plays} 条，已看完 ${snap.completed} 条，新增 ${snap.created}，更新 ${snap.updated}`
    ElMessage.success('飞牛数据已重新读取')
    await load()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    refreshing.value = false
  }
}

async function saveSync() {
  savingSync.value = true
  try {
    await api.put('/settings', {
      sync_enabled: form.sync_enabled,
      sync_interval_minutes: form.sync_interval_minutes,
      watched_threshold: form.watched_threshold
    })
    ElMessage.success('同步设置已保存，定时任务已重新调度')
    await load()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    savingSync.value = false
  }
}

function openCreate() {
  createForm.name = ''
  createForm.client_id = ''
  createForm.client_secret = ''
  createForm.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
  createVisible.value = true
}

async function saveCreate() {
  if (!createForm.name.trim() || !createForm.client_id.trim()) {
    ElMessage.warning('请填写凭据名称和 Client ID')
    return
  }
  savingCredential.value = true
  try {
    await api.post('/trakt/credentials', {
      name: createForm.name.trim(),
      client_id: createForm.client_id.trim(),
      client_secret: createForm.client_secret.trim() || null,
      redirect_uri: createForm.redirect_uri.trim() || 'urn:ietf:wg:oauth:2.0:oob'
    })
    ElMessage.success('凭据已保存，Client ID / Secret 不会再显示')
    createVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    savingCredential.value = false
  }
}

function openEdit(row) {
  editForm.id = row.id
  editForm.name = row.name
  editForm.client_id = ''
  editForm.client_secret = ''
  editForm.clear_secret = false
  editForm.redirect_uri = row.redirect_uri || 'urn:ietf:wg:oauth:2.0:oob'
  editVisible.value = true
}

async function saveEdit() {
  if (!editForm.name.trim()) {
    ElMessage.warning('请填写凭据名称')
    return
  }
  savingCredential.value = true
  try {
    const payload = {
      name: editForm.name.trim(),
      redirect_uri: editForm.redirect_uri.trim() || 'urn:ietf:wg:oauth:2.0:oob',
      clear_secret: editForm.clear_secret
    }
    if (editForm.client_id.trim()) payload.client_id = editForm.client_id.trim()
    if (editForm.client_secret.trim()) payload.client_secret = editForm.client_secret.trim()
    await api.patch(`/trakt/credentials/${editForm.id}`, payload)
    ElMessage.success('凭据已更新')
    editVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    savingCredential.value = false
  }
}

async function makeDefault(row) {
  try {
    await api.post(`/trakt/credentials/${row.id}/default`)
    ElMessage.success(`已将「${row.name}」设为默认凭据`)
    await load()
  } catch (error) {
    ElMessage.error(errMsg(error))
  }
}

async function removeCredential(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除凭据「${row.name}」吗？如果有账号正在使用，需要先解绑或重新授权。`,
      '删除凭据',
      { type: 'warning' }
    )
    await api.delete(`/trakt/credentials/${row.id}`)
    ElMessage.success('已删除')
    await load()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(errMsg(error))
  }
}

onMounted(load)
</script>

<style scoped>
.stat-mini { display: flex; gap: 22px; padding: 13px 15px; background: var(--glass-soft); border: 1px solid var(--glass-border); border-radius: 16px; }
.stat-mini div { display: flex; flex-direction: column; }
.stat-mini b { font-size: 18px; }
.stat-mini span { font-size: 11.5px; color: var(--muted); }
.scheduler-box { padding: 13px 15px; border: 1px dashed var(--line-strong); border-radius: 16px; background: var(--glass-soft); }
.stat-mini b { color: var(--ink-strong); }
.threshold-item :deep(.el-form-item__content) { padding-bottom: 6px; }
.info-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px dashed var(--line);
  font-size: 12.5px;
}
.info-label { color: var(--muted); }
.settings-top, .settings-bottom { align-items: stretch; }
.settings-top > .panel, .settings-bottom > .panel { height: 100%; }
.db-card { display: flex; flex-direction: column; }
.db-card > .panel-pad { flex: 1; display: flex; flex-direction: column; }
.db-card .db-actions { margin-top: auto; }
</style>
