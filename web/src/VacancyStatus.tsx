import { useState } from 'react'
import type { Vacancy } from './api.ts'
import ConfirmDialog from './ConfirmDialog.tsx'
import Spinner from './Spinner.tsx'
import { useCancelVacancy, useRetryJob } from './vacancies.ts'

type Props = {
  vacancy: Vacancy
  onView: (vacancyId: string) => void
}

/** Where a vacancy stands: being written, ready, or failed with a Retry button. */
function VacancyStatus({ vacancy, onView }: Props) {
  const retry = useRetryJob()
  const cancel = useCancelVacancy(vacancy.id)
  const [confirming, setConfirming] = useState(false)

  if (vacancy.status === 'generating') {
    return <Spinner label="Writing the vacancy…" />
  }

  if (vacancy.status === 'failed') {
    const job = vacancy.job
    return (
      <div>
        <p role="alert" className="problem">
          {(cancel.error ?? retry.error)?.message ??
            job?.message ??
            'Something went wrong. Please try again.'}
        </p>
        <div className="actions start">
          {job && (
            <button
              type="button"
              className="primary"
              onClick={() => retry.mutate(job.id)}
              disabled={retry.isPending || cancel.isPending}
            >
              Retry
            </button>
          )}
          <button
            type="button"
            className="danger"
            onClick={() => setConfirming(true)}
            disabled={retry.isPending || cancel.isPending}
          >
            Cancel vacancy
          </button>
        </div>
        <ConfirmDialog
          open={confirming}
          onOpenChange={setConfirming}
          title="Cancel this vacancy?"
          confirmLabel="Delete vacancy"
          cancelLabel="Keep vacancy"
          onConfirm={() => cancel.mutate()}
        >
          <p>
            This permanently deletes the vacancy “{vacancy.parameters.title}”
            and the choices you made for it. No text was generated for it yet.
            This cannot be undone.
          </p>
        </ConfirmDialog>
      </div>
    )
  }

  return (
    <button type="button" className="primary" onClick={() => onView(vacancy.id)}>
      {vacancy.status === 'draft'
        ? 'Your vacancy is ready to be viewed'
        : 'Open vacancy'}
    </button>
  )
}

export default VacancyStatus
