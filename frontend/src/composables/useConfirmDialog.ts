import ConfirmDialog from '../components/ConfirmDialog.vue'

// Note: useOverlay is auto-imported by the Nuxt UI Vite plugin
// (globally declared in auto-imports.d.ts). Do NOT import it explicitly
// and do NOT read it off globalThis -- both break at runtime or in types.

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
