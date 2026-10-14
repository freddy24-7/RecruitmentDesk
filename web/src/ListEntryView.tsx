import { flagName, NOTICE } from './lists.ts'
import Spinner from './Spinner.tsx'
import { useListEntry } from './vacancies.ts'

type Props = {
  vacancyId: string
  candidateId: string
  onBack: () => void
}

/** One listed candidate with the evidence: where in the CV each claim comes from. */
function ListEntryView({ vacancyId, candidateId, onBack }: Props) {
  const entry = useListEntry(vacancyId, candidateId)

  return (
    <article className="vacancy">
      <button type="button" onClick={onBack}>
        Back to list
      </button>
      <p className="notice" role="note">
        {NOTICE}
      </p>

      {entry.isPending && <Spinner label="Loading…" />}
      {entry.isError && (
        <p role="alert" className="problem">
          {entry.error.message}
        </p>
      )}

      {entry.isSuccess && (
        <>
          <h2>{entry.data.name}</h2>
          <p className="synthetic">
            Synthetic data. This person does not exist.
          </p>
          <p>
            {entry.data.phone} · {entry.data.email}
          </p>
          <p>{entry.data.rationale}</p>

          <h3>Scores</h3>
          <p>
            Final score {Math.round(entry.data.final_score * 100)} of 100:
            requirements computed by code{' '}
            {Math.round(entry.data.deterministic_score * 100)}, fit assessed by
            the model {entry.data.llm_score}.{' '}
            {entry.data.total_years} years of work experience in total.
          </p>

          {entry.data.flags.length > 0 && (
            <section className="flags" aria-labelledby="entry-flags">
              <h3 id="entry-flags">Flags</h3>
              <ul>
                {entry.data.flags.map((flag) => (
                  <li key={`${flag.kind}-${flag.detail}`}>
                    <strong>{flagName(flag.kind)}:</strong> {flag.detail}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <h3>Requirements</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Requirement</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Asked</th>
                  <th scope="col">Found in the CV</th>
                  <th scope="col">Result</th>
                </tr>
              </thead>
              <tbody>
                {entry.data.requirements.map((requirement) => (
                  <tr key={requirement.keywords.join('|')}>
                    <th scope="row">{requirement.keywords.join(' or ')}</th>
                    <td>{requirement.kind}</td>
                    <td>
                      {requirement.min_years > 0
                        ? `${requirement.min_years} years`
                        : 'present'}
                    </td>
                    <td>
                      {requirement.keyword
                        ? `${requirement.keyword}, ${requirement.years} years`
                        : 'not found'}
                    </td>
                    <td>{requirement.met ? 'Met' : 'Not met'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3>Evidence from the CV</h3>
          <p className="hint">
            Years are computed by code from the dates of the jobs that mention
            the keyword.
          </p>
          {entry.data.evidence.length === 0 && (
            <p>None of the keywords were found in this CV.</p>
          )}
          {entry.data.evidence.map((evidence) => (
            <section
              key={evidence.keyword}
              className="job"
              aria-label={`Evidence for ${evidence.keyword}`}
            >
              <h4>
                {evidence.keyword}: {evidence.years} years
              </h4>
              <ul>
                {evidence.snippets.map((snippet) => (
                  <li key={`${snippet.where}-${snippet.text}`}>
                    <span className="hint">{snippet.where}:</span> “{snippet.text}”
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </article>
  )
}

export default ListEntryView
