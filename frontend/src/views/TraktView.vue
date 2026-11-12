<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="page-title">Trakt 绑定</h2>
        <p class="page-sub">使用设备授权码把 Trakt 账号连接到当前 FN2Trakt 用户，无需回调地址。</p>
      </div>
      <div class="page-actions">
        <el-tag v-if="account" type="success" effect="light" round>已绑定 @{{ account.trakt_username }}</el-tag>
        <el-tag v-else type="warning" effect="light" round>未绑定</el-tag>
      </div>
    </div>

    <div class="grid grid-main">
      <div>
        <!-- bound account -->
        <div v-if="account" class="panel account-panel">
          <div class="account-hero">
            <img v-if="account.avatar_url" :src="account.avatar_url" class="account-avatar" alt="avatar" />
            <div v-else class="account-avatar fallback"><img src="/trakt-logo.svg" alt="Trakt" /></div>
            <div style="flex: 1; min-width: 0">
              <div class="account-name">@{{ account.trakt_username || 'trakt-user' }}</div>
              <div class="tiny muted">
                绑定于 {{ formatDateTime(account.authorized_at) }}
                <span v-if="account.token_expires_at"> · Token 有效期至 {{ formatDateTime(account.token_expires_at) }}</span>
              </div>
              <div class="flex" style="margin-top: 8px; gap: 8px; flex-wrap: wrap">
                <span class="chip" :class="account.status === 'active' ? 'success' : 'danger'">
                  <span class="dot"></span> {{ account.status === 'active' ? '授权有效' : '授权异常，请重新绑定' }}
                </span>
                <a v-if="account.trakt_slug" :href="`https://trakt.tv/users/${account.trakt_slug}`" target="_blank" class="tiny">
                  打开 Trakt 主页 ↗
                </a>
              </div>
            </div>
            <el-button :icon="RefreshRight" @click="startDevice">重新绑定</el-button>
          </div>
          <div v-if="account.last_error" class="account-error">
            {{ account.last_error }}
          </div>
          <div class="account-foot">
            <div class="tiny muted">
              同步时使用 {{ accountAppUser }} 的 Trakt 授权；Token 会在到期前自动刷新。
            </div>
            <el-button text type="danger" size="small" @click="unbind">解除绑定</el-button>
          </div>
        </div>

        <!-- unbound / generating -->
        <div v-else-if="!device" class="panel">
          <div class="panel-pad">
            <div class="empty" style="padding: 26px 10px 18px">
              <div class="trakt-logo"><img src="/trakt-logo.svg" alt="Trakt" /></div>
              <h3 style="margin: 12px 0 4px; color: var(--ink)">连接你的 Trakt 账号</h3>
              <p class="tiny" style="max-width: 440px; margin: 0 auto 18px">
                点击下方按钮生成 8 位授权码。验证码出现后会自动复制，
                5 秒后在新标签页打开 Trakt 授权页，在官网输入验证码并批准即可。
              </p>
              <el-button
                type="primary"
                size="large"
                :icon="Link"
                :loading="starting"
                :disabled="!credentialStatus?.configured"
                @click="startDevice"
              >
                生成 Trakt 授权码
              </el-button>
              <div v-if="!credentialStatus?.configured" class="tiny" style="color: #b26a00; margin-top: 12px">
                <template v-if="isAdmin">请先在「系统设置」中添加 Trakt 应用凭据</template>
                <template v-else>管理员还没有配置 Trakt 应用凭据，请联系管理员</template>
              </div>
            </div>
          </div>
        </div>

        <!-- device code flow -->
        <transition name="fade">
          <div v-if="device && device.status === 'pending'" class="panel device-panel mt-16">
            <div class="panel-pad">
              <div class="flex-between">
                <div>
                  <h3 class="panel-title"><el-icon><Key /></el-icon> 在 Trakt 上输入授权码</h3>
                  <p class="panel-desc">授权码 {{ countdownText }} 后过期</p>
                </div>
                <span class="chip warning">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  等待授权
                </span>
              </div>

              <div class="device-code" style="margin-top: 16px">{{ device.user_code }}</div>

              <div v-if="jumpOpened" class="auto-hint done">
                <el-icon><CircleCheckFilled /></el-icon>
                <span>已在新标签页打开 Trakt。本页会继续保持轮询，授权成功后自动完成绑定。</span>
              </div>
              <div v-else-if="jumpBlocked" class="auto-hint">
                <el-icon><WarningFilled /></el-icon>
                <span>浏览器拦截了新标签页，请点击下方「在新标签页打开」重试。</span>
              </div>
              <div v-else-if="!jumpPending && copyState === 'copied'" class="auto-hint done">
                <el-icon><CircleCheckFilled /></el-icon>
                <span>授权码已复制。自动跳转已取消，可点击下方按钮在新标签页打开 Trakt。</span>
              </div>
              <div v-else-if="!jumpPending && copyState === 'failed'" class="auto-hint">
                <el-icon><WarningFilled /></el-icon>
                <span>浏览器未允许自动复制，请手动选择授权码后再打开 Trakt。</span>
              </div>

              <div class="device-actions">
                <el-button :icon="CopyDocument" @click="handleManualCopy">复制授权码</el-button>
                <el-button type="primary" :icon="TopRight" @click="openAuthPage">在新标签页打开</el-button>
              </div>

              <div class="steps mt-16">
                <div class="step-item">
                  <span class="step-num" :class="{ done: copyState === 'copied' }">1</span>
                  <div class="step-body">
                    验证码显示后会自动复制，顶部提示 <b>5 秒</b>后在新标签页打开 Trakt。
                  </div>
                </div>
                <div class="step-item">
                  <span class="step-num">2</span>
                  <div class="step-body">
                    在 Trakt 页面粘贴授权码 <b class="mono">{{ device.user_code }}</b>，点击 Continue。
                  </div>
                </div>
                <div class="step-item">
                  <span class="step-num">3</span>
                  <div class="step-body">
                    点击 <b>Approve</b> 授权。FN2Trakt 页面会继续轮询，成功后自动完成绑定。
                  </div>
                </div>
              </div>
              <div class="tiny muted mt-8" style="line-height: 1.7">
                5 秒后会在新标签页打开 Trakt，当前页面保持不动并继续检测授权结果。
              </div>

              <div class="wait-bar">
                <div class="wait-fill" :style="{ width: progressPercent + '%' }"></div>
              </div>
            </div>
          </div>
        </transition>

        <!-- authorized success -->
        <transition name="fade">
          <div v-if="device && device.status === 'authorized'" class="panel mt-16 success-panel">
            <div class="panel-pad" style="text-align: center">
              <el-icon :size="42" color="#10b981"><CircleCheckFilled /></el-icon>
              <h3 style="margin: 10px 0 4px">授权成功</h3>
              <p class="tiny muted">Trakt 账号已绑定，当前页面即将刷新。</p>
            </div>
          </div>
        </transition>

        <div v-if="device && ['expired', 'denied', 'error'].includes(device.status)" class="mt-16">
          <el-alert
            :title="device.status === 'expired' ? '授权码已过期' : device.status === 'denied' ? '授权被拒绝' : '授权失败'"
            :description="device.error || '请重新生成授权码'"
            type="error"
            show-icon
            :closable="false"
          />
        </div>

        <!-- account list for admin -->
        <div v-if="isAdmin" class="panel mt-16">
          <div class="panel-head">
            <div>
              <h3 class="panel-title"><el-icon><UserFilled /></el-icon> 全部 Trakt 绑定</h3>
              <p class="panel-desc">每个 FN2Trakt 用户独立绑定一个 Trakt 账号</p>
            </div>
          </div>
          <el-table :data="accounts" style="width: 100%" empty-text="还没有任何绑定">
            <el-table-column label="站内用户" prop="user.username" min-width="140" />
            <el-table-column label="飞牛用户" min-width="140">
              <template #default="{ row }">{{ row.user.fn_username || '未绑定' }}</template>
            </el-table-column>
            <el-table-column label="Trakt 账号" min-width="160">
              <template #default="{ row }">
                <span v-if="row.account">@{{ row.account.trakt_username }}</span>
                <span v-else class="muted">未绑定</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <span v-if="row.account" class="chip" :class="row.account.status === 'active' ? 'success' : 'danger'">
                  {{ row.account.status === 'active' ? '正常' : '需重新授权' }}
                </span>
                <span v-else class="chip muted">未绑定</span>
              </template>
            </el-table-column>
            <el-table-column label="授权时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.account?.authorized_at) }}</template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <!-- right column -->
      <div>
        <div class="panel">
          <div class="panel-head">
            <div>
              <h3 class="panel-title"><el-icon><Lock /></el-icon> 当前应用凭据</h3>
              <p class="panel-desc">凭据由管理员统一维护，普通用户不可见</p>
            </div>
            <span class="chip" :class="credentialStatus?.configured ? 'success' : 'warning'">
              {{ credentialStatus?.configured ? '已配置' : '未配置' }}
            </span>
          </div>
          <div class="panel-pad">
            <template v-if="isAdmin">
              <div class="info-row">
                <span class="info-label">凭据名称</span>
                <span>{{ credentialStatus?.name || '—' }}</span>
              </div>
              <div class="info-row">
                <span class="info-label">Client Secret</span>
                <span>{{ credentialStatus?.has_secret ? '已设置' : '未设置（PKCE 正常）' }}</span>
              </div>
              <div class="info-row" style="border-bottom: none">
                <span class="info-label">来源</span>
                <span>{{
                  credentialStatus?.source === 'environment'
                    ? '环境变量'
                    : credentialStatus?.source === 'database'
                      ? '系统设置'
                      : '未配置'
                }}</span>
              </div>
            </template>
            <div v-else class="tiny muted" style="line-height: 1.7">
              应用凭据由管理员统一配置，你无需填写 Client ID / Secret，直接完成设备授权即可。
            </div>

            <div v-if="isAdmin" class="mt-16">
              <el-button type="primary" plain :icon="Setting" @click="router.push('/settings')">
                前往系统设置管理凭据
              </el-button>
            </div>
            <div v-else class="tiny muted mt-16" style="line-height: 1.7">
              如果需要更换 Trakt 应用，请联系管理员。你只需要完成上面的设备授权。
            </div>
          </div>
        </div>

        <div class="panel mt-16">
          <div class="panel-head">
            <h3 class="panel-title"><el-icon><InfoFilled /></el-icon> 授权说明</h3>
          </div>
          <div class="panel-pad" style="padding-top: 12px">
            <div class="info-row">
              <span class="info-label">授权方式</span>
              <span>OAuth Device Code</span>
            </div>
            <div class="info-row">
              <span class="info-label">验证地址</span>
              <span class="mono tiny">auth.trakt.tv/activate</span>
            </div>
            <div class="info-row">
              <span class="info-label">授权码有效期</span>
              <span>10 分钟</span>
            </div>
            <div class="info-row">
              <span class="info-label">Token 有效期</span>
              <span>自动刷新</span>
            </div>
            <div class="info-row" style="border-bottom: none">
              <span class="info-label">上传内容</span>
              <span>观看历史（watch history）</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <Teleport to="body">
    <transition name="fade">
      <div v-if="jumpPending" class="jump-toast">
        <el-icon class="jump-icon"><CircleCheckFilled /></el-icon>
        <span v-if="copyState === 'copied'">已自动复制授权码，<b>{{ jumpSeconds }}s</b> 后在新标签页打开 Trakt</span>
        <span v-else>授权码已生成，请手动复制，<b>{{ jumpSeconds }}s</b> 后在新标签页打开 Trakt</span>
        <el-button text size="small" @click="jumpNow">立即跳转</el-button>
        <el-button text size="small" @click="cancelJump">取消</el-button>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshRight, Setting } from '@element-plus/icons-vue'
