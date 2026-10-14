import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.tsx'
import type { Interview, Job, Lists, QuestionSet, Vacancy } from './api.ts'
import { job, json, mockApi, SESSION, SUBMITTED } from './test/api.ts'

afterEach(() => {
  vi.unstubAllGlobals()
})

const NOTICE = 'Suggestions to support a recruiter. A person decides.'

const LISTS: Lists = {
  notice: NOTICE,
  vacancy_title: 'Cloud Engineer',
  out_of_date: false,
  run: {
    created_at: '2026-10-14T09:00:00Z',
    candidates: 10,
    assessed: 6,
    long_size: 3,
    short_size: 1,
    weight_deterministic: 0.5,
    model: 'fake',
  },
  long_list: [],
  short_list: [],
}

const CORE: QuestionSet = {
  id: 'set-core',
  candidate_id: null,
  candidate_name: null,
  list_position: null,
  edited: false,
  dropped: [{ kind: 'source_not_found', detail: 'Z9' }],
  questions: [
    {
      question: 'Tell me about an Azure landing zone you designed.',
      purpose: 'Shows depth with the main cloud.',
      source: 'S1',
      source_kind: 'script_item',
      source_text: 'Microsoft Azure or AWS (required, at least 3 years)',
      flags: [],
    },
    {
      question: 'How old are you?',
      purpose: 'None.',
      source: 'S2',
      source_kind: 'script_item',
      source_text: 'Terraform (required, at least 2 years)',
      flags: ['how old (age)'],
    },
  ],
}

const FOLLOW_UP: QuestionSet = {
  id: 'set-c1',
  candidate_id: 'c-1',
  candidate_name: 'Saar Brands',
  list_position: 1,
  edited: false,
  dropped: [],
  questions: [
    {
      question: 'How have you run containers in production?',
      purpose: 'Probes the missing orchestration experience.',
      source: 'C1',
      source_kind: 'concern',
      source_text: 'No container orchestration.',
      flags: [],
    },
  ],
}

const INTERVIEW: Interview = {
  notice: NOTICE,
  vacancy_title: 'Cloud Engineer',
  out_of_date: false,
  core: CORE,
  follow_ups: [FOLLOW_UP],
}

function interviewJob(overrides: Partial<Job> = {}): Job {
  return job({
    id: 'job-5',
    type: 'interview_questions',
    status: 'running',
    progress_done: 0,
    progress_total: 2,
    ...overrides,
  })
}

const WITH_LISTS: Partial<Vacancy> = {
  lists: { exist: true, out_of_date: false, long_size: 3, short_size: 1 },
  screening_job: job({ id: 'job-4', type: 'screening' }),
  interview: { exist: false, out_of_date: false, reason: null },
}

function backend(vacancy: Partial<Vacancy> = {}) {
  const state: { vacancy: Vacancy; interview: Interview } = {
    vacancy: { ...SUBMITTED, ...WITH_LISTS, ...vacancy },
    interview: INTERVIEW,
  }
  const calls = mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancies': () => json(200, [state.vacancy]),
    'GET /api/vacancies/vacancy-1/lists': () => json(200, LISTS),
    'GET /api/vacancies/vacancy-1/interview': () => json(200, state.interview),
    'POST /api/vacancies/vacancy-1/interview': () => {
      const started = interviewJob()
      state.vacancy = { ...state.vacancy, interview_job: started, job: started }
      return json(202, started)
    },
    'PUT /api/vacancies/vacancy-1/interview/set-core': (body) => {
      const { questions } = body as { questions: QuestionSet['questions'] }
      const saved = { ...CORE, questions, edited: true }
      state.interview = { ...state.interview, core: saved }
      return json(200, saved)
    },
    'POST /api/vacancies/vacancy-1/interview/set-core/reset': () => {
      state.interview = { ...state.interview, core: CORE }
      return json(200, CORE)
    },
  })
  const finish = () => {
    const done = interviewJob({ status: 'done', progress_done: 2 })
    state.vacancy = {
      ...state.vacancy,
      interview_job: done,
      job: done,
      interview: { exist: true, out_of_date: false, reason: null },
    }
  }
  return { state, calls, finish }
}

