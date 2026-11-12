import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api, { errMsg } from '@/api/client'

export function useSync() {
  const syncing = ref(false)
  const preview = reactive({ bound: false, summary: {}, samples: [] })

  async function loadPreview() {
    try {
      const data = await api.get('/sync/preview')
      Object.assign(preview, data)
    } catch {
      /* ignore */
    }
  }

  async function runSync(router) {
    syncing.value = true
    try {
      const data = await api.post('/sync/run', {})
      ElMessage.success(`同步任务已启动（#${data.run_id}），稍后可在同步记录中查看结果`)
      if (router) router.push('/logs')
    } catch (error) {
      ElMessage.error(errMsg(error))
    } finally {
      syncing.value = false
    }
  }

  return { syncing, preview, loadPreview, runSync }
}
