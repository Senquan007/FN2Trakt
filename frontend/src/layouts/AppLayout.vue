<template>
  <el-container class="shell">
    <el-aside
      :width="isMobile ? '0px' : collapsed ? '80px' : '228px'"
      class="sidebar"
      :class="{ 'mobile-open': isMobile && mobileOpen }"
    >
      <div class="logo" :class="{ compact: collapsed && !isMobile }">
        <div class="logo-mark"><img src="/logo.png" alt="FN2Trakt" /></div>
        <transition name="fade">
          <div v-if="!collapsed || isMobile" class="logo-text">
            <div class="logo-title">FN<span>2</span>Trakt</div>
            <div class="logo-sub">飞牛观影同步</div>
          </div>
        </transition>
      </div>

      <el-menu
        :default-active="$route.path"
        :collapse="collapsed && !isMobile"
        router
        class="nav"
        background-color="transparent"
        text-color="var(--muted)"
        active-text-color="var(--ink-strong)"
        @select="mobileOpen = false"
      >
        <el-menu-item v-for="item in menu" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>

      <div v-if="!collapsed || isMobile" class="sidebar-foot">
        <div class="foot-card">
          <div class="flex-between">
            <span class="tiny foot-label">飞牛数据库</span>
            <span class="dot" :style="{ background: fntvOk ? 'var(--success)' : 'var(--danger)' }"></span>
          </div>
          <div class="foot-state">{{ fntvOk ? '已连接' : '未连接' }}</div>
          <div class="tiny foot-desc">{{ fntvLabel }}</div>
        </div>
        <div class="version">v3.0.0 · local</div>
      </div>
    </el-aside>

    <div v-if="isMobile && mobileOpen" class="mobile-mask" @click="mobileOpen = false"></div>

    <el-container class="content">
      <el-header class="topbar">
        <div class="flex" style="gap: 14px">
          <el-button text circle class="toggle" @click="toggleNav">
            <el-icon :size="18"><Fold v-if="!collapsed && !isMobile" /><Expand v-else /></el-icon>
          </el-button>
          <div>
            <div class="top-title">{{ $route.meta.title || '仪表盘' }}</div>
            <div class="top-sub">{{ today }}</div>
          </div>
        </div>

        <div class="flex" style="gap: 10px">
          <ThemeToggle />
          <el-tooltip :content="fntvOk ? '飞牛影视数据库连接正常' : '飞牛影视数据库不可用，请前往系统设置'">
            <div class="conn-chip" :class="{ bad: !fntvOk }" @click="$router.push('/settings')">
              <span class="dot"></span>
              {{ fntvOk ? '飞牛已连接' : '飞牛未连接' }}
            </div>
          </el-tooltip>

          <el-dropdown trigger="click" @command="onCommand">
            <div class="user-chip">
              <div class="avatar">{{ (auth.user?.username || '?').slice(0, 1).toUpperCase() }}</div>
              <div class="user-meta">
                <div class="user-name">{{ auth.user?.username }}</div>
                <div class="user-role">{{ auth.isAdmin ? '管理员' : '用户' }}</div>
              </div>
              <el-icon><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="password" :icon="Lock">修改密码</el-dropdown-item>
                <el-dropdown-item command="logout" :icon="SwitchButton" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>

    <el-dialog append-to-body v-model="passwordVisible" title="修改密码" width="420px">
      <el-form label-position="top">
        <el-form-item label="原密码">
          <el-input v-model="passwordForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码（至少 6 位）">
          <el-input v-model="passwordForm.new_password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordVisible = false">取消</el-button>
        <el-button type="primary" :loading="passwordSaving" @click="changePassword">保存</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Lock, SwitchButton } from '@element-plus/icons-vue'
import api, { errMsg } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import ThemeToggle from '@/components/ThemeToggle.vue'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const collapsed = ref(false)
const isMobile = ref(window.innerWidth < 900)
const mobileOpen = ref(false)
const fntvOk = ref(false)
const fntvLabel = ref('检查中…')

const passwordVisible = ref(false)
const passwordSaving = ref(false)
const passwordForm = reactive({ old_password: '', new_password: '' })

