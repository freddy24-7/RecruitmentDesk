import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { startScreening } from './api.ts'
import type { Vacancy } from './api.ts'
import CandidatesPage from './CandidatesPage.tsx'
import CandidateView from './CandidateView.tsx'
import InterviewPage from './InterviewPage.tsx'
import ListEntryView from './ListEntryView.tsx'
import ListsPage from './ListsPage.tsx'
import type { WhichList } from './lists.ts'
import GenerateVacancyDialog from './GenerateVacancyDialog.tsx'
import Spinner from './Spinner.tsx'
import {
  describeChoices,
  isRunning,
  useVacancies,
  VACANCIES_KEY,
} from './vacancies.ts'
import VacancyStatus from './VacancyStatus.tsx'
import VacancyView from './VacancyView.tsx'

type View =
  | { name: 'home' }
  | { name: 'submitted' }
  | { name: 'vacancy'; vacancyId: string }
  | { name: 'candidates'; vacancyId: string }
  | { name: 'candidate'; vacancyId: string; candidateId: string }
  | { name: 'lists'; vacancyId: string; which: WhichList }
  | { name: 'interview'; vacancyId: string }
  | {
      name: 'list-entry'
      vacancyId: string
      which: WhichList
      candidateId: string
    }

/** Short labels on a submitted vacancy: what exists for it already (PRD F3). */
function StatusChips({ vacancy }: { vacancy: Vacancy }) {
  const chips: string[] = []
  const creating = vacancy.candidate_job
  if (creating && isRunning(creating)) {
    chips.push(
      `creating candidates: ${creating.progress_done} of ${creating.progress_total}`,
    )
  } else if (vacancy.candidates.count > 0) {
    chips.push(
      `${vacancy.candidates.count} ${vacancy.candidates.count === 1 ? 'candidate' : 'candidates'}`,
    )
    if (vacancy.candidates.out_of_date) {
      chips.push('candidates out of date')
    }
  }
  if (vacancy.script.exists) {
    chips.push(vacancy.script.out_of_date ? 'script out of date' : 'script ready')
  }
  if (vacancy.lists.exist) {
    chips.push(vacancy.lists.out_of_date ? 'lists out of date' : 'long list ready')
  }
  if (vacancy.interview.exist) {
    chips.push(
      vacancy.interview.out_of_date
        ? 'interview questions out of date'
        : 'interview questions ready',
    )
  }
  if (chips.length === 0) {
    return null
  }
  return (
    <ul className="chips" aria-label="Status">
      {chips.map((chip) => (
        <li key={chip}>{chip}</li>
      ))}
    </ul>
  )
}

