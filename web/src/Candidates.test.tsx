import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.tsx'
import type { CandidateDetail, CandidateSummary, Job, Vacancy } from './api.ts'
import { job, json, mockApi, SESSION, SUBMITTED } from './test/api.ts'

afterEach(() => {
  vi.unstubAllGlobals()
})

function candidateJob(overrides: Partial<Job> = {}): Job {
  return job({
    id: 'job-2',
    type: 'candidate_generation',
    status: 'running',
    progress_done: 0,
    progress_total: 20,
    ...overrides,
  })
}

const RUNNING_ACTIONS = SUBMITTED.actions.map((action) =>
  action.key === 'generate_candidates'
    ? {
        ...action,
        enabled: false,
        reason: 'Wait until the running job has finished.',
      }
    : action,
)

const PEOPLE: CandidateSummary[] = [
  {
    id: 'c-1',
    number: 1,
    name: 'Saar Brands',
    email: 'saar.brands1@example.com',
    phone: '+44 7700 900001',
    current_title: 'Senior Cloud Engineer',
    current_company: 'Tulip Systems',
    years_experience: 8.5,
    skills: ['Microsoft Azure', 'Terraform'],
  },
  {
    id: 'c-2',
    number: 2,
    name: 'Daan Wutke',
    email: 'daan.wutke2@example.com',
    phone: '+44 7700 900002',
    current_title: 'Data Engineer',
    current_company: 'Delta Works',
    years_experience: 3,
    skills: ['Apache Spark', 'dbt'],
  },
  {
    id: 'c-3',
    number: 3,
    name: 'Hannah Hoekstra',
    email: 'hannah.hoekstra3@example.com',
    phone: '+44 7700 900003',
    current_title: 'Marketing Specialist',
    current_company: 'Polder Media',
    years_experience: 12,
    skills: ['SEO', 'Copywriting'],
  },
]

const DETAIL: CandidateDetail = {
  ...(PEOPLE[0] as CandidateSummary),
  out_of_date: false,
  cv: {
    profile: 'Engineer with a focus on cloud platforms.',
    positions: [
      {
        title: 'Senior Cloud Engineer',
        company: 'Tulip Systems',
        start: '2024-01',
        end: null,
        highlights: ['Built landing zones on Microsoft Azure.'],
        skills: ['Microsoft Azure', 'Terraform'],
      },
      {
        title: 'Cloud Engineer',
        company: 'Delta Works',
        start: '2018-05',
        end: '2023-12',
        highlights: ['Ran production workloads.'],
        skills: ['Microsoft Azure'],
      },
    ],
    education: [
      { degree: 'BSc Computer Science', institution: 'Hogeschool X', year: 2018 },
    ],
    skills: ['Microsoft Azure', 'Terraform'],
    languages: [
      { language: 'Dutch', level: 'fluent' },
      { language: 'English', level: 'professional' },
    ],
  },
}

/** A fake backend with one submitted vacancy whose state the test can change. */
function backend(initial: Partial<Vacancy> = {}) {
  const state: { vacancy: Vacancy } = { vacancy: { ...SUBMITTED, ...initial } }
  const calls = mockApi({
    'GET /api/session': () => json(200, SESSION),
    // As on the server: the latest candidate job is also reported on its own.
    'GET /api/vacancies': () =>
      json(200, [
        {
          ...state.vacancy,
          candidate_job:
            state.vacancy.job?.type === 'candidate_generation'
              ? state.vacancy.job
              : state.vacancy.candidate_job,
        },
      ]),
    'POST /api/vacancies/vacancy-1/candidates': (body) => {
      const { count } = body as { count: number }
      const started = candidateJob({ progress_total: count })
      state.vacancy = { ...state.vacancy, job: started, actions: RUNNING_ACTIONS }
      return json(202, started)
    },
    'POST /api/jobs/job-2/retry': () => {
      state.vacancy = { ...state.vacancy, job: candidateJob({ progress_done: 5, progress_total: 6 }) }
      return json(202, state.vacancy.job)
    },
    'GET /api/vacancies/vacancy-1/candidates': () =>
      json(200, {
        vacancy_id: 'vacancy-1',
        vacancy_title: 'Cloud Engineer',
        out_of_date: state.vacancy.candidates.out_of_date,
        candidates: state.vacancy.candidates.count > 0 ? PEOPLE : [],
      }),
    'GET /api/vacancies/vacancy-1/candidates/c-1': () => json(200, DETAIL),
  })
  return { state, calls }
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

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Generate candidates' }))
  return screen.findByRole('dialog', { name: 'Generate candidates' })
}