import api, { errMsg } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'

const auth = useAuthStore()
const router = useRouter()
const isAdmin = computed(() => auth.isAdmin)
const credentialStatus = ref(null)
const account = ref(null)
const accounts = ref([])
const accountAppUser = ref('')
const device = ref(null)
const starting = ref(false)
const countdown = ref(0)
const totalSeconds = ref(600)

const copyState = ref('')
const jumpPending = ref(false)
const jumpSeconds = ref(5)
const jumpUrl = ref('')
const jumpOpened = ref(false)
const jumpBlocked = ref(false)

let pollTimer = null
let countdownTimer = null
let jumpTimer = null

const countdownText = computed(() => {
  const s = Math.max(0, countdown.value)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
})
const progressPercent = computed(() => {
  if (!totalSeconds.value) return 0
  return Math.max(0, Math.min(100, (countdown.value / totalSeconds.value) * 100))
})

async function load() {
  try {
    const [status, accountData] = await Promise.all([
      api.get('/trakt/credential-status'),
      api.get('/trakt/account')
    ])
    credentialStatus.value = status
    account.value = accountData.account
    accountAppUser.value = auth.user?.username || ''
    if (isAdmin.value) {
      const list = await api.get('/trakt/accounts')
      accounts.value = list.items
    }
  } catch (error) {
    ElMessage.error(errMsg(error))
  }
}