const menu = computed(() => {
  const items = [
    { path: '/', title: '仪表盘', icon: 'DataLine' },
    { path: '/history', title: '观看记录', icon: 'Film' }
  ]
  if (auth.isAdmin) {
    items.push({ path: '/match', title: '媒体匹配', icon: 'Connection' })
  }
  items.push(
    { path: '/trakt', title: 'Trakt 绑定', icon: 'Link' },
    { path: '/logs', title: '同步记录', icon: 'Refresh' },
    { path: '/developer', title: auth.isAdmin ? '开发者' : 'API 访问', icon: 'Cpu' }
  )
  if (auth.isAdmin) {
    items.push(
      { path: '/users', title: '用户管理', icon: 'User' },
      { path: '/settings', title: '系统设置', icon: 'Setting' }
    )
  }
  return items
})

const today = computed(() =>
  new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })
)

function toggleNav() {
  if (isMobile.value) {
    mobileOpen.value = !mobileOpen.value
  } else {
    collapsed.value = !collapsed.value
  }
}

function onResize() {
  isMobile.value = window.innerWidth < 900
  if (!isMobile.value) mobileOpen.value = false
}

async function loadFntv() {
  try {
    const data = await api.get('/fntv/status')
    fntvOk.value = !!data.database?.ok
    const counts = data.summary?.item_types || {}
    fntvLabel.value = fntvOk.value
      ? `${data.cached?.plays || 0} 条播放 · ${data.cached?.completed || 0} 条已看`
      : data.database?.error || '无法读取数据库'
  } catch {
    fntvOk.value = false
    fntvLabel.value = '状态检查失败'
  }
}

async function onCommand(command) {
  if (command === 'logout') {
    await ElMessageBox.confirm('确定要退出登录吗？', '退出登录', { type: 'warning' })
    await auth.logout()
    router.push('/login')
  } else if (command === 'password') {
    passwordForm.old_password = ''
    passwordForm.new_password = ''
    passwordVisible.value = true
  }
}

async function changePassword() {
  if (!passwordForm.old_password || passwordForm.new_password.length < 6) {
    ElMessage.warning('请填写原密码，新密码至少 6 位')
    return
  }
  passwordSaving.value = true
  try {
    await api.post('/auth/password', passwordForm)
    ElMessage.success('密码已更新')
    passwordVisible.value = false
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    passwordSaving.value = false
  }
}

onMounted(() => {
  loadFntv()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => window.removeEventListener('resize', onResize))
</script>

<style scoped>
.shell {
  min-height: 100vh;
  padding: 14px;
  gap: 14px;
  background: transparent;
}

.sidebar {
  height: calc(100vh - 28px);
  position: sticky;
  top: 14px;
  flex: none;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 20px;
  background: var(--glass);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-sm);
  transition: width 0.24s ease;
}

.logo {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 20px 18px 14px;
  min-height: 76px;
}
.logo.compact { padding: 20px 10px; justify-content: center; }
.logo-mark {
  width: 42px;
  height: 42px;
  flex: none;
  border-radius: 11px;
  display: grid;
  place-items: center;
  font-weight: 800;
  font-size: 14px;
  letter-spacing: -0.02em;
  color: var(--on-primary);
  background: var(--bg-2);
  overflow: hidden;
  box-shadow: 0 8px 18px -12px rgba(16, 24, 40, 0.35);
}
.logo-mark img { width: 100%; height: 100%; display: block; object-fit: cover; }
.logo-title { color: var(--ink-strong); font-weight: 750; font-size: 16px; letter-spacing: -0.025em; }
.logo-title span { color: var(--primary); }
.logo-sub { color: var(--muted); font-size: 11px; margin-top: 2px; letter-spacing: 0.02em; }

