import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError, getSession } from './api.ts'
import CodeEntry from './CodeEntry.tsx'
import Workspace from './Workspace.tsx'

type Access = 'checking' | 'gate' | 'unreachable' | 'ready'

function App() {
  const [access, setAccess] = useState<Access>('checking')

  // One client for all server data. If any call says the session is gone
  // (401), the visitor goes back to the code entry screen.
  const [queryClient] = useState(() => {
    const onError = (error: Error) => {
      if (error instanceof ApiError && error.status === 401) {
        setAccess('gate')
      }
    }
    return new QueryClient({
      queryCache: new QueryCache({ onError }),
      mutationCache: new MutationCache({ onError }),
      defaultOptions: { queries: { retry: false } },
    })
  })

  // On every page load, ask the server whether a session already exists.
  // A reload therefore never asks for the code again, and never uses one up.
  useEffect(() => {
    let cancelled = false
    getSession()
      .then((session) => {
        if (!cancelled) {
          setAccess(session ? 'ready' : 'gate')
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAccess('unreachable')
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (access === 'checking') {
    return (
      <main>
        <p role="status">Loading…</p>
      </main>
    )
  }

  if (access === 'unreachable') {
    return (
      <main>
        <h1>RecruitDesk</h1>
        <p role="alert">
          Could not reach the server. Reload the page to try again.
        </p>
      </main>
    )
  }

  if (access === 'gate') {
    return (
      <CodeEntry
        onEntered={() => {
          // Nothing from an earlier session may be shown in the new one.
          queryClient.clear()
          setAccess('ready')
        }}
      />
    )
  }

  return (
    <QueryClientProvider client={queryClient}>
      <Workspace />
    </QueryClientProvider>
  )
}

export default App
