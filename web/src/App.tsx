import { useEffect, useState } from 'react'
import { getSession } from './api.ts'
import type { Session } from './api.ts'
import CodeEntry from './CodeEntry.tsx'

type Access =
  | { state: 'checking' }
  | { state: 'gate' }
  | { state: 'unreachable' }
  | { state: 'ready'; session: Session }

function App() {
  const [access, setAccess] = useState<Access>({ state: 'checking' })

  // On every page load, ask the server whether a session already exists.
  // A reload therefore never asks for the code again, and never uses one up.
  useEffect(() => {
    let cancelled = false
    getSession()
      .then((session) => {
        if (!cancelled) {
          setAccess(session ? { state: 'ready', session } : { state: 'gate' })
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAccess({ state: 'unreachable' })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (access.state === 'checking') {
    return (
      <main>
        <p role="status">Loading…</p>
      </main>
    )
  }

  if (access.state === 'unreachable') {
    return (
      <main>
        <h1>RecruitDesk</h1>
        <p role="alert">
          Could not reach the server. Reload the page to try again.
        </p>
      </main>
    )
  }

  if (access.state === 'gate') {
    return (
      <CodeEntry onEntered={(session) => setAccess({ state: 'ready', session })} />
    )
  }

  return (
    <main>
      <h1>RecruitDesk</h1>
      <p>
        Your private workspace is ready. All candidates in this demo are
        fictional (synthetic data).
      </p>
      <p>
        The workspace is removed after {access.session.idle_hours} hours
        without activity.
      </p>
    </main>
  )
}

export default App
