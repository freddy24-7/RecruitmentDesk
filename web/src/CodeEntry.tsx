import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, startSession } from './api.ts'
import type { Session } from './api.ts'

type Problem = {
  message: string
  contactUrl?: string
}

type Props = {
  onEntered: (session: Session) => void
}

function CodeEntry({ onEntered }: Props) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<Problem | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      onEntered(await startSession(code))
    } catch (error) {
      if (error instanceof ApiError) {
        // The server decides the wording, so it stays in one place.
        setProblem({ message: error.message, contactUrl: error.contactUrl })
      } else {
        setProblem({ message: 'Could not reach the server. Please try again.' })
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="gate">
      <h1>RecruitDesk</h1>
      <p>
        A demo of AI-assisted recruitment. All candidates are fictional
        (synthetic data).
      </p>
      <form onSubmit={submit}>
        <label htmlFor="access-code">Access code</label>
        <input
          id="access-code"
          name="code"
          type="text"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          autoFocus
          aria-describedby={problem ? 'access-code-problem' : undefined}
          aria-invalid={problem ? true : undefined}
        />
        <button type="submit" disabled={busy || code.trim() === ''}>
          {busy ? 'Checking…' : 'Enter'}
        </button>
      </form>
      {problem && (
        <p id="access-code-problem" role="alert" className="problem">
          {problem.message}
          {problem.contactUrl && (
            <>
              {' '}
              <a href={problem.contactUrl} target="_blank" rel="noreferrer">
                Contact the developer
              </a>
            </>
          )}
        </p>
      )}
    </main>
  )
}

export default CodeEntry
