/**
 * Copy text to the clipboard.
 *
 * `navigator.clipboard` only exists in a secure context (HTTPS or localhost).
 * FN2Trakt is usually reached over plain HTTP on a LAN address, which is
 * exactly why "复制" silently failed for the API Token dialog.  The hidden
 * textarea + `document.execCommand('copy')` fallback still works there.
 */
export async function copyText(value) {
  const text = String(value ?? '')
  if (!text) return false

  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // fall through to the legacy path
    }
  }

  try {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.top = '-1000px'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    area.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    document.body.removeChild(area)
    return ok
  } catch {
    return false
  }
}

export function selectAll(event) {
  const target = event?.target
  if (target && typeof target.select === 'function') target.select()
}
