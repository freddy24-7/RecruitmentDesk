// The one place that talks to the backend. The session lives in an HttpOnly
// cookie, so there is no token to handle here.

export type Session = {
  workspace_id: string
  idle_hours: number
}

export type VacancyOptions = {
  sectors: string[]
  seniorities: string[]
  work_modes: string[]
  title_max: number
  company_max: number
  emphasis_max: number
}

export type VacancyChoices = {
  sector: string
  seniority: string[]
  work_mode: string[]
  title: string
  company: string | null
  emphasis: string | null
}

export type VacancySections = {
  title: string
  company_intro: string
  role_summary: string
  responsibilities: string[]
  required_qualifications: string[]
  nice_to_haves: string[]
  what_we_offer: string[]
  location_and_work_mode: string
}

export type Flag = {
  section: string
  term: string
  attribute: string
}

export type Job = {
  id: string
  type: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'interrupted'
  progress_done: number
  progress_total: number
  error_kind: string | null
  message: string | null
  vacancy_id: string | null
}

export type Vacancy = {
  id: string
  status: 'generating' | 'draft' | 'submitted' | 'failed'
  parameters: VacancyChoices
  sections: VacancySections | null
  flags: Flag[]
  version: number
  created_at: string
  job: Job | null
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

async function request<T>(
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
): Promise<T> {
  const response =
    method === 'GET'
      ? await fetch(path)
      : await fetch(path, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body ?? {}),
        })
  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as T
}

/** The current session, or null if the visitor still has to enter a code. */
export async function getSession(): Promise<Session | null> {
  try {
    return await request<Session>('GET', '/api/session')
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null
    }
    throw error
  }
}

/** Redeem an access code. The code goes in the body, never in the URL. */
export function startSession(code: string): Promise<Session> {
  return request<Session>('POST', '/api/session', { code })
}

export function getVacancyOptions(): Promise<VacancyOptions> {
  return request<VacancyOptions>('GET', '/api/vacancy-options')
}

export function listVacancies(): Promise<Vacancy[]> {
  return request<Vacancy[]>('GET', '/api/vacancies')
}

/** Starts a background job and returns at once. */
export function generateVacancy(
  choices: VacancyChoices,
): Promise<{ vacancy_id: string; job_id: string }> {
  return request('POST', '/api/vacancies', choices)
}

export function retryJob(jobId: string): Promise<Job> {
  return request<Job>('POST', `/api/jobs/${jobId}/retry`)
}
