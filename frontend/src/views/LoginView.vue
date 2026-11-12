<template>
  <div class="auth-wrapper">
    <ThemeToggle class="auth-theme" />
    <div class="auth-card">
      <div class="auth-logo"><img src="/logo.png" alt="FN2Trakt" /></div>
      <h1 class="auth-title">欢迎回来</h1>
      <p class="auth-sub">登录 <b class="brand-gradient">FN2Trakt</b>，把飞牛影视的观看记录同步到 Trakt。</p>

      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" size="large" placeholder="请输入用户名" autocomplete="username" @keyup.enter="submit">
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            size="large"
            type="password"
            show-password
            placeholder="请输入密码"
            autocomplete="current-password"
            @keyup.enter="submit"
          >
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-button type="primary" size="large" class="w-full" :loading="loading" @click="submit">登录</el-button>
      </el-form>

      <div class="hint">
        <el-icon><InfoFilled /></el-icon>
        <span>首次使用？系统会自动引导完成初始化与管理员创建。</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api, { errMsg } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import ThemeToggle from '@/components/ThemeToggle.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function submit() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await auth.login(form.username.trim(), form.password)
    ElMessage.success('登录成功')
    router.replace(route.query.redirect || '/')
  } catch (error) {
    ElMessage.error(errMsg(error))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.hint {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin-top: 22px;
  padding: 13px 15px;
  border-radius: 16px;
  background: var(--glass-soft);
  border: 1px solid var(--glass-border);
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.6;
}
.hint .el-icon { color: var(--primary-deep); margin-top: 2px; }
</style>
