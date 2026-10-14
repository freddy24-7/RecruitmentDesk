import * as Dialog from '@radix-ui/react-dialog'
import { useState } from 'react'
import type { FormEvent } from 'react'
import type { ScriptItem, Vacancy } from './api.ts'
import Spinner from './Spinner.tsx'
import { useReturnFocus } from './useReturnFocus.ts'
import {
  isRunning,
  useRetryJob,
  useSaveScript,
  useScript,
} from './vacancies.ts'

const MAX_YEARS = 20

const SOURCE_NAMES: Record<string, string> = {
  required_qualifications: 'From the required qualifications',
  nice_to_haves: 'From the nice-to-haves',
  responsibilities: 'From the responsibilities',
  role_summary: 'From the role summary',
  title: 'From the title',
}
const MAX_ALTERNATIVES = 4

/** The request for a proposal. Owned by the page, which also starts it on opening. */
type Propose = {
  mutate: () => void
  isPending: boolean
  error: Error | null
}

type Props = {
  vacancy: Vacancy
  open: boolean
  onOpenChange: (open: boolean) => void
  propose: Propose
}

/**
 * The selection script dialog (PRD F5): the model's proposal, which the
 * recruiter edits. Cancel saves nothing; Submit saves the script.
 */
function SelectionScriptDialog({ vacancy, open, onOpenChange, propose }: Props) {
  const returnFocus = useReturnFocus()

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog wide" {...returnFocus}>
          <Dialog.Title>Selection script</Dialog.Title>
          <DialogBody
            vacancy={vacancy}
            propose={propose}
            onClose={() => onOpenChange(false)}
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
  propose,
  onClose,
}: {
  vacancy: Vacancy
  propose: Propose
  onClose: () => void
}) {
  const script = useScript(vacancy, true)
  const retry = useRetryJob()
  const job = vacancy.script_job

  if (isRunning(job) || propose.isPending) {
    return (
      <>
        <Spinner label="Reading the vacancy and proposing criteria…" />
        <Dialog.Description>
          You can close this window: the proposal will be waiting for you.
        </Dialog.Description>
      </>
    )
  }

  if (script.isPending) {
    return <Spinner label="Loading…" />
  }
  if (script.isError) {
    return (
      <p role="alert" className="problem">
        {script.error.message}
      </p>
    )
  }

  const saved = script.data.saved
  const proposal = script.data.proposal?.current ? script.data.proposal : null
  // What to edit: the saved script if there is one, otherwise the proposal.
  const start = saved?.items ?? proposal?.items ?? null

  const failed = job && (job.status === 'failed' || job.status === 'interrupted')
  if (start === null) {
    return (
      <div>
        {failed || propose.error ? (
          <p role="alert" className="problem">
            {propose.error?.message ?? retry.error?.message ?? job?.message}
          </p>
        ) : (
          <Dialog.Description>
            There is no proposal for this vacancy yet.
          </Dialog.Description>
        )}
        <div className="actions">
          <Dialog.Close asChild>
            <button type="button">Cancel</button>
          </Dialog.Close>
          <button
            type="button"
            className="primary"
            disabled={retry.isPending}
            onClick={() =>
              failed && job ? retry.mutate(job.id) : propose.mutate()
            }
          >
            {failed ? 'Retry' : 'Ask for a proposal'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <ScriptEditor
      // A new proposal, or a newly saved script, starts the form afresh.
      key={`${saved?.revision ?? 'proposal'}-${job?.id ?? 'none'}`}
      vacancy={vacancy}
      start={start}
      source={saved ? 'saved' : 'proposal'}
      outOfDate={saved?.out_of_date ?? false}
      onPropose={() => propose.mutate()}
      proposeProblem={propose.error?.message}
      onClose={onClose}
    />
  )
}

/** One row of the form. Keywords are edited as text, alternatives split by a comma. */
type Row = {
  id: number
  keywords: string
  years: string
  kind: 'hard' | 'soft'
  reason: string
  grounded: boolean
  source: string
  note: string
}

function toRow(item: ScriptItem, id: number): Row {
  return {
    id,
    keywords: item.any_of.join(', '),
    years: String(item.min_years),
    kind: item.kind,
    reason: item.reason,
    grounded: item.grounded,
    source: item.source,
    note: item.note,
  }
}

function keywordsOf(row: Row): string[] {
  return row.keywords
    .split(',')
    .map((keyword) => keyword.trim())
    .filter((keyword) => keyword !== '')
}

function problemIn(row: Row): string | null {
  const keywords = keywordsOf(row)
  if (keywords.length === 0) {
    return 'Enter at least one keyword.'
  }
  if (keywords.length > MAX_ALTERNATIVES) {
    return `Use at most ${MAX_ALTERNATIVES} alternatives.`
  }
  const years = Number(row.years)
  if (!/^\d+$/.test(row.years.trim()) || years > MAX_YEARS) {
    return `Years must be a whole number from 0 to ${MAX_YEARS}.`
  }
  return null
}

function ScriptEditor({
  vacancy,
  start,
  source,
  outOfDate,
  onPropose,
  proposeProblem,
  onClose,
}: {
  vacancy: Vacancy
  start: ScriptItem[]
  source: 'saved' | 'proposal'
  outOfDate: boolean
  onPropose: () => void
  proposeProblem: string | undefined
  onClose: () => void
}) {
  const [rows, setRows] = useState(() => start.map(toRow))
  const [nextId, setNextId] = useState(start.length)
  const [checked, setChecked] = useState(false)
  const save = useSaveScript(vacancy.id)

  const change = (id: number, changes: Partial<Row>) =>
    setRows(rows.map((row) => (row.id === id ? { ...row, ...changes } : row)))

  function submit(event: FormEvent) {
    event.preventDefault()
    setChecked(true)
    if (rows.length === 0 || rows.some((row) => problemIn(row) !== null)) {
      return
    }
    save.mutate(
      rows.map((row) => ({
        any_of: keywordsOf(row),
        min_years: Number(row.years),
        kind: row.kind,
        reason: row.reason,
        // Decided by the server; what is sent here is ignored.
        grounded: false,
        source: '',
        note: '',
        enabled: true,
      })),
      { onSuccess: onClose },
    )
  }

  return (
    <form onSubmit={submit} noValidate>
      <Dialog.Description>
        {source === 'proposal'
          ? 'A proposal from the model, based on the vacancy text. Review and edit it before you submit.'
          : 'The saved script for this vacancy. Edit it and submit to save your changes.'}
      </Dialog.Description>
      <ul className="explain">
        <li>
          <strong>Hard:</strong> a candidate must meet it to be listed.{' '}
          <strong>Soft:</strong> it adds to the score but is not required.
          Only the required qualifications are proposed as hard; you can make
          any item hard yourself.
        </li>
        <li>
          Separate alternatives with a comma. A candidate needs only one of
          them, and it must reach the years on its own: years are not added up
          across alternatives.
        </li>
      </ul>

      {outOfDate && (
        <p className="flags" role="note">
          <strong>Out of date.</strong> The vacancy was edited after this
          script was saved. Check it against the new text, or ask for a new
          proposal. Submitting saves it for the current text.
        </p>
      )}

      {rows.length === 0 && <p>The script has no items. Add at least one.</p>}

      <ol className="script-items">
        {rows.map((row, position) => {
          const number = position + 1
          const problem = checked ? problemIn(row) : null
          return (
            <li key={row.id}>
              <fieldset>
                <legend>Item {number}</legend>
                <div className="script-row">
                  <div className="field grow">
                    <label htmlFor={`keywords-${row.id}`}>Keywords</label>
                    <input
                      id={`keywords-${row.id}`}
                      type="text"
                      value={row.keywords}
                      onChange={(event) =>
                        change(row.id, { keywords: event.target.value })
                      }
                      aria-invalid={problem ? true : undefined}
                      aria-describedby={problem ? `problem-${row.id}` : undefined}
                    />
                  </div>
                  <div className="field years">
                    <label htmlFor={`years-${row.id}`}>Years</label>
                    <input
                      id={`years-${row.id}`}
                      type="text"
                      inputMode="numeric"
                      value={row.years}
                      onChange={(event) =>
                        change(row.id, { years: event.target.value })
                      }
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`kind-${row.id}`}>Requirement</label>
                    <select
                      id={`kind-${row.id}`}
                      value={row.kind}
                      onChange={(event) =>
                        change(row.id, {
                          kind: event.target.value === 'hard' ? 'hard' : 'soft',
                        })
                      }
                    >
                      <option value="hard">Hard</option>
                      <option value="soft">Soft</option>
                    </select>
                  </div>
                  <button
                    type="button"
                    className="danger"
                    aria-label={`Remove item ${number}`}
                    onClick={() =>
                      setRows(rows.filter((other) => other.id !== row.id))
                    }
                  >
                    Remove
                  </button>
                </div>
                {problem && (
                  <p id={`problem-${row.id}`} className="problem">
                    {problem}
                  </p>
                )}
                {row.reason && (
                  <p className="hint">
                    {row.grounded
                      ? `${SOURCE_NAMES[row.source] ?? 'From the vacancy'}: `
                      : 'Reason given by the model, not found in the vacancy text: '}
                    “{row.reason}”
                  </p>
                )}
                {row.note && <p className="hint">{row.note}</p>}
              </fieldset>
            </li>
          )
        })}
      </ol>

      <p>
        <button
          type="button"
          onClick={() => {
            setRows([
              ...rows,
              {
                id: nextId,
                keywords: '',
                years: '0',
                kind: 'soft',
                reason: '',
                grounded: false,
                source: '',
                note: '',
              },
            ])
            setNextId(nextId + 1)
          }}
        >
          Add item
        </button>
      </p>

      {(save.isError || proposeProblem) && (
        <p role="alert" className="problem">
          {save.error?.message ?? proposeProblem}
        </p>
      )}

      <div className="actions spread">
        <button type="button" disabled={save.isPending} onClick={onPropose}>
          Ask for a new proposal
        </button>
        <div className="actions">
          <Dialog.Close asChild>
            <button type="button">Cancel</button>
          </Dialog.Close>
          <button type="submit" className="primary" disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Submit'}
          </button>
        </div>
      </div>
    </form>
  )
}

export default SelectionScriptDialog