/** Everything behind the access gate. */
function Workspace() {
  const [view, setView] = useState<View>({ name: 'home' })
  const [dialogOpen, setDialogOpen] = useState(false)
  const vacancies = useVacancies()
  const queryClient = useQueryClient()
  // One request for a screening run, shared by the vacancy and the list pages,
  // so a refusal is shown wherever the user ends up.
  const screening = useMutation({
    mutationFn: ({ vacancyId, replace }: { vacancyId: string; replace: boolean }) =>
      startScreening(vacancyId, replace),
    onSettled: () => queryClient.invalidateQueries({ queryKey: VACANCIES_KEY }),
  })

  const showVacancy = (vacancyId: string) =>
    setView({ name: 'vacancy', vacancyId })

  const all = vacancies.data ?? []
  const inProgress = all.filter((vacancy) => vacancy.status !== 'submitted')
  const submitted = all.filter((vacancy) => vacancy.status === 'submitted')
  const opened =
    view.name === 'vacancy' ||
    view.name === 'candidates' ||
    view.name === 'candidate' ||
    view.name === 'lists' ||
    view.name === 'interview' ||
    view.name === 'list-entry'
      ? all.find((vacancy) => vacancy.id === view.vacancyId)
      : undefined

  return (
    <>
      <header className="top">
        <div>
          <h1>
            <button
              type="button"
              className="plain"
              onClick={() => setView({ name: 'home' })}
            >
              RecruitDesk
            </button>
          </h1>
          <p className="hint">Demo. All candidates are fictional (synthetic data).</p>
        </div>
        {/* Both buttons are always visible (PRD section 5). */}
        <nav aria-label="Main">
          <button
            type="button"
            className="primary"
            onClick={() => setDialogOpen(true)}
          >
            Generate vacancy
          </button>
          <button
            type="button"
            aria-current={view.name === 'submitted' ? 'page' : undefined}
            onClick={() => setView({ name: 'submitted' })}
          >
            Submitted vacancies
          </button>
        </nav>
      </header>

      <main>
        {vacancies.isPending && <Spinner label="Loading…" />}
        {vacancies.isError && (
          <p role="alert" className="problem">
            {vacancies.error.message}
          </p>
        )}

        {vacancies.isSuccess && view.name === 'home' && (
          <section aria-labelledby="in-progress-heading">
            <h2 id="in-progress-heading">Drafts</h2>
            {inProgress.length === 0 ? (
              <p>
                Nothing here yet. Choose “Generate vacancy” to write your first
                vacancy.
              </p>
            ) : (
              <ul className="cards">
                {inProgress.map((vacancy) => (
                  <li key={vacancy.id} className="card">
                    <h3>{vacancy.parameters.title}</h3>
                    <p className="hint">{describeChoices(vacancy)}</p>
                    <VacancyStatus vacancy={vacancy} onView={showVacancy} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {vacancies.isSuccess && view.name === 'submitted' && (
          <section aria-labelledby="submitted-heading">
            <h2 id="submitted-heading">Submitted vacancies</h2>
            {submitted.length === 0 ? (
              <p>No vacancies have yet been submitted</p>
            ) : (
              <ul className="cards">
                {submitted.map((vacancy) => (
                  <li key={vacancy.id} className="card">
                    <h3>{vacancy.sections?.title || vacancy.parameters.title}</h3>
                    <p className="hint">
                      {describeChoices(vacancy)}
                      {vacancy.submitted_at &&
                        ` · Submitted on ${new Date(
                          vacancy.submitted_at,
                        ).toLocaleDateString('en-GB', {
                          day: 'numeric',
                          month: 'long',
                          year: 'numeric',
                        })}`}
                    </p>
                    <StatusChips vacancy={vacancy} />
                    <VacancyStatus vacancy={vacancy} onView={showVacancy} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {vacancies.isSuccess &&
          view.name === 'vacancy' &&
          (opened ? (
            <VacancyView
              // A different vacancy starts with a fresh editor.
              key={opened.id}
              vacancy={opened}
              onBack={() =>
                setView(
                  opened.status === 'submitted'
                    ? { name: 'submitted' }
                    : { name: 'home' },
                )
              }
              onCancelled={() => setView({ name: 'home' })}
              onSubmitted={() => setView({ name: 'submitted' })}
              onViewCandidates={() =>
                setView({ name: 'candidates', vacancyId: opened.id })
              }
              onViewList={(which) => {
                // "Generate long-list" makes the lists if there are none yet,
                // and then shows them. One run produces both lists.
                screening.reset()
                if (!opened.lists.exist && !isRunning(opened.screening_job)) {
                  screening.mutate({ vacancyId: opened.id, replace: false })
                }
                setView({ name: 'lists', vacancyId: opened.id, which })
              }}
            />
          ) : (
            <p>This vacancy does not exist.</p>
          ))}

        {vacancies.isSuccess && view.name === 'lists' && opened && (
          <ListsPage
            vacancy={opened}
            which={view.which}
            start={{
              mutate: (replace) =>
                screening.mutate({ vacancyId: opened.id, replace }),
              isPending: screening.isPending,
              error: screening.error,
            }}
            onBack={() => setView({ name: 'vacancy', vacancyId: opened.id })}
            onSwitch={(which) =>
              setView({ name: 'lists', vacancyId: opened.id, which })
            }
            onInterview={() => setView({ name: 'interview', vacancyId: opened.id })}
            onOpen={(candidateId) =>
              setView({
                name: 'list-entry',
                vacancyId: opened.id,
                which: view.which,
                candidateId,
              })
            }
          />
        )}

        {vacancies.isSuccess && view.name === 'interview' && opened && (
          <InterviewPage
            vacancy={opened}
            onBack={() =>
              setView({ name: 'lists', vacancyId: opened.id, which: 'short' })
            }
          />
        )}

        {vacancies.isSuccess && view.name === 'list-entry' && opened && (
          <ListEntryView
            vacancyId={opened.id}
            candidateId={view.candidateId}
            onBack={() =>
              setView({ name: 'lists', vacancyId: opened.id, which: view.which })
            }
          />
        )}

        {vacancies.isSuccess && view.name === 'candidates' && opened && (
          <CandidatesPage
            vacancy={opened}
            onBack={() => setView({ name: 'vacancy', vacancyId: opened.id })}
            onOpen={(candidateId) =>
              setView({ name: 'candidate', vacancyId: opened.id, candidateId })
            }
          />
        )}

        {vacancies.isSuccess && view.name === 'candidate' && opened && (
          <CandidateView
            vacancyId={opened.id}
            candidateId={view.candidateId}
            onBack={() => setView({ name: 'candidates', vacancyId: opened.id })}
          />
        )}
      </main>

      <GenerateVacancyDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onView={showVacancy}
      />
    </>
  )
}

export default Workspace
