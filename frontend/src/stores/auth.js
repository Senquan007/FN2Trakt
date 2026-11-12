import { defineStore } from 'pinia'
import api from '@/api/client'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    loaded: false
  }),
  getters: {
    isAdmin: (state) => state.user?.role === 'admin',
    isLoggedIn: (state) => !!state.user
  },
  actions: {
    async fetchMe() {
      try {
        const data = await api.get('/auth/me')
        this.user = data.user
      } catch {
        this.user = null
      } finally {
        this.loaded = true
      }
      return this.user
    },
    async login(username, password) {
      const data = await api.post('/auth/login', { username, password })
      this.user = data.user
      this.loaded = true
      return data.user
    },
    async logout() {
      try {
        await api.post('/auth/logout')
      } catch {
        /* ignore */
      }
      this.user = null
    },
    setUser(user) {
      this.user = user
    }
  }
})
