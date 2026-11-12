import { onMounted, onUnmounted, ref } from 'vue'

export function useMediaQuery(query = '(max-width: 720px)') {
  const matches = ref(false)
  let mql = null

  const update = () => {
    if (mql) matches.value = mql.matches
  }

  onMounted(() => {
    mql = window.matchMedia(query)
    matches.value = mql.matches
    mql.addEventListener?.('change', update)
  })

  onUnmounted(() => {
    mql?.removeEventListener?.('change', update)
  })

  return matches
}
