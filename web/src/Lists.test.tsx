import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.tsx'
import type { Job, ListEntry, ListEntryDetail, Lists, Vacancy } from './api.ts'
import { job, json, mockApi, SESSION, SUBMITTED } from './test/api.ts'

afterEach(() => {
  vi.unstubAllGlobals()
})

const NOTICE = 'Suggestions to support a recruiter. A person decides.'

function entry(overrides: Partial<ListEntry> = {}): ListEntry {
  return {
    candidate_id: 'c-1',
    position: 1,
    name: 'Saar Brands',
    phone: '+44 7700 900001',
    email: 'saar.brands1@example.com',
    rationale:
      'Found in the CV: Microsoft Azure (6.8 years), Terraform (2.8 years). Not found: Kubernetes. Relevant roles in the same field.',
    strengths: ['Long hands-on Azure experience.'],
    concerns: ['No container orchestration.'],
    flags: [],
    final_score: 0.84,
    deterministic_score: 0.83,
    llm_score: 85,
    on_short_list: true,
    ...overrides,
  }
}

const ENTRIES: ListEntry[] = [
  entry(),
  entry({
    candidate_id: 'c-2',
    position: 2,
    name: 'Daan Wutke',
    phone: '+44 7700 900002',
    email: 'daan.wutke2@example.com',
    on_short_list: false,
    flags: [
      {
        kind: 'hard_requirement_not_met',
        detail: 'Terraform: 1.2 years of Terraform, 2 asked',
      },
      { kind: 'keyword_not_in_cv', detail: 'Kubernetes' },
    ],
  }),
  entry({
    candidate_id: 'c-3',
    position: 3,
    name: 'Hannah Hoekstra',
    phone: '+44 7700 900003',
    email: 'hannah.hoekstra3@example.com',
    on_short_list: false,
  }),
]

const LISTS: Lists = {
  notice: NOTICE,
  vacancy_title: 'Cloud Engineer',
  out_of_date: false,
  run: {
    created_at: '2026-10-13T15:00:00Z',
    candidates: 10,
    assessed: 6,
    long_size: 3,
    short_size: 1,
    weight_deterministic: 0.5,
    model: 'fake',
  },
  long_list: ENTRIES,
  short_list: ENTRIES.filter((e) => e.on_short_list),
}

const DETAIL: ListEntryDetail = {
  ...entry(),
  notice: NOTICE,
  total_years: 6.8,
  requirements: [
    {
      keywords: ['Microsoft Azure', 'AWS'],
      kind: 'hard',
      min_years: 3,
      met: true,
      keyword: 'Microsoft Azure',
      years: 6.8,
    },
    {
      keywords: ['Kubernetes'],
      kind: 'soft',
      min_years: 0,
      met: false,
      keyword: null,
      years: 0,
    },
  ],
  evidence: [
    {
      keyword: 'Microsoft Azure',
      years: 6.8,
      snippets: [
        {
          where: 'Job 1: Senior Cloud Engineer, Tulip Systems',
          text: 'Built landing zones on Microsoft Azure.',
        },
      ],
    },
  ],
}

const WITH_BOTH = {
  candidates: { count: 10, out_of_date: false },
  script: { exists: true, out_of_date: false, item_count: 4, proposal_ready: true },
}

const LIST_ACTIONS = SUBMITTED.actions.map((action) =>
  action.key.endsWith('_list') ? { ...action, enabled: true, reason: null } : action,
)

function screeningJob(overrides: Partial<Job> = {}): Job {
  return job({
    id: 'job-4',
    type: 'screening',
    status: 'running',
    progress_done: 0,
    progress_total: 6,
    ...overrides,
  })
}

const READY_LISTS = { exist: true, out_of_date: false, long_size: 3, short_size: 1 }