function stopTimers() {
  if (pollTimer) clearInterval(pollTimer)
  if (countdownTimer) clearInterval(countdownTimer)
  pollTimer = null
  countdownTimer = null
}

function clearJumpTimer() {
  if (jumpTimer) clearInterval(jumpTimer)
  jumpTimer = null
}

function openTraktTab(url) {
  try {
    const win = window.open(url, '_blank')
    if (!win) return false
    try {
      win.opener = null
    } catch {
      /* ignore */
    }
    return true
  } catch {
    return false
  }
}

function cancelJump() {
  clearJumpTimer()
  jumpPending.value = false
}

function jumpNow() {
  clearJumpTimer()
  const url = jumpUrl.value
  jumpPending.value = false
  if (!url) return
  if (openTraktTab(url)) {
    jumpOpened.value = true
    jumpBlocked.value = false
  } else {
    jumpOpened.value = false
    jumpBlocked.value = true
    ElMessage.warning('浏览器拦截了新标签页，请点击下方「在新标签页打开」')
  }
}

async function copyDeviceCode() {
  try {
    await navigator.clipboard.writeText(device.value?.user_code || '')
    return true
  } catch {
    return false
  }
}

function startJumpCountdown(url, copied, budgetMs) {
  clearJumpTimer()
  jumpUrl.value = url
  copyState.value = copied ? 'copied' : 'failed'
  jumpSeconds.value = 5
  jumpPending.value = true
  // 浏览器只允许在点击后的短暂激活窗口内自动打开标签页。
  // 把 5 步倒计时压缩进这个窗口，既保留“等待后跳转”的观感，
  // 又避免 5 秒整点时被弹窗拦截。
  const step = Math.max(160, Math.round(budgetMs / 5))
  jumpTimer = setInterval(() => {
    jumpSeconds.value -= 1
    if (jumpSeconds.value <= 0) jumpNow()
  }, step)
}

