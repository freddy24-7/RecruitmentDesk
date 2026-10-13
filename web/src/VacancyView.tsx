import type { Vacancy, VacancySections } from './api.ts'
import { describeChoices } from './vacancies.ts'

type Props = {
  vacancy: Vacancy
  onBack: () => void
}

const SECTION_NAMES: Record<keyof VacancySections, string> = {
  title: 'Title',
  company_intro: 'About the company',
  role_summary: 'The role',
  responsibilities: 'Responsibilities',
  required_qualifications: 'Required qualifications',
  nice_to_haves: 'Nice to have',
  what_we_offer: 'What we offer',
  location_and_work_mode: 'Location and work mode',
}

function sectionName(section: string): string {
  return section in SECTION_NAMES
    ? SECTION_NAMES[section as keyof VacancySections]
    : section
}

function Items({ items }: { items: string[] }) {
  if (items.length === 0) {
    return <p className="hint">None.</p>
  }
  return (
    <ul>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  )
}

/** The generated vacancy, read-only. */
function VacancyView({ vacancy, onBack }: Props) {
  const sections = vacancy.sections

  return (
    <article className="vacancy">
      <button type="button" onClick={onBack}>
        Back
      </button>
      <h2>{sections?.title ?? vacancy.parameters.title}</h2>
      <p className="hint">{describeChoices(vacancy)}</p>

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

      {sections ? (
        <>
          <h3>{SECTION_NAMES.company_intro}</h3>
          <p>{sections.company_intro}</p>
          <h3>{SECTION_NAMES.role_summary}</h3>
          <p>{sections.role_summary}</p>
          <h3>{SECTION_NAMES.responsibilities}</h3>
          <Items items={sections.responsibilities} />
          <h3>{SECTION_NAMES.required_qualifications}</h3>
          <Items items={sections.required_qualifications} />
          <h3>{SECTION_NAMES.nice_to_haves}</h3>
          <Items items={sections.nice_to_haves} />
          <h3>{SECTION_NAMES.what_we_offer}</h3>
          <Items items={sections.what_we_offer} />
          <h3>{SECTION_NAMES.location_and_work_mode}</h3>
          <p>{sections.location_and_work_mode}</p>
        </>
      ) : (
        <p>This vacancy has no text yet.</p>
      )}
    </article>
  )
}

export default VacancyView
