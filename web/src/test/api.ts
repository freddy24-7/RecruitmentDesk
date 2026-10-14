import { vi } from 'vitest'
import type { Job, Vacancy, VacancyOptions } from '../api.ts'

export type Call = { route: string; body: unknown }

type Handler = (body: unknown) => Response

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/**
 * Replace fetch with a small fake backend. `routes` maps "METHOD /path" to
 * a function that makes the response. Returns the list of calls made.
 */
export function mockApi(routes: Record<string, Handler>): Call[] {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const route = `${init?.method ?? 'GET'} ${String(input)}`
      const body: unknown =
        typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
      calls.push({ route, body })
      const handler = routes[route]
      if (!handler) {
        return json(404, { error: 'not_found', message: `No mock for ${route}` })
      }
      return handler(body)
    }),
  )
  return calls
}

export const SESSION = { workspace_id: 'workspace-1', idle_hours: 24 }

export const OPTIONS: VacancyOptions = {
  sectors: ['IT and software', 'Healthcare', 'Finance'],
  seniorities: ['junior', 'medior', 'senior', 'lead'],
  work_modes: ['office-based', 'home-based', 'hybrid'],
  title_max: 120,
  company_max: 80,
  emphasis_max: 500,
}

export function job(overrides: Partial<Job> = {}): Job {
  return {
    id: 'job-1',
    type: 'vacancy_generation',
    status: 'done',
    progress_done: 1,
    progress_total: 1,
    error_kind: null,
    message: null,
    vacancy_id: 'vacancy-1',
    ...overrides,
  }
}

export function vacancy(overrides: Partial<Vacancy> = {}): Vacancy {
  return {
    id: 'vacancy-1',
    status: 'draft',
    parameters: {
      sector: 'IT and software',
      seniority: ['senior'],
      work_mode: ['hybrid'],
      title: 'Cloud Engineer',
      company: null,
      emphasis: null,
    },
    sections: {
      title: 'Cloud Engineer',
      company_intro: 'Tulip Systems is a fictional company.',
      role_summary: 'You build and run cloud platforms.',
      responsibilities: ['Design cloud infrastructure', 'Review code'],
      required_qualifications: ['3 years of experience with Microsoft Azure'],
      nice_to_haves: ['Experience with Terraform'],
      what_we_offer: ['A competitive salary'],
      location_and_work_mode: 'Utrecht, hybrid.',
    },
    flags: [],
    version: 1,
    edited: false,
    created_at: '2026-10-13T12:00:00Z',
    submitted_at: null,
    actions: [],
    candidates: { count: 0, out_of_date: false },
    script: {
      exists: false,
      out_of_date: false,
      item_count: 0,
      proposal_ready: false,
    },
    lists: { exist: false, out_of_date: false, long_size: 0, short_size: 0 },
    candidate_job: null,
    script_job: null,
    screening_job: null,
    interview: { exist: false, out_of_date: false, reason: 'Generate the short list first.' },
    interview_job: null,
    job: job(),
    ...overrides,
  }
}

export const GENERATING = vacancy({
  status: 'generating',
  sections: null,
  version: 0,
  job: job({ status: 'running', progress_done: 0 }),
})

export const FAILED = vacancy({
  status: 'failed',
  sections: null,
  version: 0,
  job: job({
    status: 'failed',
    error_kind: 'llm_rate_limited',
    message: 'The model is busy right now. Please try again in a moment.',
  }),
})

export const SUBMITTED = vacancy({
  status: 'submitted',
  submitted_at: '2026-10-13T13:00:00Z',
  actions: [
    { key: 'edit', label: 'Edit vacancy', enabled: true, reason: null },
    {
      key: 'generate_candidates',
      label: 'Generate candidates',
      enabled: true,
      reason: null,
    },
    {
      key: 'generate_script',
      label: 'Generate selection script',
      enabled: true,
      reason: null,
    },
    {
      key: 'generate_long_list',
      label: 'Generate long-list',
      enabled: false,
      reason: 'Generate candidates and a selection script first.',
    },
    {
      key: 'generate_short_list',
      label: 'Generate short-list',
      enabled: false,
      reason: 'Generate candidates and a selection script first.',
    },
  ],
})