test('generating candidates shows progress as "x of N" and then the result', async () => {
  const { state, calls } = backend()
  const user = await openVacancy()
  const dialog = await openDialog(user)
  expect(within(dialog).getByLabelText('Number of candidates')).toHaveValue('20')

  await user.click(within(dialog).getByRole('button', { name: 'Generate' }))

  expect(await within(dialog).findByRole('status')).toHaveTextContent(
    '0 of 20 candidates created',
  )
  expect(calls).toContainEqual({
    route: 'POST /api/vacancies/vacancy-1/candidates',
    body: { count: 20, replace: false },
  })

  // The job moves on, on the server.
  state.vacancy = { ...state.vacancy, job: candidateJob({ progress_done: 7 }) }
  expect(await within(dialog).findByText('7 of 20 candidates created')).toHaveRole(
    'status',
  )

  state.vacancy = {
    ...state.vacancy,
    job: candidateJob({ status: 'done', progress_done: 20 }),
    candidates: { count: 20, out_of_date: false },
    actions: SUBMITTED.actions,
  }
  await user.click(
    await within(dialog).findByRole('button', { name: 'View candidates (20)' }),
  )

  expect(
    await screen.findByRole('heading', { name: 'Candidates for Cloud Engineer' }),
  ).toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test.each(['0', '101', 'ten', '2.5', ''])(
  'a number outside 1 to 100 is refused in the form: "%s"',
  async (typed) => {
    const { calls } = backend()
    const user = await openVacancy()
    const dialog = await openDialog(user)
    const input = within(dialog).getByLabelText('Number of candidates')

    await user.clear(input)
    if (typed) {
      await user.type(input, typed)
    }
    await user.click(within(dialog).getByRole('button', { name: 'Generate' }))

    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Choose a number from 1 to 100.')
    expect(calls.map((call) => call.route)).not.toContain(
      'POST /api/vacancies/vacancy-1/candidates',
    )
  },
)

test.each(['1', '100'])('the edges of the range are accepted: %s', async (typed) => {
  const { calls } = backend()
  const user = await openVacancy()
  const dialog = await openDialog(user)
  const input = within(dialog).getByLabelText('Number of candidates')

  await user.clear(input)
  await user.type(input, typed)
  await user.click(within(dialog).getByRole('button', { name: 'Generate' }))

  await waitFor(() =>
    expect(calls).toContainEqual({
      route: 'POST /api/vacancies/vacancy-1/candidates',
      body: { count: Number(typed), replace: false },
    }),
  )
})

test('regenerating states what is replaced and only then sends the confirmation', async () => {
  const { calls } = backend({ candidates: { count: 20, out_of_date: false } })
  const user = await openVacancy()

  const dialog = await openDialog(user)

  expect(within(dialog).getByRole('note')).toHaveTextContent(
    'This replaces the 20 existing candidates of this vacancy. Their CVs are deleted and cannot be brought back.',
  )
  expect(
    within(dialog).queryByRole('button', { name: 'Generate' }),
  ).not.toBeInTheDocument()

  // Backing out sends nothing.
  await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
  expect(calls.map((call) => call.route)).not.toContain(
    'POST /api/vacancies/vacancy-1/candidates',
  )

  const again = await openDialog(user)
  await user.click(within(again).getByRole('button', { name: 'Replace candidates' }))

  await waitFor(() =>
    expect(calls).toContainEqual({
      route: 'POST /api/vacancies/vacancy-1/candidates',
      body: { count: 20, replace: true },
    }),
  )
})

test('a refusal from the server is shown in the dialog', async () => {
  backend()
  mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancies': () => json(200, [SUBMITTED]),
    'POST /api/vacancies/vacancy-1/candidates': () =>
      json(409, {
        error: 'limit_reached',
        message:
          'This demo workspace can generate 300 candidates in total. There is room for 3 more.',
      }),
  })
  const user = await openVacancy()
  const dialog = await openDialog(user)

  await user.click(within(dialog).getByRole('button', { name: 'Generate' }))

  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    'There is room for 3 more.',
  )
})

