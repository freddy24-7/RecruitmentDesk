import { useState } from 'react'
import type { Vacancy, VacancySections } from './api.ts'
import ConfirmDialog from './ConfirmDialog.tsx'
import {
  LIST_SECTIONS,
  OPTIONAL_SECTIONS,
  SECTION_NAMES,
  SECTION_ORDER,
  sameSections,
  toSections,
  toTexts,
} from './sections.ts'
import {
  useCancelVacancy,
  useResetVacancy,
  useSaveSections,
  useSubmitVacancy,
} from './vacancies.ts'

type Props = {
  vacancy: Vacancy
  sections: VacancySections
  /** Called after "Cancel vacancy" deleted the draft. */
  onCancelled: () => void
  /** Called after the draft was submitted. */
  onSubmitted: () => void
  /** For a submitted vacancy: leave the editor again. */
  onDone?: () => void
}

/**
 * Each section of the vacancy in an editable field (PRD F2). The same editor
 * is used for a draft and for a submitted vacancy; only the buttons differ.
 */
function VacancyEditor({
  vacancy,
  sections,
  onCancelled,
  onSubmitted,
  onDone,
}: Props) {
  const [texts, setTexts] = useState(() => toTexts(sections))
  const [confirming, setConfirming] = useState<'cancel' | 'reset' | null>(null)
  const save = useSaveSections(vacancy.id)
  const reset = useResetVacancy(vacancy.id)
  const submit = useSubmitVacancy(vacancy.id)
  const cancel = useCancelVacancy(vacancy.id)

  const isDraft = vacancy.status === 'draft'
  const edited = toSections(texts)
  const unsaved = !sameSections(edited, sections)
  const busy =
    save.isPending || reset.isPending || submit.isPending || cancel.isPending
  const problem = [cancel, submit, reset, save].find((m) => m.isError)?.error

  function clearProblems() {
    for (const mutation of [save, reset, submit, cancel]) {
      mutation.reset()
    }
  }

  async function saveEdits() {
    const saved = await save.mutateAsync(edited)
    if (saved.sections) {
      // Show the text as the server stored it (tidied).
      setTexts(toTexts(saved.sections))
    }
  }

  async function submitVacancy() {
    clearProblems()
    try {
      // Submit what is on the screen: unsaved edits are saved first.
      if (unsaved) {
        await saveEdits()
      }
      await submit.mutateAsync()
      onSubmitted()
    } catch {
      // The failed mutation holds the error, and it is shown below.
    }
  }

  async function resetToGenerated() {
    clearProblems()
    try {
      const restored = await reset.mutateAsync()
      if (restored.sections) {
        setTexts(toTexts(restored.sections))
      }
    } catch {
      // Shown below.
    }
  }

  async function cancelVacancy() {
    clearProblems()
    try {
      await cancel.mutateAsync()
      onCancelled()
    } catch {
      // Shown below.
    }
  }

  return (
    <form
      className="editor"
      onSubmit={(event) => {
        event.preventDefault()
        clearProblems()
        // A failure is held by the mutation and shown below.
        saveEdits().catch(() => undefined)
      }}
    >
      <p className="hint" role="status">
        Version {vacancy.version}
        {vacancy.edited ? ', edited by you' : ', as generated'}
        {unsaved ? '. You have unsaved changes.' : '.'}
      </p>

      {SECTION_ORDER.map((key) => {
        const id = `section-${key}`
        const isList = LIST_SECTIONS.has(key)
        return (
          <div className="field" key={key}>
            <label htmlFor={id}>
              {SECTION_NAMES[key]}
              {OPTIONAL_SECTIONS.has(key) && ' (optional)'}
            </label>
            {key === 'title' ? (
              <input
                id={id}
                type="text"
                value={texts[key]}
                onChange={(event) => setTexts({ ...texts, [key]: event.target.value })}
              />
            ) : (
              <textarea
                id={id}
                value={texts[key]}
                rows={isList ? 6 : 4}
                aria-describedby={isList ? `${id}-hint` : undefined}
                onChange={(event) => setTexts({ ...texts, [key]: event.target.value })}
              />
            )}
            {isList && (
              <p id={`${id}-hint`} className="hint">
                One item per line.
              </p>
            )}
          </div>
        )
      })}

      {problem && (
        <p role="alert" className="problem">
          {problem.message}
        </p>
      )}

      <div className="actions spread">
        <div className="actions">
          {isDraft && (
            <button
              type="button"
              className="danger"
              disabled={busy}
              onClick={() => setConfirming('cancel')}
            >
              Cancel vacancy
            </button>
          )}
          <button
            type="button"
            disabled={busy || (!vacancy.edited && !unsaved)}
            onClick={() => setConfirming('reset')}
          >
            Reset to generated
          </button>
        </div>
        <div className="actions">
          {onDone && (
            <button type="button" disabled={busy} onClick={onDone}>
              Stop editing
            </button>
          )}
          <button type="submit" disabled={busy || !unsaved}>
            {save.isPending ? 'Saving…' : 'Save changes'}
          </button>
          {isDraft && (
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => void submitVacancy()}
            >
              Submit vacancy
            </button>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirming === 'cancel'}
        onOpenChange={(open) => setConfirming(open ? 'cancel' : null)}
        title="Cancel this vacancy?"
        confirmLabel="Delete vacancy"
        cancelLabel="Keep vacancy"
        onConfirm={() => void cancelVacancy()}
      >
        <p>This permanently deletes:</p>
        <ul>
          <li>the vacancy “{sections.title || vacancy.parameters.title}”</li>
          <li>its generated text and all your edits</li>
        </ul>
        <p>This cannot be undone.</p>
      </ConfirmDialog>

      <ConfirmDialog
        open={confirming === 'reset'}
        onOpenChange={(open) => setConfirming(open ? 'reset' : null)}
        title="Reset to the generated text?"
        confirmLabel="Reset"
        cancelLabel="Keep my edits"
        onConfirm={() => void resetToGenerated()}
      >
        <p>
          This replaces every section with the text as the model wrote it. All
          your edits to this vacancy are lost, including unsaved changes.
        </p>
      </ConfirmDialog>
    </form>
  )
}

export default VacancyEditor