function persistDevice() {
  if (!device.value) {
    localStorage.removeItem('fn2t_device')
    return
  }
  localStorage.setItem(
    'fn2t_device',
    JSON.stringify({
      id: device.value.id,
      user_code: device.value.user_code,
      verification_url: device.value.verification_url,
      expires_at: device.value.expires_at
    })
  )
}

function startTimers() {
  stopTimers()
  countdownTimer = setInterval(() => {
    countdown.value = Math.max(0, countdown.value - 1)
    if (countdown.value <= 0) {
      device.value = { ...device.value, status: 'expired', error: '授权码已过期，请重新生成' }
      stopTimers()
      cancelJump()
      copyState.value = ''
      jumpOpened.value = false
      jumpBlocked.value = false
      persistDevice()
    }
  }, 1000)
  pollTimer = setInterval(pollDevice, 2000)
}

async function startDevice() {
  if (!credentialStatus.value?.configured) {
    ElMessage.warning(isAdmin.value ? '请先在系统设置中添加 Trakt 应用凭据' : '请联系管理员配置 Trakt 应用凭据')
    return
  }
  cancelJump()
  copyState.value = ''
  jumpOpened.value = false
  jumpBlocked.value = false
  starting.value = true
  const clickedAt = performance.now()
  try {
    const data = await api.post('/trakt/device/start')
    device.value = data
    countdown.value = data.seconds_remaining
    totalSeconds.value = data.seconds_remaining
    persistDevice()
    startTimers()
    // Wait until the code is actually rendered before copying and showing the
    // countdown. Two animation frames make sure the DOM has painted.
    await nextTick()
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    const copied = await copyDeviceCode()
    // Keep the destination tab closed until the countdown finishes. Chrome
    // keeps the click activation for ~5s, so open slightly before that
    // deadline; if it still gets blocked, the page offers a manual button.
    const elapsed = performance.now() - clickedAt
    const budget = Math.max(900, 4700 - elapsed)
    startJumpCountdown(data.verification_url, copied, budget)
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    starting.value = false
  }
}

