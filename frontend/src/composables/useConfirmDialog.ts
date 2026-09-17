// @ts-ignore - auto-imported by Nuxt UI Vite plugin
const useOverlay = globalThis.useOverlay
import ConfirmDialog from '../components/ConfirmDialog.vue'

export interface ConfirmOptions {
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  color?: 'error' | 'warning' | 'neutral'
}

export const useConfirmDialog = () => {
  const overlay = useOverlay()

  const confirm = (options: ConfirmOptions): Promise<boolean> => {
    const modal = overlay.create(ConfirmDialog, {
      destroyOnClose: true,
      props: options
    })

    return modal.open()
  }

  return { confirm }
}
