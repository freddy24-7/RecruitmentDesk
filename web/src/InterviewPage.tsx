import { useState } from 'react'
import type { InterviewQuestion, QuestionSet, Vacancy } from './api.ts'
import ConfirmDialog from './ConfirmDialog.tsx'
import { NOTICE } from './lists.ts'
import Spinner from './Spinner.tsx'
import {
  isRunning,
  useInterview,
  useResetQuestions,
  useRetryJob,
  useSaveQuestions,
  useStartInterview,
} from './vacancies.ts'

const SOURCE_NAMES: Record<string, string> = {
  script_item: 'Selection script',
  strength: 'Strength to verify',
  concern: 'Concern to probe',
  recruiter: 'Added by you',
}

type Props = {
  vacancy: Vacancy
  onBack: () => void
}

function QuestionView({ question }: { question: InterviewQuestion }) {
  return (
    <li>
      <p className="question">{question.question}</p>
      {question.purpose && <p className="hint">{question.purpose}</p>}
      <p className="hint">
        {SOURCE_NAMES[question.source_kind] ?? question.source_kind}
        {question.source_text && `: ${question.source_text}`}
      </p>
      {question.flags.length > 0 && (
        <p className="flags" role="note">
          <strong>Check this question:</strong> it may touch a protected
          attribute ({question.flags.join(', ')}).
        </p>
      )}
    </li>
  )
}

/** One set of questions, readable, with an editor for the recruiter. */
function SetEditor({
  vacancyId,
  set,
  title,
  headingId,
}: {
  vacancyId: string
  set: QuestionSet
  title: string
  headingId: string
}) {
  const [draft, setDraft] = useState<InterviewQuestion[] | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const save = useSaveQuestions(vacancyId)
  const reset = useResetQuestions(vacancyId)
  const problem = save.error ?? reset.error

  const change = (index: number, changes: Partial<InterviewQuestion>) =>
    setDraft(
      (draft ?? []).map((q, at) => (at === index ? { ...q, ...changes } : q)),
    )

  return (
    <section aria-labelledby={headingId} className="card">
      <h3 id={headingId}>{title}</h3>
      {set.dropped.length > 0 && (
        <p className="hint">
          {set.dropped.length}{' '}
          {set.dropped.length === 1 ? 'question was' : 'questions were'} left
          out: the model based them on something that was not offered.
        </p>
      )}

      {draft === null ? (
        <>
          <ol className="questions">
            {set.questions.map((question) => (
              <QuestionView key={question.question} question={question} />
            ))}
          </ol>
          <div className="actions start">
            <button type="button" onClick={() => setDraft(set.questions)}>
              Edit questions
            </button>
            <button
              type="button"
              disabled={!set.edited || reset.isPending}
              onClick={() => setConfirmReset(true)}
            >
              Reset to generated
            </button>
          </div>
        </>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            const kept = draft.filter((q) => q.question.trim() !== '')
            if (kept.length === 0) {
              return
            }
            save.mutate(
              { setId: set.id, questions: kept },
              { onSuccess: () => setDraft(null) },
            )
          }}
        >
          <ol className="questions">
            {draft.map((question, index) => (
              <li key={index}>
                <fieldset>
                  <legend>Question {index + 1}</legend>
                  <div className="field">
                    <label htmlFor={`${set.id}-q-${index}`}>Question</label>
                    <textarea
                      id={`${set.id}-q-${index}`}
                      rows={2}
                      value={question.question}
                      onChange={(event) =>
                        change(index, { question: event.target.value })
                      }
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`${set.id}-p-${index}`}>What it should show</label>
                    <input
                      id={`${set.id}-p-${index}`}
                      type="text"
                      value={question.purpose}
                      onChange={(event) =>
                        change(index, { purpose: event.target.value })
                      }
                    />
                  </div>
                  <button
                    type="button"
                    className="danger"
                    aria-label={`Remove question ${index + 1}`}
                    onClick={() => setDraft(draft.filter((_, at) => at !== index))}
                  >
                    Remove
                  </button>
                </fieldset>
              </li>
            ))}
          </ol>
          {draft.every((q) => q.question.trim() === '') && (
            <p className="problem">Keep or add at least one question.</p>
          )}
          <div className="actions spread">
            <button
              type="button"
              onClick={() =>
                setDraft([
                  ...draft,
                  {
                    question: '',
                    purpose: '',
                    source: '',
                    source_kind: 'recruiter',
                    source_text: '',
                    flags: [],
                  },
                ])
              }
            >
              Add question
            </button>
            <div className="actions">
              <button type="button" onClick={() => setDraft(null)}>
                Cancel
              </button>
              <button type="submit" className="primary" disabled={save.isPending}>
                {save.isPending ? 'Saving…' : 'Save questions'}
              </button>
            </div>
          </div>
        </form>
      )}

      {problem && (
        <p role="alert" className="problem">
          {problem.message}
        </p>
      )}

      <ConfirmDialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title="Reset to the generated questions?"
        confirmLabel="Reset"
        cancelLabel="Keep my edits"
        onConfirm={() => reset.mutate(set.id)}
      >
        <p>
          This puts back the questions as they were generated. Your changes to
          these questions are lost.
        </p>
      </ConfirmDialog>
    </section>
  )
}

