import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
  timeout: 180000
})

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error?.response?.status
    if (status === 401) {
      const path = window.location.pathname
      if (path !== '/login' && path !== '/setup') {
        window.location.assign('/login')
      }
    }
    return Promise.reject(error)
  }
)

export function errMsg(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg || d).join('; ')
  return error?.message || '请求失败，请稍后重试'
}

export default api