/** A fake backend with one submitted vacancy that has candidates and a script. */
function backend(vacancy: Partial<Vacancy> = {}) {
  const state: { vacancy: Vacancy } = {
    vacancy: { ...SUBMITTED, ...WITH_BOTH, actions: LIST_ACTIONS, ...vacancy },
  }
  const calls = mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancies': () => json(200, [state.vacancy]),
    'POST /api/vacancies/vacancy-1/screening': () => {
      const started = screeningJob()
      state.vacancy = { ...state.vacancy, screening_job: started, job: started }
      return json(202, started)
    },
    'POST /api/jobs/job-4/retry': () => {
      const started = screeningJob({ progress_done: 4 })
      state.vacancy = { ...state.vacancy, screening_job: started, job: started }
      return json(202, started)
    },
    'GET /api/vacancies/vacancy-1/lists': () =>
      json(200, { ...LISTS, out_of_date: state.vacancy.lists.out_of_date }),
    'GET /api/vacancies/vacancy-1/lists/c-1': () => json(200, DETAIL),
  })
  const finish = () => {
    const done = screeningJob({ status: 'done', progress_done: 6 })
    state.vacancy = {
      ...state.vacancy,
      screening_job: done,
      job: done,
      lists: READY_LISTS,
    }
  }
  return { state, calls, finish }
}

const withLists = (vacancy: Partial<Vacancy> = {}) =>
  backend({
    lists: READY_LISTS,
    screening_job: screeningJob({ status: 'done', progress_done: 6 }),
    ...vacancy,
  })

function routes(calls: { route: string }[]): string[] {
  return calls.map((call) => call.route)
}

async function openVacancy() {
  const user = userEvent.setup()
  render(<App />)
  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )
  await user.click(await screen.findByRole('button', { name: 'Open vacancy' }))
  await screen.findByRole('list', { name: 'Actions' })
  return user
}

function names(): string[] {
  return screen
    .getAllByRole('heading', { level: 3 })
    .map((heading) => heading.textContent ?? '')
}

test('generate long-list starts a run, shows progress, then the list', async () => {
  const { state, calls, finish } = backend()
  const user = await openVacancy()

  await user.click(screen.getByRole('button', { name: 'Generate long-list' }))

  expect(
    await screen.findByRole('heading', { name: 'Long list for Cloud Engineer' }),
  ).toBeInTheDocument()
  expect(await screen.findByText('0 of 6 candidates assessed')).toHaveRole('status')
  expect(calls).toContainEqual({
    route: 'POST /api/vacancies/vacancy-1/screening',
    body: { replace: false },
  })

  state.vacancy = { ...state.vacancy, screening_job: screeningJob({ progress_done: 4 }) }
  expect(await screen.findByText('4 of 6 candidates assessed')).toHaveRole('status')

  finish()

  expect(await screen.findByRole('heading', { name: '1. Saar Brands' })).toBeInTheDocument()
  expect(names()).toEqual(['1. Saar Brands', '2. Daan Wutke', '3. Hannah Hoekstra'])
})

test('each entry shows name, phone, email and the paragraph explaining why', async () => {
  withLists()
  const user = await openVacancy()

  await user.click(screen.getByRole('button', { name: 'View long list (3)' }))

  const first = (await screen.findByRole('heading', { name: '1. Saar Brands' }))
    .closest('li') as HTMLElement
  expect(first).toHaveTextContent('+44 7700 900001 · saar.brands1@example.com')
  // Keywords found, years of experience, and what the model found relevant.
  expect(first).toHaveTextContent(
    'Found in the CV: Microsoft Azure (6.8 years), Terraform (2.8 years). Not found: Kubernetes. Relevant roles in the same field.',
  )
  expect(within(first).getByText('Long hands-on Azure experience.')).toBeInTheDocument()
  // Concerns are shown too.
  expect(within(first).getByText('No container orchestration.')).toBeInTheDocument()
})

test('the notice that a person decides is always visible on the lists', async () => {
  const { state } = backend()
  const user = await openVacancy()

  // While the run is still going.
  await user.click(screen.getByRole('button', { name: 'Generate long-list' }))
  await screen.findByRole('status')
  expect(screen.getByText(NOTICE)).toBeVisible()

  // On the long list, the short list, and the evidence view.
  state.vacancy = {
    ...state.vacancy,
    screening_job: screeningJob({ status: 'done' }),
    lists: READY_LISTS,
  }
  await screen.findByRole('heading', { name: '1. Saar Brands' })
  expect(screen.getByText(NOTICE)).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Short list' }))
  expect(screen.getByText(NOTICE)).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Show evidence' }))
  await screen.findByRole('heading', { name: 'Saar Brands', level: 2 })
  expect(screen.getByText(NOTICE)).toBeVisible()
})

