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

export type Action = {
  key: string
  label: string
  enabled: boolean
  reason: string | null
}

export type Vacancy = {
  id: string
  status: 'generating' | 'draft' | 'submitted' | 'failed'
  parameters: VacancyChoices
  sections: VacancySections | null
  flags: Flag[]
  version: number
  /** True when the text differs from what the model wrote. */
  edited: boolean
  created_at: string
  submitted_at: string | null
  /** What can be done with a submitted vacancy, with the reason when it cannot. */
  actions: Action[]
  /** Candidates whose CV is ready, and whether the vacancy changed since. */
  candidates: { count: number; out_of_date: boolean }
  job: Job | null
}

export type CandidateSummary = {
  id: string
  number: number
  name: string
  email: string
  phone: string
  current_title: string
  current_company: string
  years_experience: number
  skills: string[]
}

export type CandidateList = {
  vacancy_id: string
  vacancy_title: string
  out_of_date: boolean
  candidates: CandidateSummary[]
}

export type Cv = {
  profile: string
  positions: {
    title: string
    company: string
    start: string
    end: string | null
    highlights: string[]
    skills: string[]
  }[]
  education: { degree: string; institution: string; year: number }[]
  skills: string[]
  languages: { language: string; level: string }[]
}

export type CandidateDetail = CandidateSummary & {
  out_of_date: boolean
  cv: Cv
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
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
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
  if (response.status === 204) {
    return undefined as T
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

/** Save edited sections as a new version of the vacancy. */
export function saveSections(
  vacancyId: string,
  sections: VacancySections,
): Promise<Vacancy> {
  return request<Vacancy>('PUT', `/api/vacancies/${vacancyId}/sections`, sections)
}

/** Go back to the text as the model wrote it. */
export function resetVacancy(vacancyId: string): Promise<Vacancy> {
  return request<Vacancy>('POST', `/api/vacancies/${vacancyId}/reset`)
}

export function submitVacancy(vacancyId: string): Promise<Vacancy> {
  return request<Vacancy>('POST', `/api/vacancies/${vacancyId}/submit`)
}

/**
 * Cancel vacancy: deletes it with all related data. Call this only after the
 * user has confirmed in the confirmation dialog.
 */
export async function cancelVacancy(vacancyId: string): Promise<void> {
  await request<unknown>('DELETE', `/api/vacancies/${vacancyId}?confirm=true`)
}

/**
 * Start generating candidates in the background. `replace` must be true when
 * the vacancy already has candidates: send it only after the user confirmed.
 */
export function generateCandidates(
  vacancyId: string,
  count: number,
  replace: boolean,
): Promise<Job> {
  return request<Job>('POST', `/api/vacancies/${vacancyId}/candidates`, {
    count,
    replace,
  })
}

export function listCandidates(vacancyId: string): Promise<CandidateList> {
  return request<CandidateList>('GET', `/api/vacancies/${vacancyId}/candidates`)
}

export function getCandidate(
  vacancyId: string,
  candidateId: string,
): Promise<CandidateDetail> {
  return request<CandidateDetail>(
    'GET',
    `/api/vacancies/${vacancyId}/candidates/${candidateId}`,
  )
}
