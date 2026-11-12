import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import api from '@/api/client'

const routes = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true, title: '登录' } },
  { path: '/setup', name: 'setup', component: () => import('@/views/SetupView.vue'), meta: { public: true, title: '初始化' } },
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    children: [
      { path: '', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '仪表盘' } },
      { path: 'history', name: 'history', component: () => import('@/views/HistoryView.vue'), meta: { title: '观看记录' } },
      { path: 'match', name: 'match', component: () => import('@/views/MatchView.vue'), meta: { title: '媒体匹配', admin: true } },
      { path: 'trakt', name: 'trakt', component: () => import('@/views/TraktView.vue'), meta: { title: 'Trakt 绑定' } },
      { path: 'logs', name: 'logs', component: () => import('@/views/LogsView.vue'), meta: { title: '同步记录' } },
      { path: 'developer', name: 'developer', component: () => import('@/views/DeveloperView.vue'), meta: { title: '开发者' } },
      { path: 'users', name: 'users', component: () => import('@/views/UsersView.vue'), meta: { title: '用户管理', admin: true } },
      { path: 'settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { title: '系统设置', admin: true } }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    await auth.fetchMe()
  }

  if (to.meta.public) {
    try {
      const status = await api.get('/setup/status')
      if (status.needs_setup) {
        if (to.name !== 'setup') return { name: 'setup' }
      } else if (to.name === 'setup') {
        return auth.user ? { name: 'dashboard' } : { name: 'login' }
      }
    } catch {
      /* keep going */
    }
    return true
  }

  if (!auth.user) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.admin && !auth.isAdmin) {
    return { name: 'dashboard' }
  }
  return true
})

export default router