.nav {
  border-right: none;
  flex: none;
  margin: 2px 10px 0;
  padding: 4px;
  border-radius: 12px;
  background: var(--nav-bg);
}
.nav.el-menu--collapse {
  width: auto;
  margin-left: 8px;
  margin-right: 8px;
}
.nav.el-menu--collapse :deep(.el-menu-item) {
  width: 100%;
  padding: 0 !important;
  justify-content: center;
}
.nav.el-menu--collapse :deep(.el-menu-tooltip__trigger) {
  width: 100%;
  padding: 0 !important;
  display: flex;
  justify-content: center;
}
.nav.el-menu--collapse :deep(.el-menu-item .el-icon) {
  margin: 0;
}
.nav :deep(.el-menu-item) {
  height: 40px;
  line-height: 40px;
  border-radius: 8px;
  margin-bottom: 1px;
  font-weight: 600;
  font-size: 13px;
  color: var(--muted);
  background: transparent;
  transition: background 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
}
.nav :deep(.el-menu-item:last-child) { margin-bottom: 0; }
.nav :deep(.el-menu-item:hover) {
  background: color-mix(in srgb, var(--glass) 55%, transparent);
  color: var(--ink);
}
.nav :deep(.el-menu-item.is-active) {
  background: var(--glass);
  color: var(--ink-strong);
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.06), 0 4px 12px -8px rgba(16, 24, 40, 0.28);
}
.nav :deep(.el-menu-item.is-active .el-icon) { color: var(--primary); }
.nav :deep(.el-menu-item .el-icon) { font-size: 16px; color: var(--muted-2); }
.nav :deep(.el-menu-item:hover .el-icon) { color: var(--muted); }

.sidebar-foot { padding: 10px 14px 14px; margin-top: auto; }
.foot-card {
  border-radius: 12px;
  padding: 11px 12px;
  background: var(--glass-soft);
  border: 1px solid var(--glass-border);
}
.foot-label { color: var(--muted); }
.foot-state { color: var(--ink); font-size: 12.5px; font-weight: 650; margin: 5px 0 1px; }
.foot-desc { color: var(--muted-2); }
.version { color: var(--muted-2); font-size: 10.5px; text-align: center; margin-top: 10px; }

.content { min-width: 0; display: flex; flex-direction: column; }

.topbar {
  height: 60px;
  margin: 14px 14px 0;
  padding: 0 12px;
  border-radius: 14px;
  background: var(--glass);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-sm);
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 14px;
  z-index: 20;
}
.toggle { color: var(--muted); }
.top-title { font-weight: 700; font-size: 16px; letter-spacing: -0.02em; color: var(--ink-strong); line-height: 1.2; }
.top-sub { font-size: 11px; color: var(--muted); margin-top: 2px; }

.conn-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--muted);
  background: var(--glass-soft);
  border: 1px solid var(--glass-border);
  border-radius: 999px;
  padding: 5px 10px;
  cursor: pointer;
}
.conn-chip .dot { background: var(--success); box-shadow: 0 0 0 3px var(--success-soft); }
.conn-chip.bad { color: var(--danger-ink); }
.conn-chip.bad .dot { background: var(--danger); box-shadow: 0 0 0 3px var(--danger-soft); }

.user-chip {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 4px 8px 4px 4px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.15s ease;
}
.user-chip:hover { background: var(--glass-soft); }
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  color: var(--on-primary);
  font-weight: 700;
  font-size: 13px;
  background: var(--primary-grad);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.4);
}
.user-name { font-size: 12.5px; font-weight: 650; line-height: 1.2; color: var(--ink); }
.user-role { font-size: 10.5px; color: var(--muted); }

.main { padding: 0; background: transparent; }

.mobile-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.34);
  backdrop-filter: blur(3px);
  z-index: 29;
}

@media (max-width: 900px) {
  .shell { padding: 0; gap: 0; }
  .sidebar {
    position: fixed;
    left: 8px;
    top: 8px;
    bottom: 8px;
    z-index: 30;
    width: 228px !important;
    height: auto;
    border-radius: 18px;
    transform: translateX(calc(-100% - 16px));
    transition: transform 0.24s ease;
  }
  .sidebar.mobile-open { transform: none; }
  .topbar {
    margin: 8px 10px 0;
    padding: 0 10px;
    height: 56px;
    border-radius: 14px;
    top: 8px;
  }
  .conn-chip { display: none; }
  .user-meta { display: none; }
}
</style>
