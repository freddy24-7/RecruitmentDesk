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
  /** The saved selection script, and whether a proposal is waiting. */
  script: {
    exists: boolean
    out_of_date: boolean
    item_count: number
    proposal_ready: boolean
  }
  /** The long list and short list, and whether their inputs changed since. */
  lists: {
    exist: boolean
    out_of_date: boolean
    long_size: number
    short_size: number
  }
  /** The latest job of each kind, so one does not hide the state of the other. */
  candidate_job: Job | null
  script_job: Job | null
  screening_job: Job | null
  /** Interview questions: whether they exist, are current, or why not possible. */
  interview: { exist: boolean; out_of_date: boolean; reason: string | null }
  interview_job: Job | null
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

export type ScriptItem = {
  /** Alternatives: any one of these keywords meets the item. */
  any_of: string[]
  min_years: number
  kind: 'hard' | 'soft'
  /** The sentence in the vacancy the item is based on. Empty for added items. */
  reason: string
  /** Set by the server: is the reason really in the vacancy text? */
  grounded: boolean
  /** Set by the server: the vacancy section the reason is quoted from, or ''. */
  source: string
  /** Set by the server when it changed the model's proposal, to say why. */
  note: string
  enabled: boolean
}

export type Script = {
  saved: {
    items: ScriptItem[]
    revision: number
    out_of_date: boolean
    updated_at: string
  } | null
  proposal: { items: ScriptItem[]; current: boolean } | null
}

export type ListFlag = { kind: string; detail: string }

/** One candidate on a list. Contact details are joined back for display only. */
export type ListEntry = {
  candidate_id: string
  position: number
  name: string
  phone: string
  email: string
  rationale: string
  strengths: string[]
  concerns: string[]
  flags: ListFlag[]
  final_score: number
  deterministic_score: number
  llm_score: number
  on_short_list: boolean
}

export type Lists = {
  notice: string
  vacancy_title: string
  out_of_date: boolean
  run: {
    created_at: string
    candidates: number
    assessed: number
    long_size: number
    short_size: number
    weight_deterministic: number
    model: string
  }
  long_list: ListEntry[]
  short_list: ListEntry[]
}

export type ListEntryDetail = ListEntry & {
  notice: string
  total_years: number
  requirements: {
    keywords: string[]
    kind: 'hard' | 'soft'
    min_years: number
    met: boolean
    keyword: string | null
    years: number
  }[]
  evidence: {
    keyword: string
    years: number
    snippets: { where: string; text: string }[]
  }[]
}

export type InterviewQuestion = {
  question: string
  purpose: string
  /** A reference into the set's sources, or '' for the recruiter's own. */
  source: string
  source_kind: string
  source_text: string
  /** Terms a check in code found that may touch a protected attribute. */
  flags: string[]
}

export type QuestionSet = {
  id: string
  candidate_id: string | null
  candidate_name: string | null
  list_position: number | null
  questions: InterviewQuestion[]
  edited: boolean
  dropped: { kind: string; detail: string }[]
}

export type Interview = {
  notice: string
  vacancy_title: string
  out_of_date: boolean
  core: QuestionSet | null
  follow_ups: QuestionSet[]
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

/** The saved script and the model's latest proposal, for the dialog. */
export function getScript(vacancyId: string): Promise<Script> {
  return request<Script>('GET', `/api/vacancies/${vacancyId}/script`)
}

/** Ask the model for a proposal, in the background. Nothing is saved as script. */
export function proposeScript(vacancyId: string): Promise<Job> {
  return request<Job>('POST', `/api/vacancies/${vacancyId}/script/proposal`)
}

/** Submit the dialog: save the script for the current version of the vacancy. */
export function saveScript(vacancyId: string, items: ScriptItem[]): Promise<Script> {
  return request<Script>('PUT', `/api/vacancies/${vacancyId}/script`, { items })
}

/**
 * Start a screening run in the background: it produces both lists. `replace`
 * must be true when lists exist: send it only after the user confirmed.
 */
export function startScreening(vacancyId: string, replace: boolean): Promise<Job> {
  return request<Job>('POST', `/api/vacancies/${vacancyId}/screening`, { replace })
}

export function getLists(vacancyId: string): Promise<Lists> {
  return request<Lists>('GET', `/api/vacancies/${vacancyId}/lists`)
}

export function getListEntry(
  vacancyId: string,
  candidateId: string,
): Promise<ListEntryDetail> {
  return request<ListEntryDetail>(
    'GET',
    `/api/vacancies/${vacancyId}/lists/${candidateId}`,
  )
}

/** Start making interview questions. `replace` only after the user confirmed. */
export function startInterview(vacancyId: string, replace: boolean): Promise<Job> {
  return request<Job>('POST', `/api/vacancies/${vacancyId}/interview`, { replace })
}

export function getInterview(vacancyId: string): Promise<Interview> {
  return request<Interview>('GET', `/api/vacancies/${vacancyId}/interview`)
}

export function saveQuestions(
  vacancyId: string,
  setId: string,
  questions: InterviewQuestion[],
): Promise<QuestionSet> {
  return request<QuestionSet>('PUT', `/api/vacancies/${vacancyId}/interview/${setId}`, {
    questions,
  })
}

export function resetQuestions(vacancyId: string, setId: string): Promise<QuestionSet> {
  return request<QuestionSet>(
    'POST',
    `/api/vacancies/${vacancyId}/interview/${setId}/reset`,
  )
}

/**
 * "Reset demo": delete every vacancy of this workspace with all related data.
 * Send only after the user confirmed. The session and the limits stay.
 */
export async function resetDemo(): Promise<void> {
  await request<unknown>('POST', '/api/workspace/reset', { confirm: true })
}
