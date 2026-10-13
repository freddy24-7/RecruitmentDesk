import { useState } from 'react'
import GenerateVacancyDialog from './GenerateVacancyDialog.tsx'
import Spinner from './Spinner.tsx'
import { describeChoices, useVacancies } from './vacancies.ts'
import VacancyStatus from './VacancyStatus.tsx'
import VacancyView from './VacancyView.tsx'

type View =
  | { name: 'home' }
  | { name: 'submitted' }
  | { name: 'vacancy'; vacancyId: string }

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
    view.name === 'vacancy'
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
            />
          ) : (
            <p>This vacancy does not exist.</p>
          ))}
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
