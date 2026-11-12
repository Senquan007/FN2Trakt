import { defineStore } from 'pinia'

const STORAGE_KEY = 'fn2t-theme'

function applyTheme(theme) {
  const root = document.documentElement
  root.dataset.theme = theme
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

export const useThemeStore = defineStore('theme', {
  state: () => ({ theme: 'light' }),
  getters: {
    isDark: (state) => state.theme === 'dark'
  },
  actions: {
    init() {
      let theme = document.documentElement.dataset.theme
      if (theme !== 'light' && theme !== 'dark') {
        try {
          theme = localStorage.getItem(STORAGE_KEY)
        } catch {
          theme = null
        }
      }
      if (theme !== 'light' && theme !== 'dark') {
        theme = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
      }
      this.setTheme(theme)
    },
    setTheme(theme) {
      const next = theme === 'dark' ? 'dark' : 'light'
      this.theme = next
      applyTheme(next)
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
        /* ignore storage failures */
      }
    },
    toggle() {
      this.setTheme(this.isDark ? 'light' : 'dark')
    }
  }
})
