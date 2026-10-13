import type { Vacancy } from './api.ts'
import Spinner from './Spinner.tsx'
import { isRunning, useRetryJob } from './vacancies.ts'

type Props = {
  vacancy: Vacancy
  onViewCandidates: () => void
}

/**
 * Where the candidates of a vacancy stand: being created ("x of N"), failed
 * part-way with a Retry button, or ready to view.
 */
function CandidateProgress({ vacancy, onViewCandidates }: Props) {
  const retry = useRetryJob()
  // The latest candidate job, also when another kind of job came after it.
  const job = vacancy.candidate_job
  const { count, out_of_date: outOfDate } = vacancy.candidates

  if (job && isRunning(job)) {
    return (
      <Spinner
        label={`${job.progress_done} of ${job.progress_total} candidates created`}
      />
    )
  }

  const stopped = job && (job.status === 'failed' || job.status === 'interrupted')

  return (
    <div>
      {stopped && (
        <>
          <p role="alert" className="problem">
            {retry.error?.message ?? job.message} {job.progress_done} of{' '}
            {job.progress_total} candidates were created.
          </p>
          <button
            type="button"
            className="primary"
            onClick={() => retry.mutate(job.id)}
            disabled={retry.isPending}
          >
            Retry
          </button>
        </>
      )}
      {count > 0 && outOfDate && (
        <p className="flags" role="note">
          <strong>Out of date.</strong> The vacancy was edited after these
          candidates were created. Generate candidates again to match the new
          text.
        </p>
      )}
      {count > 0 && (
        <p>
          <button type="button" onClick={onViewCandidates}>
            View candidates ({count})
          </button>
        </p>
      )}
    </div>
  )
}

export default CandidateProgress
