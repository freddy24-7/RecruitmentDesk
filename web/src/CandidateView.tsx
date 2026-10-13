import Spinner from './Spinner.tsx'
import { useCandidate } from './vacancies.ts'

type Props = {
  vacancyId: string
  candidateId: string
  onBack: () => void
}

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

/** "2024-03" becomes "Mar 2024". */
function month(value: string): string {
  const [year, number] = value.split('-')
  return `${MONTHS[Number(number) - 1] ?? ''} ${year ?? ''}`.trim()
}

/** One candidate with the full CV (PRD F4). */
function CandidateView({ vacancyId, candidateId, onBack }: Props) {
  const candidate = useCandidate(vacancyId, candidateId)

  return (
    <article className="vacancy">
      <button type="button" onClick={onBack}>
        Back to candidates
      </button>

      {candidate.isPending && <Spinner label="Loading…" />}
      {candidate.isError && (
        <p role="alert" className="problem">
          {candidate.error.message}
        </p>
      )}

      {candidate.isSuccess && (
        <>
          <h2>{candidate.data.name}</h2>
          <p className="synthetic">
            Synthetic data. This person does not exist.
          </p>
          <p>
            {candidate.data.email} · {candidate.data.phone}
          </p>

          <h3>Profile</h3>
          <p>{candidate.data.cv.profile}</p>

          <h3>Employment</h3>
          {candidate.data.cv.positions.map((position) => (
            <section key={`${position.start}-${position.company}`} className="job">
              <h4>
                {position.title}, {position.company}
              </h4>
              <p className="hint">
                {month(position.start)} to{' '}
                {position.end ? month(position.end) : 'present'}
              </p>
              <ul>
                {position.highlights.map((highlight) => (
                  <li key={highlight}>{highlight}</li>
                ))}
              </ul>
              {position.skills.length > 0 && (
                <p className="hint">Skills used: {position.skills.join(', ')}</p>
              )}
            </section>
          ))}

          <h3>Education</h3>
          <ul>
            {candidate.data.cv.education.map((education) => (
              <li key={`${education.degree}-${education.year}`}>
                {education.degree}, {education.institution} ({education.year})
              </li>
            ))}
          </ul>

          <h3>Skills</h3>
          <p>{candidate.data.cv.skills.join(', ') || 'None listed.'}</p>

          <h3>Languages</h3>
          <ul>
            {candidate.data.cv.languages.map((language) => (
              <li key={language.language}>
                {language.language}: {language.level}
              </li>
            ))}
          </ul>
        </>
      )}
    </article>
  )
}

export default CandidateView
