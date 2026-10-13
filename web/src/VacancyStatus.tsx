import type { Vacancy } from './api.ts'
import Spinner from './Spinner.tsx'
import { useRetryJob } from './vacancies.ts'

type Props = {
  vacancy: Vacancy
  onView: (vacancyId: string) => void
}

/** Where a vacancy stands: being written, ready, or failed with a Retry button. */
function VacancyStatus({ vacancy, onView }: Props) {
  const retry = useRetryJob()

  if (vacancy.status === 'generating') {
    return <Spinner label="Writing the vacancy…" />
  }

  if (vacancy.status === 'failed') {
    const job = vacancy.job
    return (
      <div>
        <p role="alert" className="problem">
          {retry.isError
            ? retry.error.message
            : (job?.message ?? 'Something went wrong. Please try again.')}
        </p>
        {job && (
          <button
            type="button"
            onClick={() => retry.mutate(job.id)}
            disabled={retry.isPending}
          >
            Retry
          </button>
        )}
      </div>
    )
  }

  return (
    <button type="button" className="primary" onClick={() => onView(vacancy.id)}>
      {vacancy.status === 'draft'
        ? 'Your vacancy is ready to be viewed'
        : 'View vacancy'}
    </button>
  )
}

export default VacancyStatus