async function pollDevice() {
  if (!device.value?.id) return
  try {
    const data = await api.get(`/trakt/device/${device.value.id}`)
    if (data.status === 'authorized') {
      device.value = { ...device.value, status: 'authorized' }
      stopTimers()
      cancelJump()
      copyState.value = ''
      jumpOpened.value = false
      jumpBlocked.value = false
      localStorage.removeItem('fn2t_device')
      ElMessage.success('Trakt 授权成功')
      await load()
      setTimeout(() => {
        device.value = null
      }, 1800)
    } else if (['expired', 'denied', 'error'].includes(data.status)) {
      device.value = { ...device.value, status: data.status, error: data.error }
      stopTimers()
      cancelJump()
      copyState.value = ''
      jumpOpened.value = false
      jumpBlocked.value = false
      localStorage.removeItem('fn2t_device')
    }
  } catch (error) {
    stopTimers()
    cancelJump()
    device.value = { ...device.value, status: 'error', error: errMsg(error) }
  }
}

async function handleManualCopy() {
  if (!device.value?.user_code) return
  const copied = await copyDeviceCode()
  copyState.value = copied ? 'copied' : 'failed'
  if (copied) ElMessage.success('已复制')
  else ElMessage.warning('复制失败，请手动选择授权码')
}

function openAuthPage() {
  cancelJump()
  const url = device.value?.verification_url
  if (!url) return
  if (openTraktTab(url)) {
    jumpOpened.value = true
    jumpBlocked.value = false
  } else {
    jumpOpened.value = false
    jumpBlocked.value = true
    ElMessage.warning('浏览器拦截了新标签页，请允许弹窗后重试')
  }
}

async function unbind() {
  try {
    await ElMessageBox.confirm('解除绑定后需要重新授权才能同步，确定继续吗？', '解除 Trakt 绑定', {
      type: 'warning',
      confirmButtonText: '解除绑定'
    })
    await api.delete('/trakt/account')
    ElMessage.success('已解除绑定')
    await load()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(errMsg(error))
  }
}

function restoreDevice() {
  const raw = localStorage.getItem('fn2t_device')
  if (!raw) return
  try {
    const saved = JSON.parse(raw)
    if (!saved.expires_at || new Date(saved.expires_at).getTime() <= Date.now()) {
      localStorage.removeItem('fn2t_device')
      return
    }
    device.value = { ...saved, status: 'pending' }
    totalSeconds.value = Math.max(1, Math.round((new Date(saved.expires_at).getTime() - Date.now()) / 1000))
    countdown.value = totalSeconds.value
    jumpPending.value = false
    copyState.value = ''
    jumpOpened.value = false
    jumpBlocked.value = false
    startTimers()
  } catch {
    localStorage.removeItem('fn2t_device')
  }
}

