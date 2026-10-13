import { useState } from 'react'
import type { CandidateSummary, Vacancy } from './api.ts'
import Spinner from './Spinner.tsx'
import { useCandidates } from './vacancies.ts'

type Props = {
  vacancy: Vacancy
  onBack: () => void
  onOpen: (candidateId: string) => void
}

type SortKey = 'number' | 'name' | 'current_title' | 'years_experience'
type Sort = { key: SortKey; ascending: boolean }

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: 'number', label: 'No.' },
  { key: 'name', label: 'Name' },
  { key: 'current_title', label: 'Current role' },
  { key: 'years_experience', label: 'Experience' },
]

function matches(candidate: CandidateSummary, search: string): boolean {
  const words = search.toLowerCase().split(/\s+/).filter(Boolean)
  const text = [
    candidate.name,
    candidate.current_title,
    candidate.current_company,
    candidate.email,
    ...candidate.skills,
  ]
    .join(' ')
    .toLowerCase()
  return words.every((word) => text.includes(word))
}

function compare(a: CandidateSummary, b: CandidateSummary, sort: Sort): number {
  const left = a[sort.key]
  const right = b[sort.key]
  const order =
    typeof left === 'number' && typeof right === 'number'
      ? left - right
      : String(left).localeCompare(String(right))
  return sort.ascending ? order : -order
}

/** The candidates of one vacancy: searchable and sortable (PRD F4). */
function CandidatesPage({ vacancy, onBack, onOpen }: Props) {
  const candidates = useCandidates(vacancy)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<Sort>({ key: 'number', ascending: true })

  const all = candidates.data?.candidates ?? []
  const shown = all
    .filter((candidate) => matches(candidate, search))
    .sort((a, b) => compare(a, b, sort))

  return (
    <section aria-labelledby="candidates-heading">
      <button type="button" onClick={onBack}>
        Back to vacancy
      </button>
      <h2 id="candidates-heading">
        Candidates for {vacancy.sections?.title || vacancy.parameters.title}
      </h2>
      <p className="synthetic">
        Synthetic data. These people do not exist: names, contact details and
        CVs are generated.
      </p>

      {vacancy.candidates.out_of_date && (
        <p className="flags" role="note">
          <strong>Out of date.</strong> The vacancy was edited after these
          candidates were created.
        </p>
      )}

      {candidates.isPending && <Spinner label="Loading…" />}
      {candidates.isError && (
        <p role="alert" className="problem">
          {candidates.error.message}
        </p>
      )}

      {candidates.isSuccess && all.length === 0 && (
        <p>No candidates have been generated for this vacancy yet.</p>
      )}

      {candidates.isSuccess && all.length > 0 && (
        <>
          <div className="field">
            <label htmlFor="candidate-search">Search candidates</label>
            <input
              id="candidate-search"
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              aria-describedby="candidate-search-hint"
            />
            <p id="candidate-search-hint" className="hint">
              Searches name, role, company and skills.
            </p>
          </div>
          <p role="status" className="hint">
            Showing {shown.length} of {all.length} candidates
          </p>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {COLUMNS.map((column) => {
                    const active = sort.key === column.key
                    return (
                      <th
                        key={column.key}
                        scope="col"
                        aria-sort={
                          active
                            ? sort.ascending
                              ? 'ascending'
                              : 'descending'
                            : 'none'
                        }
                      >
                        <button
                          type="button"
                          className="plain sort"
                          onClick={() =>
                            setSort({
                              key: column.key,
                              ascending: active ? !sort.ascending : true,
                            })
                          }
                        >
                          {column.label}
                          <span aria-hidden="true">
                            {active ? (sort.ascending ? ' ▲' : ' ▼') : ''}
                          </span>
                        </button>
                      </th>
                    )
                  })}
                  <th scope="col">Skills</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((candidate) => (
                  <tr key={candidate.id}>
                    <td>{candidate.number}</td>
                    <td>
                      <button
                        type="button"
                        className="plain link"
                        onClick={() => onOpen(candidate.id)}
                      >
                        {candidate.name}
                      </button>
                    </td>
                    <td>
                      {candidate.current_title}
                      <span className="hint"> at {candidate.current_company}</span>
                    </td>
                    <td>{candidate.years_experience} years</td>
                    <td>{candidate.skills.join(', ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}

export default CandidatesPage
