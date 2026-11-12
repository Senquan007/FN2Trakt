import dayjs from 'dayjs'

export function formatDateTime(value) {
  if (!value) return '—'
  return dayjs(value).format('YYYY-MM-DD HH:mm')
}

export function formatDate(value) {
  if (!value) return '—'
  return dayjs(value).format('YYYY-MM-DD')
}

export function formatSeconds(total) {
  if (total === null || total === undefined) return '—'
  const seconds = Math.max(0, Math.round(total))
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`
}

export const SYNC_STATUS = {
  success: { label: '已同步', type: 'success' },
  synced: { label: '已同步', type: 'success' },
  pending: { label: '待同步', type: 'warning' },
  failed: { label: '同步失败', type: 'danger' },
  blocked: { label: '待匹配', type: 'info' },
  partial: { label: '部分成功', type: 'warning' },
  queued: { label: '排队中', type: 'info' },
  running: { label: '进行中', type: 'info' },
  skipped: { label: '已跳过', type: 'info' },
  incomplete: { label: '未看完', type: 'info' }
}

export const MATCH_STATUS = {
  auto: { label: '自动匹配', type: 'success' },
  manual: { label: '手动匹配', type: 'primary' },
  unmatched: { label: '未匹配', type: 'warning' },
  rejected: { label: '已忽略', type: 'info' }
}

export function typeLabel(type) {
  return { Movie: '电影', Episode: '剧集', Video: '视频', Unknown: '未知' }[type] || type
}

export function matchChipClass(status) {
  return {
    auto: 'success',
    manual: 'info',
    unmatched: 'warning',
    rejected: 'muted'
  }[status] || 'muted'
}

export function syncChipClass(status) {
  return {
    success: 'success',
    synced: 'success',
    failed: 'danger',
    pending: 'warning',
    blocked: 'info',
    incomplete: 'muted'
  }[status] || 'muted'
}
