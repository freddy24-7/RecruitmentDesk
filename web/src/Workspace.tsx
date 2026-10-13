import { useState } from 'react'
import type { Vacancy } from './api.ts'
import CandidatesPage from './CandidatesPage.tsx'
import CandidateView from './CandidateView.tsx'
import GenerateVacancyDialog from './GenerateVacancyDialog.tsx'
import Spinner from './Spinner.tsx'
import { describeChoices, isRunning, useVacancies } from './vacancies.ts'
import VacancyStatus from './VacancyStatus.tsx'
import VacancyView from './VacancyView.tsx'

type View =
  | { name: 'home' }
  | { name: 'submitted' }
  | { name: 'vacancy'; vacancyId: string }
  | { name: 'candidates'; vacancyId: string }
  | { name: 'candidate'; vacancyId: string; candidateId: string }

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

  const showVacancy = (vacancyId: string) =>
    setView({ name: 'vacancy', vacancyId })

  const all = vacancies.data ?? []
  const inProgress = all.filter((vacancy) => vacancy.status !== 'submitted')
  const submitted = all.filter((vacancy) => vacancy.status === 'submitted')
  const opened =
    view.name === 'vacancy' ||
    view.name === 'candidates' ||
    view.name === 'candidate'
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
            />
          ) : (
            <p>This vacancy does not exist.</p>
          ))}

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
