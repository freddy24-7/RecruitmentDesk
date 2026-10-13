import { useState } from 'react'
import type { Action, Vacancy, VacancySections } from './api.ts'
import CandidateProgress from './CandidateProgress.tsx'
import GenerateCandidatesDialog from './GenerateCandidatesDialog.tsx'
import {
  LIST_SECTIONS,
  SECTION_NAMES,
  SECTION_ORDER,
  sectionName,
} from './sections.ts'
import { describeChoices } from './vacancies.ts'
import VacancyEditor from './VacancyEditor.tsx'

type Props = {
  vacancy: Vacancy
  onBack: () => void
  onCancelled: () => void
  onSubmitted: () => void
  onViewCandidates: () => void
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

function ReadOnlySections({ sections }: { sections: VacancySections }) {
  return (
    <>
      {SECTION_ORDER.filter((key) => key !== 'title').map((key) => {
        const value = sections[key]
        return (
          <section key={key}>
            <h3>{SECTION_NAMES[key]}</h3>
            {LIST_SECTIONS.has(key) && Array.isArray(value) ? (
              value.length === 0 ? (
                <p className="hint">None.</p>
              ) : (
                <ul>
                  {value.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )
            ) : (
              <p>{value}</p>
            )}
          </section>
        )
      })}
    </>
  )
}

/**
 * The actions on a submitted vacancy. An action whose prerequisites are
 * missing stays visible but disabled, with the reason next to it (PRD F3).
 */
function Actions({
  actions,
  onAction,
}: {
  actions: Action[]
  onAction: (key: string) => void
}) {
  return (
    <ul className="action-list" aria-label="Actions">
      {actions.map((action) => {
        const reasonId = `action-reason-${action.key}`
        return (
          <li key={action.key}>
            <button
              type="button"
              // aria-disabled, not disabled: the button stays reachable with
              // the keyboard, so the reason is read out too.
              aria-disabled={action.enabled ? undefined : true}
              aria-describedby={action.reason ? reasonId : undefined}
              onClick={() => {
                if (action.enabled) {
                  onAction(action.key)
                }
              }}
            >
              {action.label}
            </button>
            {action.reason && (
              <span id={reasonId} className="hint">
                {action.reason}
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

/** One vacancy: the editor for a draft, text and actions for a submitted one. */
function VacancyView({
  vacancy,
  onBack,
  onCancelled,
  onSubmitted,
  onViewCandidates,
}: Props) {
  const [editing, setEditing] = useState(false)
  const [generatingCandidates, setGeneratingCandidates] = useState(false)
  const sections = vacancy.sections
  const isDraft = vacancy.status === 'draft'
  const showEditor = sections !== null && (isDraft || editing)

  return (
    <article className="vacancy">
      <button type="button" onClick={onBack}>
        Back
      </button>
      <h2>{sections?.title || vacancy.parameters.title}</h2>
      <p className="hint">
        {describeChoices(vacancy)}
        {vacancy.submitted_at &&
          ` · Submitted on ${formatDate(vacancy.submitted_at)}`}
      </p>

      {vacancy.flags.length > 0 && (
        <section className="flags" aria-labelledby="flags-heading">
          <h3 id="flags-heading">Wording to review</h3>
          <p>
            A check in code found wording that may be discriminatory. Please
            review it.
          </p>
          <ul>
            {vacancy.flags.map((flag) => (
              <li key={`${flag.section}-${flag.term}`}>
                “{flag.term}” in {sectionName(flag.section)} ({flag.attribute})
              </li>
            ))}
          </ul>
        </section>
      )}

      {sections === null && <p>This vacancy has no text yet.</p>}

      {sections !== null && !showEditor && (
        <>
          <Actions
            actions={vacancy.actions}
            onAction={(key) => {
              if (key === 'edit') {
                setEditing(true)
              } else if (key === 'generate_candidates') {
                setGeneratingCandidates(true)
              }
            }}
          />
          <CandidateProgress
            vacancy={vacancy}
            onViewCandidates={onViewCandidates}
          />
          <ReadOnlySections sections={sections} />
        </>
      )}

      {sections !== null && showEditor && (
        <VacancyEditor
          vacancy={vacancy}
          sections={sections}
          onCancelled={onCancelled}
          onSubmitted={onSubmitted}
          onDone={isDraft ? undefined : () => setEditing(false)}
        />
      )}

      <GenerateCandidatesDialog
        vacancy={vacancy}
        open={generatingCandidates}
        onOpenChange={setGeneratingCandidates}
        onViewCandidates={onViewCandidates}
      />
    </article>
  )
}

export default VacancyView
