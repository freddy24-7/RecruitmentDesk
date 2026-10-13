import type { Vacancy } from './api.ts'
import Spinner from './Spinner.tsx'
import { jobIsRunning, useRetryJob } from './vacancies.ts'

type Props = {
  vacancy: Vacancy
  onViewCandidates: () => void
}

export const CANDIDATE_JOB = 'candidate_generation'

/**
 * Where the candidates of a vacancy stand: being created ("x of N"), failed
 * part-way with a Retry button, or ready to view.
 */
function CandidateProgress({ vacancy, onViewCandidates }: Props) {
  const retry = useRetryJob()
  const job = vacancy.job?.type === CANDIDATE_JOB ? vacancy.job : null
  const { count, out_of_date: outOfDate } = vacancy.candidates

  if (job && jobIsRunning(vacancy)) {
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
