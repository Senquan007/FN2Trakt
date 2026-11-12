<template>
  <div class="auth-wrapper" style="align-items: flex-start; padding-top: 6vh">
    <ThemeToggle class="auth-theme" />
    <div class="setup-wrap">
      <div class="auth-card setup-card">
        <div class="flex" style="justify-content: space-between; align-items: flex-start">
          <div style="flex: 1; min-width: 0">
            <div class="auth-logo"><img src="/logo.png" alt="FN2Trakt" /></div>
            <h1 class="auth-title">初始化 FN2Trakt</h1>
            <p class="auth-sub">连接飞牛影视数据库，创建管理员，然后把观影记录同步到 Trakt。</p>
          </div>
          <span class="chip info" style="flex: none">首次启动</span>
        </div>

        <div class="db-card" :class="{ bad: status && !status.fntv?.ok }">
          <div class="flex" style="gap: 10px">
            <el-icon :size="18"><Coin /></el-icon>
            <div style="flex: 1; min-width: 0">
              <div class="db-title">
                {{ status?.fntv?.ok ? '飞牛数据库已识别' : '尚未连接飞牛数据库' }}
              </div>
              <div class="db-path mono">{{ status?.fntv?.path || '读取中…' }}</div>
            </div>
            <el-button text size="small" @click="loadStatus">重新检测</el-button>
          </div>
          <div v-if="status?.fntv?.ok" class="db-stats">
            <div><b>{{ status.fntv.counts?.item ?? 0 }}</b><span>媒体</span></div>
            <div><b>{{ status.fntv_users?.length ?? 0 }}</b><span>用户</span></div>
            <div><b>{{ status.fntv.counts?.item_user_play ?? 0 }}</b><span>播放记录</span></div>
          </div>
          <div v-else class="db-error">
            {{ status?.fntv?.error || '未找到 trimmedia.db' }}
            <div class="tiny" style="margin-top: 4px">
              请确认路径正确，或在初始化完成后到「系统设置」中修改。
            </div>
          </div>
        </div>

        <el-form label-position="top" class="mt-16" @submit.prevent="submit">
          <div class="grid grid-2">
            <el-form-item label="管理员用户名">
              <el-input v-model="form.username" size="large" placeholder="例如 admin" />
            </el-form-item>
            <el-form-item label="登录密码">
              <el-input v-model="form.password" size="large" type="password" show-password placeholder="至少 6 位" />
            </el-form-item>
          </div>
          <el-form-item label="确认密码">
            <el-input v-model="form.confirm" size="large" type="password" show-password placeholder="再次输入密码" />
          </el-form-item>
          <el-form-item label="绑定飞牛用户（推荐，之后可在用户管理中修改）">
            <el-select v-model="form.fn_user_guid" size="large" placeholder="选择你的飞牛账号" clearable style="width: 100%">
              <el-option v-for="u in status?.fntv_users || []" :key="u.guid" :label="u.username" :value="u.guid">
                <div class="flex-between">
                  <span>{{ u.username }}</span>
                  <span class="tiny muted">{{ u.is_admin ? '管理员' : '用户' }}</span>
                </div>
              </el-option>
            </el-select>
          </el-form-item>
          <el-button type="primary" size="large" class="w-full" :loading="loading" @click="submit">
            创建管理员并进入
          </el-button>
        </el-form>

        <div class="hint">
          下一步：在「Trakt 绑定」中填写自己的 Client ID / Secret，点击生成绑定码并授权。
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api, { errMsg } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import ThemeToggle from '@/components/ThemeToggle.vue'

const router = useRouter()
const auth = useAuthStore()
const status = ref(null)
const loading = ref(false)
const form = reactive({ username: 'admin', password: '', confirm: '', fn_user_guid: '' })

async function loadStatus() {
  try {
    status.value = await api.get('/setup/status')
    if (!status.value.needs_setup) {
      router.replace('/login')
    }
  } catch (error) {
    ElMessage.error(errMsg(error))
  }
}

async function submit() {
  if (form.username.trim().length < 2) {
    ElMessage.warning('用户名至少 2 个字符')
    return
  }
  if (form.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  if (form.password !== form.confirm) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  loading.value = true
  try {
    const data = await api.post('/setup', {
      username: form.username.trim(),
      password: form.password,
      fn_user_guid: form.fn_user_guid || null
    })
    auth.setUser(data.user)
    ElMessage.success('初始化完成，欢迎使用')
    router.replace('/')
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    loading.value = false
  }
}

onMounted(loadStatus)
</script>

<style scoped>
.setup-wrap { width: 100%; max-width: 760px; }
.setup-card { max-width: none; }
.db-card {
  border: 1px solid var(--glass-border);
  background: var(--glass-soft);
  border-radius: 18px;
  padding: 15px 17px;
  backdrop-filter: blur(12px);
}
.db-card.bad {
  background: var(--danger-soft);
  border-color: color-mix(in srgb, var(--danger) 25%, transparent);
}
.db-title { font-size: 13px; font-weight: 650; }
.db-path { font-size: 11.5px; color: var(--muted); margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.db-stats { display: flex; gap: 26px; margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--line-strong); }
.db-stats div { display: flex; flex-direction: column; }
.db-stats b { font-size: 19px; letter-spacing: -0.02em; }
.db-stats span { font-size: 11.5px; color: var(--muted); }
.db-error { margin-top: 10px; color: var(--danger-ink); font-size: 12.5px; }
.hint { margin-top: 18px; font-size: 12px; color: var(--muted); line-height: 1.6; }
</style>