/** Interview questions for the short list (PRD F8). */
function InterviewPage({ vacancy, onBack }: Props) {
  const interview = useInterview(vacancy)
  const start = useStartInterview(vacancy.id)
  const retry = useRetryJob()
  const [confirming, setConfirming] = useState(false)

  const job = vacancy.interview_job
  const running = isRunning(job) || start.isPending
  const failed = job && (job.status === 'failed' || job.status === 'interrupted')
  const reason = vacancy.interview.reason

  return (
    <section aria-labelledby="interview-heading">
      <button type="button" onClick={onBack}>
        Back to short list
      </button>
      <h2 id="interview-heading">
        Interview questions for{' '}
        {vacancy.sections?.title || vacancy.parameters.title}
      </h2>
      <p className="notice" role="note">
        {NOTICE}
      </p>
      <p className="hint">
        Core questions are the same for every candidate, so interviews can be
        compared. Follow-up questions are per candidate: strengths to verify
        and concerns to probe.
      </p>

      {running && job && (
        <Spinner
          label={`${job.progress_done} of ${job.progress_total} question sets made`}
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

      {!running && !vacancy.interview.exist && !failed && (
        <p>
          <button
            type="button"
            className="primary"
            aria-disabled={reason ? true : undefined}
            aria-describedby={reason ? 'interview-reason' : undefined}
            onClick={() => {
              if (!reason) {
                start.mutate(false)
              }
            }}
          >
            Generate interview questions
          </button>
          {reason && (
            <span id="interview-reason" className="hint">
              {' '}
              {reason}
            </span>
          )}
        </p>
      )}

      {!running && vacancy.interview.exist && (
        <>
          {vacancy.interview.out_of_date && (
            <p className="flags" role="note">
              <strong>Out of date.</strong> The vacancy, the selection script
              or the lists changed after these questions were made.
            </p>
          )}
          {interview.isPending && <Spinner label="Loading…" />}
          {interview.isSuccess && (
            <>
              {interview.data.core && (
                <SetEditor
                  vacancyId={vacancy.id}
                  set={interview.data.core}
                  title="Core questions, for every candidate"
                  headingId="core-heading"
                />
              )}
              {interview.data.follow_ups.map((set) => (
                <SetEditor
                  key={set.id}
                  vacancyId={vacancy.id}
                  set={set}
                  title={`Follow-up questions for ${set.candidate_name ?? 'a candidate'}`}
                  headingId={`follow-up-${set.id}`}
                />
              ))}
            </>
          )}
          <p>
            <button
              type="button"
              aria-disabled={reason ? true : undefined}
              aria-describedby={reason ? 'interview-again-reason' : undefined}
              onClick={() => {
                if (!reason) {
                  setConfirming(true)
                }
              }}
            >
              Generate interview questions again
            </button>
            {reason && (
              <span id="interview-again-reason" className="hint">
                {' '}
                {reason}
              </span>
            )}
          </p>
        </>
      )}

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Generate the interview questions again?"
        confirmLabel="Replace questions"
        cancelLabel="Keep questions"
        onConfirm={() => start.mutate(true)}
      >
        <p>
          This replaces all interview questions of this vacancy, including
          your edits. They cannot be brought back.
        </p>
      </ConfirmDialog>
    </section>
  )
}

export default InterviewPage