test('while a job runs, the page shows progress and the action is disabled with the reason', async () => {
  backend({
    job: candidateJob({ progress_done: 12, progress_total: 40 }),
    actions: RUNNING_ACTIONS,
  })

  await openVacancy()

  expect(await screen.findByText('12 of 40 candidates created')).toHaveRole('status')
  const action = screen.getByRole('button', { name: 'Generate candidates' })
  expect(action).toHaveAttribute('aria-disabled', 'true')
  expect(action).toHaveAccessibleDescription(
    'Wait until the running job has finished.',
  )
})

test('a run that failed part-way says how far it got and can be retried', async () => {
  const { calls } = backend({
    job: candidateJob({
      status: 'failed',
      progress_done: 5,
      progress_total: 6,
      error_kind: 'llm_invalid_output',
      message: 'The model returned an answer that could not be used. Please try again.',
    }),
    candidates: { count: 5, out_of_date: false },
  })
  const user = await openVacancy()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'The model returned an answer that could not be used. Please try again. 5 of 6 candidates were created.',
  )
  // What was created is kept and can be viewed.
  expect(
    screen.getByRole('button', { name: 'View candidates (5)' }),
  ).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Retry' }))

  expect(await screen.findByText('5 of 6 candidates created')).toHaveRole('status')
  expect(calls.map((call) => call.route)).toContain('POST /api/jobs/job-2/retry')
})

test('candidates of an edited vacancy are marked out of date', async () => {
  backend({ candidates: { count: 20, out_of_date: true } })
  const user = userEvent.setup()
  render(<App />)
  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )

  // On the list, as status chips.
  const chips = await screen.findByRole('list', { name: 'Status' })
  expect(within(chips).getByText('20 candidates')).toBeInTheDocument()
  expect(within(chips).getByText('candidates out of date')).toBeInTheDocument()

  // On the vacancy, with what to do about it.
  await user.click(screen.getByRole('button', { name: 'Open vacancy' }))
  expect(await screen.findByRole('note')).toHaveTextContent(
    'Out of date. The vacancy was edited after these candidates were created. Generate candidates again to match the new text.',
  )
  // They are still there: nothing was thrown away silently.
  expect(
    screen.getByRole('button', { name: 'View candidates (20)' }),
  ).toBeInTheDocument()
})

async function openCandidates() {
  backend({ candidates: { count: 3, out_of_date: false } })
  const user = await openVacancy()
  await user.click(screen.getByRole('button', { name: 'View candidates (3)' }))
  await screen.findByRole('table')
  return user
}

function names(): string[] {
  return within(screen.getByRole('table'))
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[1]?.textContent ?? '')
}

test('the candidate page lists the candidates and labels them as synthetic', async () => {
  await openCandidates()

  expect(
    screen.getByRole('heading', { name: 'Candidates for Cloud Engineer' }),
  ).toBeInTheDocument()
  expect(screen.getByText(/Synthetic data. These people do not exist/)).toBeInTheDocument()
  expect(names()).toEqual(['Saar Brands', 'Daan Wutke', 'Hannah Hoekstra'])
  expect(screen.getByRole('status')).toHaveTextContent('Showing 3 of 3 candidates')
  const row = screen.getByRole('row', { name: /Saar Brands/ })
  expect(row).toHaveTextContent('Senior Cloud Engineer at Tulip Systems')
  expect(row).toHaveTextContent('8.5 years')
  expect(row).toHaveTextContent('Microsoft Azure, Terraform')
})