const READY = {
  interview: { exist: true, out_of_date: false, reason: null },
  interview_job: interviewJob({ status: 'done', progress_done: 2 }),
}

function routes(calls: { route: string }[]): string[] {
  return calls.map((call) => call.route)
}

async function openShortList() {
  const user = userEvent.setup()
  render(<App />)
  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )
  await user.click(await screen.findByRole('button', { name: 'Open vacancy' }))
  await user.click(await screen.findByRole('button', { name: 'View short list (1)' }))
  await screen.findByRole('heading', { name: 'Short list for Cloud Engineer' })
  return user
}

test('the short list leads to the interview questions, which are made in the background', async () => {
  const { calls, finish } = backend()
  const user = await openShortList()

  await user.click(
    await screen.findByRole('button', { name: 'Generate interview questions' }),
  )
  expect(
    await screen.findByRole('heading', { name: 'Interview questions for Cloud Engineer' }),
  ).toBeInTheDocument()
  expect(screen.getByText(NOTICE)).toBeVisible()

  await user.click(screen.getByRole('button', { name: 'Generate interview questions' }))
  expect(await screen.findByText('0 of 2 question sets made')).toHaveRole('status')
  expect(calls).toContainEqual({
    route: 'POST /api/vacancies/vacancy-1/interview',
    body: { replace: false },
  })

  finish()

  expect(
    await screen.findByRole('heading', { name: 'Core questions, for every candidate' }),
  ).toBeInTheDocument()
  expect(
    screen.getByRole('heading', { name: 'Follow-up questions for Saar Brands' }),
  ).toBeInTheDocument()
})

test('every question shows what it is based on', async () => {
  backend(READY)
  const user = await openShortList()

  await user.click(screen.getByRole('button', { name: 'View interview questions' }))

  const core = await screen.findByRole('region', {
    name: 'Core questions, for every candidate',
  })
  expect(core).toHaveTextContent('Tell me about an Azure landing zone you designed.')
  expect(core).toHaveTextContent(
    'Selection script: Microsoft Azure or AWS (required, at least 3 years)',
  )
  const followUp = screen.getByRole('region', {
    name: 'Follow-up questions for Saar Brands',
  })
  expect(followUp).toHaveTextContent('Concern to probe: No container orchestration.')
})

test('a question that may touch a protected attribute is flagged for review', async () => {
  backend(READY)
  const user = await openShortList()
  await user.click(screen.getByRole('button', { name: 'View interview questions' }))

  const core = await screen.findByRole('region', {
    name: 'Core questions, for every candidate',
  })

  expect(within(core).getByRole('note')).toHaveTextContent(
    'Check this question: it may touch a protected attribute (how old (age)).',
  )
})

test('questions dropped for a broken link are reported', async () => {
  backend(READY)
  const user = await openShortList()
  await user.click(screen.getByRole('button', { name: 'View interview questions' }))

  const core = await screen.findByRole('region', {
    name: 'Core questions, for every candidate',
  })

  expect(core).toHaveTextContent(
    '1 question was left out: the model based them on something that was not offered.',
  )
})

