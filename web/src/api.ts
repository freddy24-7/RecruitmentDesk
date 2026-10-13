// The one place that talks to the backend. The session lives in an HttpOnly
// cookie, so there is no token to handle here.

export type Session = {
  workspace_id: string
  idle_hours: number
}

type ErrorBody = {
  error?: string
  message?: string
  contact_url?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly kind: string
  readonly contactUrl: string | undefined

  constructor(status: number, body: ErrorBody) {
    super(body.message ?? 'Something went wrong. Please try again.')
    this.name = 'ApiError'
    this.status = status
    this.kind = body.error ?? 'unknown'
    this.contactUrl = body.contact_url
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: ErrorBody = {}
  try {
    body = (await response.json()) as ErrorBody
  } catch {
    // Not JSON (for example a proxy error page): use the default message.
  }
  return new ApiError(response.status, body)
}

/** The current session, or null if the visitor still has to enter a code. */
export async function getSession(): Promise<Session | null> {
  const response = await fetch('/api/session')
  if (response.status === 401) {
    return null
  }
  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as Session
}

/** Redeem an access code. The code goes in the body, never in the URL. */
export async function startSession(code: string): Promise<Session> {
  const response = await fetch('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  })
  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as Session
}
