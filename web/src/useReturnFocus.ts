import { useRef } from 'react'

/**
 * Give focus back to whatever had it before a dialog opened.
 *
 * Radix does this by itself only when the dialog is opened by its own
 * Trigger. Our dialogs are opened from state, so without this the focus
 * would be dropped when a dialog closes, and a keyboard user would have to
 * start again from the top of the page.
 */
export function useReturnFocus() {
  const opener = useRef<HTMLElement | null>(null)
  return {
    // Called just before the dialog takes the focus.
    onOpenAutoFocus: () => {
      opener.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null
    },
    onCloseAutoFocus: (event: Event) => {
      const element = opener.current
      if (element?.isConnected) {
        event.preventDefault()
        element.focus()
      }
    },
  }
}