test('the short list is the top of the long list', async () => {
  withLists()
  const user = await openVacancy()

  await user.click(screen.getByRole('button', { name: 'View short list (1)' }))

  expect(
    await screen.findByRole('heading', { name: 'Short list for Cloud Engineer' }),
  ).toBeInTheDocument()
  await screen.findByRole('heading', { name: '1. Saar Brands' })
  expect(names()).toEqual(['1. Saar Brands'])

  await user.click(screen.getByRole('button', { name: 'Long list' }))
  expect(names()).toEqual(['1. Saar Brands', '2. Daan Wutke', '3. Hannah Hoekstra'])
})

test('generate short-list shows existing lists without running again', async () => {
  const { calls } = withLists()
  const user = await openVacancy()

  await user.click(screen.getByRole('button', { name: 'Generate short-list' }))

  await screen.findByRole('heading', { name: '1. Saar Brands' })
  expect(routes(calls)).not.toContain('POST /api/vacancies/vacancy-1/screening')
})

test('flags are shown in plain words, with what they are about', async () => {
  withLists()
  const user = await openVacancy()
  await user.click(screen.getByRole('button', { name: 'View long list (3)' }))

  const flags = await screen.findByRole('list', { name: 'Flags for Daan Wutke' })

  expect(flags).toHaveTextContent(
    'Hard requirement not met: Terraform: 1.2 years of Terraform, 2 asked',
  )
  expect(flags).toHaveTextContent(
    'Removed: the model named a keyword that is not in the CV: Kubernetes',
  )
  // An entry without flags has no flag list.
  expect(
    screen.queryByRole('list', { name: 'Flags for Saar Brands' }),
  ).not.toBeInTheDocument()
})

test('the evidence view shows where in the CV each claim comes from', async () => {
  withLists()
  const user = await openVacancy()
  await user.click(screen.getByRole('button', { name: 'View long list (3)' }))
  const first = (await screen.findByRole('heading', { name: '1. Saar Brands' }))
    .closest('li') as HTMLElement

  await user.click(within(first).getByRole('button', { name: 'Show evidence' }))

  expect(
    await screen.findByRole('heading', { name: 'Saar Brands', level: 2 }),
  ).toBeInTheDocument()
  expect(screen.getByText(/Final score 84 of 100/)).toHaveTextContent(
    'requirements computed by code 83, fit assessed by the model 85. 6.8 years of work experience in total.',
  )
  // Per requirement: asked, found, met or not.
  const met = screen.getByRole('row', { name: /Microsoft Azure or AWS/ })
  expect(met).toHaveTextContent('hard')
  expect(met).toHaveTextContent('3 years')
  expect(met).toHaveTextContent('Microsoft Azure, 6.8 years')
  expect(met).toHaveTextContent('Met')
  const missed = screen.getByRole('row', { name: /Kubernetes/ })
  expect(missed).toHaveTextContent('not found')
  expect(missed).toHaveTextContent('Not met')
  // The part of the CV behind the claim.
  const evidence = screen.getByRole('region', { name: 'Evidence for Microsoft Azure' })
  expect(evidence).toHaveTextContent('Microsoft Azure: 6.8 years')
  expect(evidence).toHaveTextContent(
    'Job 1: Senior Cloud Engineer, Tulip Systems: “Built landing zones on Microsoft Azure.”',
  )

  await user.click(screen.getByRole('button', { name: 'Back to list' }))
  expect(await screen.findByRole('heading', { name: '1. Saar Brands' })).toBeInTheDocument()
})

test('generating again states what is replaced and needs confirmation', async () => {
  const { calls } = withLists()
  const user = await openVacancy()
  await user.click(screen.getByRole('button', { name: 'View long list (3)' }))
  await screen.findByRole('heading', { name: '1. Saar Brands' })

  await user.click(screen.getByRole('button', { name: 'Generate lists again' }))
  const dialog = await screen.findByRole('alertdialog', {
    name: 'Generate the lists again?',
  })
  expect(dialog).toHaveTextContent(
    'This replaces the current long list and short list of this vacancy, with their assessments and reasons. They cannot be brought back.',
  )

  await user.click(within(dialog).getByRole('button', { name: 'Keep lists' }))
  expect(routes(calls)).not.toContain('POST /api/vacancies/vacancy-1/screening')

  await user.click(screen.getByRole('button', { name: 'Generate lists again' }))
  await user.click(await screen.findByRole('button', { name: 'Replace lists' }))

  await waitFor(() =>
    expect(calls).toContainEqual({
      route: 'POST /api/vacancies/vacancy-1/screening',
      body: { replace: true },
    }),
  )
})

