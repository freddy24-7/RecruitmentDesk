import * as Dialog from '@radix-ui/react-dialog'
import { useState } from 'react'
import type { FormEvent } from 'react'
import type { Vacancy } from './api.ts'
import CandidateProgress from './CandidateProgress.tsx'
import { useReturnFocus } from './useReturnFocus.ts'
import { useGenerateCandidates } from './vacancies.ts'

export const MAX_CANDIDATES = 100

type Props = {
  vacancy: Vacancy
  open: boolean
  onOpenChange: (open: boolean) => void
  onViewCandidates: () => void
}

/** Choose how many candidates to generate, then follow the job (PRD F4). */
function GenerateCandidatesDialog({
  vacancy,
  open,
  onOpenChange,
  onViewCandidates,
}: Props) {
  const returnFocus = useReturnFocus()

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog" {...returnFocus}>
          <Dialog.Title>Generate candidates</Dialog.Title>
          <DialogBody
            vacancy={vacancy}
            onViewCandidates={() => {
              onOpenChange(false)
              onViewCandidates()
            }}
          />
          <Dialog.Close asChild>
            <button type="button" className="dialog-close" aria-label="Close">
              ×
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function DialogBody({
  vacancy,
  onViewCandidates,
}: {
  vacancy: Vacancy
  onViewCandidates: () => void
}) {
  const [text, setText] = useState('20')
  const [started, setStarted] = useState(false)
  const [checked, setChecked] = useState(false)
  const generate = useGenerateCandidates(vacancy.id)
  // Counted when the dialog opened: these are the ones that will be replaced.
  const [existing] = useState(vacancy.candidates.count)

  const count = Number(text)
  const valid =
    /^\d+$/.test(text.trim()) && count >= 1 && count <= MAX_CANDIDATES

  if (started) {
    return (
      <>
        <CandidateProgress vacancy={vacancy} onViewCandidates={onViewCandidates} />
        <Dialog.Description>
          You can close this window: the candidates keep being created.
        </Dialog.Description>
      </>
    )
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    setChecked(true)
    if (!valid) {
      return
    }
    generate.mutate(
      // The dialog below states what is replaced; submitting it is the confirmation.
      { count, replace: existing > 0 },
      { onSuccess: () => setStarted(true) },
    )
  }

  return (
    <form onSubmit={submit} noValidate>
      <Dialog.Description>
        Creates fictional candidates with a CV for this vacancy. All of it is
        synthetic data: no real people.
      </Dialog.Description>

      <div className="field">
        <label htmlFor="candidate-count">Number of candidates</label>
        <input
          id="candidate-count"
          type="text"
          inputMode="numeric"
          value={text}
          onChange={(event) => setText(event.target.value)}
          aria-invalid={checked && !valid ? true : undefined}
          aria-describedby="candidate-count-hint"
        />
        <p
          id="candidate-count-hint"
          className={checked && !valid ? 'problem' : 'hint'}
        >
          Choose a number from 1 to {MAX_CANDIDATES}.
        </p>
      </div>

      {existing > 0 && (
        <div className="flags" role="note">
          <p>
            <strong>
              This replaces the {existing} existing candidates of this vacancy.
            </strong>{' '}
            Their CVs are deleted and cannot be brought back.
            {vacancy.lists.exist &&
              ' The long list and short list made from them are deleted too.'}
          </p>
        </div>
      )}

      {generate.isError && (
        <p role="alert" className="problem">
          {generate.error.message}
        </p>
      )}

      <div className="actions">
        <Dialog.Close asChild>
          <button type="button">Cancel</button>
        </Dialog.Close>
        <button
          type="submit"
          className={existing > 0 ? 'danger' : 'primary'}
          disabled={generate.isPending}
        >
          {existing > 0 ? 'Replace candidates' : 'Generate'}
        </button>
      </div>
    </form>
  )
}

export default GenerateCandidatesDialog