onMounted(async () => {
  await load()
  restoreDevice()
})

onBeforeUnmount(() => {
  stopTimers()
  cancelJump()
})
</script>

<style scoped>
.account-panel { overflow: hidden; }
.account-hero {
  display: flex;
  gap: 16px;
  align-items: center;
  padding: 22px;
  background:
    radial-gradient(520px 220px at 0% 0%, var(--primary-soft), transparent 70%),
    var(--glass-soft);
}
.account-avatar {
  width: 62px;
  height: 62px;
  border-radius: 18px;
  object-fit: cover;
  flex: none;
  box-shadow: 0 10px 26px -14px rgba(30, 41, 59, 0.5);
}
.account-avatar.fallback {
  display: grid;
  place-items: center;
  background: transparent;
  overflow: hidden;
}
.account-avatar.fallback img { width: 100%; height: 100%; display: block; object-fit: contain; }
.account-name { font-size: 20px; font-weight: 750; letter-spacing: -0.02em; color: var(--ink-strong); }
.account-error {
  padding: 9px 22px;
  background: var(--danger-soft);
  color: var(--danger-ink);
  font-size: 12px;
  border-top: 1px solid color-mix(in srgb, var(--danger) 20%, transparent);
}
.account-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px 22px;
  background: var(--glass-soft);
  border-top: 1px solid var(--line);
}
.trakt-logo {
  width: 58px;
  height: 58px;
  border-radius: 17px;
  margin: 0 auto;
  display: grid;
  place-items: center;
  font-size: 28px;
  font-weight: 800;
  color: #fff;
  background: transparent;
  overflow: hidden;
}
.trakt-logo img { width: 100%; height: 100%; display: block; object-fit: contain; }
.device-panel { border-color: color-mix(in srgb, var(--primary) 26%, transparent); box-shadow: 0 18px 40px -32px color-mix(in srgb, var(--primary) 45%, transparent); }
.device-actions { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
.device-actions .el-button { flex: 1; min-width: 150px; }
.auto-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 11px 13px;
  border-radius: 14px;
  background: var(--primary-soft);
  border: 1px solid color-mix(in srgb, var(--primary) 20%, transparent);
  color: var(--primary-deep);
  font-size: 12.5px;
  font-weight: 600;
}
.auto-hint.done {
  background: var(--success-soft);
  border-color: color-mix(in srgb, var(--success) 20%, transparent);
  color: var(--success-ink);
}
.jump-toast {
  position: fixed;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 2100;
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: calc(100vw - 32px);
  padding: 9px 12px;
  border-radius: 10px;
  background: var(--bg-2);
  border: 1px solid color-mix(in srgb, var(--primary) 16%, var(--glass-border));
  color: var(--ink);
  font-size: 12.5px;
  box-shadow: var(--shadow-sm);
}
.jump-toast .jump-icon { color: var(--success); font-size: 15px; }
.jump-toast b { color: var(--primary-deep); font-size: 13.5px; margin: 0 2px; }
.jump-toast .el-button { color: var(--primary-deep); margin-left: 2px; }
.jump-toast .el-button:hover { color: var(--primary-deep); background: var(--primary-soft); }
.wait-bar { height: 5px; background: var(--line); border-radius: 99px; margin-top: 18px; overflow: hidden; }
.wait-fill { height: 100%; background: linear-gradient(90deg, var(--primary), var(--primary-2)); transition: width 1s linear; }
.success-panel {
  border-color: color-mix(in srgb, var(--success) 30%, transparent);
  background: color-mix(in srgb, var(--success-soft) 70%, var(--glass));
}
.info-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px dashed var(--line);
  font-size: 12.5px;
}
.info-label { color: var(--muted); }
</style>