test('the recruiter edits, removes and adds questions', async () => {
  const { calls } = backend(READY)
  const user = await openShortList()
  await user.click(screen.getByRole('button', { name: 'View interview questions' }))
  const core = await screen.findByRole('region', {
    name: 'Core questions, for every candidate',
  })

  await user.click(within(core).getByRole('button', { name: 'Edit questions' }))
  const first = within(core).getByLabelText('Question', { selector: '#set-core-q-0' })
  await user.clear(first)
  await user.type(first, 'Walk me through your Azure landing zone design.')
  await user.click(within(core).getByRole('button', { name: 'Remove question 2' }))
  await user.click(within(core).getByRole('button', { name: 'Add question' }))
  await user.type(
    within(core).getByLabelText('Question', { selector: '#set-core-q-1' }),
    'What would you change in your last team?',
  )
  await user.click(within(core).getByRole('button', { name: 'Save questions' }))

  await waitFor(() =>
    expect(routes(calls)).toContain('PUT /api/vacancies/vacancy-1/interview/set-core'),
  )
  const sent = calls.find((c) => c.route.startsWith('PUT'))?.body as {
    questions: { question: string; source: string }[]
  }
  expect(sent.questions.map((q) => [q.question, q.source])).toEqual([
    ['Walk me through your Azure landing zone design.', 'S1'],
    ['What would you change in your last team?', ''],
  ])
  expect(
    await within(core).findByText('Walk me through your Azure landing zone design.'),
  ).toBeInTheDocument()
})

test('reset to generated asks for confirmation', async () => {
  const { state, calls } = backend(READY)
  state.interview = {
    ...INTERVIEW,
    core: { ...CORE, edited: true, questions: CORE.questions.slice(0, 1) },
  }
  const user = await openShortList()
  await user.click(screen.getByRole('button', { name: 'View interview questions' }))
  const core = await screen.findByRole('region', {
    name: 'Core questions, for every candidate',
  })

  await user.click(within(core).getByRole('button', { name: 'Reset to generated' }))
  const dialog = await screen.findByRole('alertdialog', {
    name: 'Reset to the generated questions?',
  })
  expect(dialog).toHaveTextContent('Your changes to these questions are lost.')
  await user.click(within(dialog).getByRole('button', { name: 'Reset' }))

  await waitFor(() =>
    expect(routes(calls)).toContain(
      'POST /api/vacancies/vacancy-1/interview/set-core/reset',
    ),
  )
})

test('without a current short list the button is disabled and says why', async () => {
  const { calls } = backend({
    interview: {
      exist: false,
      out_of_date: false,
      reason: 'The lists are out of date. Generate them again first.',
    },
  })
  const user = await openShortList()
  await user.click(
    await screen.findByRole('button', { name: 'Generate interview questions' }),
  )

  const button = await screen.findByRole('button', {
    name: 'Generate interview questions',
  })
  expect(button).toHaveAttribute('aria-disabled', 'true')
  expect(button).toHaveAccessibleDescription(
    'The lists are out of date. Generate them again first.',
  )
  await user.click(button)
  expect(routes(calls)).not.toContain('POST /api/vacancies/vacancy-1/interview')
})

test('questions of changed inputs are marked out of date', async () => {
  backend({ ...READY, interview: { exist: true, out_of_date: true, reason: null } })
  const user = userEvent.setup()
  render(<App />)
  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )

  const chips = await screen.findByRole('list', { name: 'Status' })
  expect(within(chips).getByText('interview questions out of date')).toBeInTheDocument()
})

test('generating again states what is replaced and needs confirmation', async () => {
  const { calls } = backend(READY)
  const user = await openShortList()
  await user.click(screen.getByRole('button', { name: 'View interview questions' }))
  await screen.findByRole('region', { name: 'Core questions, for every candidate' })

  await user.click(
    screen.getByRole('button', { name: 'Generate interview questions again' }),
  )
  const dialog = await screen.findByRole('alertdialog', {
    name: 'Generate the interview questions again?',
  })
  expect(dialog).toHaveTextContent(
    'This replaces all interview questions of this vacancy, including your edits.',
  )
  await user.click(within(dialog).getByRole('button', { name: 'Replace questions' }))

  await waitFor(() =>
    expect(calls).toContainEqual({
      route: 'POST /api/vacancies/vacancy-1/interview',
      body: { replace: true },
    }),
  )
})
