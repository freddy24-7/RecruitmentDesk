import { useState } from 'react'
import type { ListEntry, Vacancy } from './api.ts'
import ConfirmDialog from './ConfirmDialog.tsx'
import { flagName, NOTICE } from './lists.ts'
import type { StartScreening, WhichList } from './lists.ts'
import Spinner from './Spinner.tsx'
import { isRunning, useLists, useRetryJob } from './vacancies.ts'

type Props = {
  vacancy: Vacancy
  which: WhichList
  start: StartScreening
  onBack: () => void
  onInterview: () => void
  onSwitch: (which: WhichList) => void
  onOpen: (candidateId: string) => void
}

function Entry({ entry, onOpen }: { entry: ListEntry; onOpen: () => void }) {
  return (
    <li className="card">
      <h3>
        {entry.position}. {entry.name}
      </h3>
      <p>
        {entry.phone} · {entry.email}
      </p>
      <p>{entry.rationale}</p>
      {entry.strengths.length > 0 && (
        <>
          <h4>Strengths</h4>
          <ul>
            {entry.strengths.map((strength) => (
              <li key={strength}>{strength}</li>
            ))}
          </ul>
        </>
      )}
      {entry.concerns.length > 0 && (
        <>
          <h4>Concerns</h4>
          <ul>
            {entry.concerns.map((concern) => (
              <li key={concern}>{concern}</li>
            ))}
          </ul>
        </>
      )}
      {entry.flags.length > 0 && (
        <ul className="flag-list" aria-label={`Flags for ${entry.name}`}>
          {entry.flags.map((flag) => (
            <li key={`${flag.kind}-${flag.detail}`}>
              <strong>{flagName(flag.kind)}:</strong> {flag.detail}
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={onOpen}>
        Show evidence
      </button>
    </li>
  )
}

/** The long list or the short list of one vacancy (PRD F6, F7). */
function ListsPage({
  vacancy,
  which,
  start,
  onBack,
  onSwitch,
  onOpen,
  onInterview,
}: Props) {
  const lists = useLists(vacancy)
  const retry = useRetryJob()
  const [confirming, setConfirming] = useState(false)

  const title = which === 'long' ? 'Long list' : 'Short list'
  const job = vacancy.screening_job
  const running = isRunning(job) || start.isPending
  const failed = job && (job.status === 'failed' || job.status === 'interrupted')
  const action = vacancy.actions.find(
    (candidate) => candidate.key === 'generate_long_list',
  )
  const entries =
    which === 'long' ? lists.data?.long_list : lists.data?.short_list

  return (
    <section aria-labelledby="lists-heading">
      <button type="button" onClick={onBack}>
        Back to vacancy
      </button>
      <h2 id="lists-heading">
        {title} for {vacancy.sections?.title || vacancy.parameters.title}
      </h2>
      <p className="notice" role="note">
        {NOTICE}
      </p>

      <nav aria-label="Lists" className="tabs">
        <button
          type="button"
          aria-current={which === 'long' ? 'page' : undefined}
          onClick={() => onSwitch('long')}
        >
          Long list
        </button>
        <button
          type="button"
          aria-current={which === 'short' ? 'page' : undefined}
          onClick={() => onSwitch('short')}
        >
          Short list
        </button>
      </nav>

      {running && job && (
        <Spinner
          label={`${job.progress_done} of ${job.progress_total} candidates assessed`}
        />
      )}
      {running && !job && <Spinner label="Starting…" />}

      {!running && (failed || start.error) && (
        <div>
          <p role="alert" className="problem">
            {start.error?.message ?? retry.error?.message ?? job?.message}
          </p>
          {failed && job && (
            <button
              type="button"
              className="primary"
              disabled={retry.isPending}
              onClick={() => retry.mutate(job.id)}
            >
              Retry
            </button>
          )}
        </div>
      )}

      {!running && !vacancy.lists.exist && !failed && !start.error && (
        <div>
          <p>No lists have been generated for this vacancy yet.</p>
          <button
            type="button"
            className="primary"
            aria-disabled={action?.enabled ? undefined : true}
            aria-describedby={action?.reason ? 'generate-lists-reason' : undefined}
            onClick={() => {
              if (action?.enabled) {
                start.mutate(false)
              }
            }}
          >
            Generate lists
          </button>
          {action?.reason && (
            <span id="generate-lists-reason" className="hint">
              {' '}
              {action.reason}
            </span>
          )}
        </div>
      )}

      {!running && vacancy.lists.exist && (
        <>
          {vacancy.lists.out_of_date && (
            <p className="flags" role="note">
              <strong>Out of date.</strong> The vacancy or the selection script
              changed after these lists were made. Generate them again to
              match.
            </p>
          )}
          {lists.isPending && <Spinner label="Loading…" />}
          {lists.isError && (
            <p role="alert" className="problem">
              {lists.error.message}
            </p>
          )}
          {lists.isSuccess && entries && (
            <>
              <p className="hint">
                {entries.length} of {lists.data.run.candidates} candidates. The
                model assessed the strongest {lists.data.run.assessed} on an
                anonymised CV. Names and contact details were added afterwards.
              </p>
              <ol className="cards">
                {entries.map((entry) => (
                  <Entry
                    key={entry.candidate_id}
                    entry={entry}
                    onOpen={() => onOpen(entry.candidate_id)}
                  />
                ))}
              </ol>
            </>
          )}
          {which === 'short' && lists.isSuccess && (
            <p>
              <button type="button" className="primary" onClick={onInterview}>
                {vacancy.interview.exist
                  ? 'View interview questions'
                  : 'Generate interview questions'}
              </button>
            </p>
          )}
          <p>
            <button
              type="button"
              aria-disabled={action?.enabled ? undefined : true}
              aria-describedby={action?.reason ? 'regenerate-reason' : undefined}
              onClick={() => {
                if (action?.enabled) {
                  setConfirming(true)
                }
              }}
            >
              Generate lists again
            </button>
            {action?.reason && (
              <span id="regenerate-reason" className="hint">
                {' '}
                {action.reason}
              </span>
            )}
          </p>
        </>
      )}

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Generate the lists again?"
        confirmLabel="Replace lists"
        cancelLabel="Keep lists"
        onConfirm={() => start.mutate(true)}
      >
        <p>
          This replaces the current long list and short list of this vacancy,
          with their assessments and reasons. They cannot be brought back.
        </p>
      </ConfirmDialog>
    </section>
  )
}

export default ListsPage