test('candidates can be searched by name, role, company or skill', async () => {
  const user = await openCandidates()
  const search = screen.getByLabelText('Search candidates')

  await user.type(search, 'spark')
  expect(names()).toEqual(['Daan Wutke'])
  expect(screen.getByRole('status')).toHaveTextContent('Showing 1 of 3 candidates')

  await user.clear(search)
  await user.type(search, 'engineer')
  expect(names()).toEqual(['Saar Brands', 'Daan Wutke'])

  await user.clear(search)
  await user.type(search, 'polder')
  expect(names()).toEqual(['Hannah Hoekstra'])

  await user.clear(search)
  await user.type(search, 'no such thing')
  expect(names()).toEqual([])
  expect(screen.getByRole('status')).toHaveTextContent('Showing 0 of 3 candidates')
})

test('candidates can be sorted, and the sorted column is announced', async () => {
  const user = await openCandidates()
  const header = (name: string) => screen.getByRole('columnheader', { name })

  // The arrow is decoration; screen readers get the state from aria-sort.
  expect(header('No.')).toHaveAttribute('aria-sort', 'ascending')
  expect(header('Name')).toHaveAttribute('aria-sort', 'none')

  await user.click(screen.getByRole('button', { name: 'Name' }))
  expect(names()).toEqual(['Daan Wutke', 'Hannah Hoekstra', 'Saar Brands'])
  expect(header('Name')).toHaveAttribute('aria-sort', 'ascending')
  expect(header('No.')).toHaveAttribute('aria-sort', 'none')

  await user.click(screen.getByRole('button', { name: 'Name' }))
  expect(names()).toEqual(['Saar Brands', 'Hannah Hoekstra', 'Daan Wutke'])
  expect(header('Name')).toHaveAttribute('aria-sort', 'descending')

  // Years are sorted as numbers: 3, 8.5, 12 (as text, 12 would come first).
  await user.click(screen.getByRole('button', { name: 'Experience' }))
  expect(names()).toEqual(['Daan Wutke', 'Saar Brands', 'Hannah Hoekstra'])
})

test('a candidate opens with the full CV', async () => {
  const user = await openCandidates()

  await user.click(screen.getByRole('button', { name: 'Saar Brands' }))

  expect(
    await screen.findByRole('heading', { name: 'Saar Brands', level: 2 }),
  ).toBeInTheDocument()
  expect(screen.getByText('Synthetic data. This person does not exist.')).toBeInTheDocument()
  expect(
    screen.getByText('saar.brands1@example.com · +44 7700 900001'),
  ).toBeInTheDocument()
  expect(screen.getByText('Engineer with a focus on cloud platforms.')).toBeInTheDocument()
  // Employment history with dates.
  expect(
    screen.getByRole('heading', { name: 'Senior Cloud Engineer, Tulip Systems' }),
  ).toBeInTheDocument()
  expect(screen.getByText('Jan 2024 to present')).toBeInTheDocument()
  expect(screen.getByText('May 2018 to Dec 2023')).toBeInTheDocument()
  expect(screen.getByText('Skills used: Microsoft Azure, Terraform')).toBeInTheDocument()
  expect(
    screen.getByText('BSc Computer Science, Hogeschool X (2018)'),
  ).toBeInTheDocument()
  expect(screen.getByText('English: professional')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Back to candidates' }))
  expect(await screen.findByRole('table')).toBeInTheDocument()
})

test('a vacancy without candidates says so', async () => {
  backend({ candidates: { count: 0, out_of_date: false } })
  await openVacancy()

  expect(
    screen.queryByRole('button', { name: /View candidates/ }),
  ).not.toBeInTheDocument()
})
