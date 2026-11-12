<template>
  <div class="theme-toggle" role="group" aria-label="切换主题">
    <button
      type="button"
      class="theme-btn"
      :class="{ active: theme.theme === 'light' }"
      title="亮色模式"
      aria-label="亮色模式"
      @click="theme.setTheme('light')"
    >
      <el-icon><Sunny /></el-icon>
    </button>
    <button
      type="button"
      class="theme-btn"
      :class="{ active: theme.theme === 'dark' }"
      title="暗黑模式"
      aria-label="暗黑模式"
      @click="theme.setTheme('dark')"
    >
      <el-icon><Moon /></el-icon>
    </button>
  </div>
</template>

<script setup>
import { useThemeStore } from '@/stores/theme'

const theme = useThemeStore()
</script>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 999px;
  background: var(--seg-bg);
  border: 1px solid var(--glass-border);
}
.theme-btn {
  width: 28px;
  height: 26px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--muted);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: background 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
  font-size: 13px;
}
.theme-btn:hover { color: var(--ink); }
.theme-btn.active {
  background: var(--glass);
  color: var(--primary);
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.08), 0 3px 8px -6px rgba(16, 24, 40, 0.3);
}
</style>