test('lists made from an older vacancy or script are marked out of date', async () => {
  withLists({ lists: { ...READY_LISTS, out_of_date: true } })
  const user = userEvent.setup()
  render(<App />)
  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )

  const chips = await screen.findByRole('list', { name: 'Status' })
  expect(within(chips).getByText('lists out of date')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Open vacancy' }))
  expect(await screen.findByText(/Lists out of date\./)).toBeInTheDocument()

  // Still there to look at, with the warning.
  await user.click(screen.getByRole('button', { name: 'View long list (3)' }))
  await screen.findByRole('heading', { name: '1. Saar Brands' })
  expect(
    screen.getByText(/The vacancy or the selection script changed after these lists were made/),
  ).toBeInTheDocument()
})

test('ready lists show as a status chip', async () => {
  withLists()
  const user = userEvent.setup()
  render(<App />)

  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )

  const chips = await screen.findByRole('list', { name: 'Status' })
  expect(within(chips).getByText('long list ready')).toBeInTheDocument()
})

test('without candidates or a script the list actions are disabled with the reason', async () => {
  const { calls } = backend({
    candidates: { count: 0, out_of_date: false },
    actions: SUBMITTED.actions,
  })
  const user = await openVacancy()

  const long = screen.getByRole('button', { name: 'Generate long-list' })
  const short = screen.getByRole('button', { name: 'Generate short-list' })
  for (const button of [long, short]) {
    expect(button).toHaveAttribute('aria-disabled', 'true')
    expect(button).toHaveAccessibleDescription(
      'Generate candidates and a selection script first.',
    )
  }

  await user.click(long)
  expect(routes(calls)).not.toContain('POST /api/vacancies/vacancy-1/screening')
  expect(
    screen.queryByRole('heading', { name: /Long list for/ }),
  ).not.toBeInTheDocument()
})

test('a run that fails while the page is open can be retried there', async () => {
  const { state, calls } = backend()
  const user = await openVacancy()
  await user.click(screen.getByRole('button', { name: 'Generate long-list' }))
  await screen.findByRole('status')

  const failed = screeningJob({
    status: 'failed',
    progress_done: 4,
    error_kind: 'llm_rate_limited',
    message: 'The model is busy right now. Please try again in a moment.',
  })
  state.vacancy = { ...state.vacancy, screening_job: failed, job: failed }

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'The model is busy right now. Please try again in a moment.',
  )
  // No half-finished list is shown.
  expect(screen.queryByRole('heading', { level: 3 })).not.toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Retry' }))

  expect(await screen.findByText('4 of 6 candidates assessed')).toHaveRole('status')
  expect(routes(calls)).toContain('POST /api/jobs/job-4/retry')
})

test('a refusal to start is shown on the list page', async () => {
  mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancies': () =>
      json(200, [{ ...SUBMITTED, ...WITH_BOTH, actions: LIST_ACTIONS }]),
    'POST /api/vacancies/vacancy-1/screening': () =>
      json(409, {
        error: 'limit_reached',
        message: 'This demo workspace has used all 10 screening runs.',
      }),
  })
  const user = await openVacancy()

  await user.click(screen.getByRole('button', { name: 'Generate long-list' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'This demo workspace has used all 10 screening runs.',
  )
})

test('regenerating candidates says that the lists are deleted too', async () => {
  withLists()
  const user = await openVacancy()

  await user.click(screen.getByRole('button', { name: 'Generate candidates' }))

  const dialog = await screen.findByRole('dialog', { name: 'Generate candidates' })
  expect(within(dialog).getByRole('note')).toHaveTextContent(
    'The long list and short list made from them are deleted too.',
  )
})
