import * as AlertDialog from '@radix-ui/react-alert-dialog'
import type { ReactNode } from 'react'
import { useReturnFocus } from './useReturnFocus.ts'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  /** States exactly what will be lost. */
  children: ReactNode
  confirmLabel: string
  cancelLabel: string
  onConfirm: () => void
}

/**
 * Confirmation for a destructive action. An alert dialog traps focus, closes
 * on Escape, and puts the focus on the safe choice first.
 */
function ConfirmDialog({
  open,
  onOpenChange,
  title,
  children,
  confirmLabel,
  cancelLabel,
  onConfirm,
}: Props) {
  const returnFocus = useReturnFocus()

  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="dialog-overlay" />
        <AlertDialog.Content className="dialog" {...returnFocus}>
          <AlertDialog.Title>{title}</AlertDialog.Title>
          <AlertDialog.Description asChild>
            <div>{children}</div>
          </AlertDialog.Description>
          <div className="actions">
            <AlertDialog.Cancel asChild>
              <button type="button">{cancelLabel}</button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button type="button" className="danger" onClick={onConfirm}>
                {confirmLabel}
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  )
}

export default ConfirmDialog
