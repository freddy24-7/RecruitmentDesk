import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.tsx'
import type { Vacancy } from './api.ts'
import {
  FAILED,
  GENERATING,
  job,
  json,
  mockApi,
  OPTIONS,
  SESSION,
  vacancy,
} from './test/api.ts'

afterEach(() => {
  vi.unstubAllGlobals()
})

/** A fake backend whose list of vacancies the test can change while it runs. */
function backend(initial: Vacancy[] = []) {
  const state = { vacancies: initial }
  const calls = mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancy-options': () => json(200, OPTIONS),
    'GET /api/vacancies': () => json(200, state.vacancies),
    'POST /api/vacancies': () => {
      state.vacancies = [GENERATING]
      return json(202, { vacancy_id: 'vacancy-1', job_id: 'job-1' })
    },
    'POST /api/jobs/job-1/retry': () => {
      state.vacancies = [GENERATING]
      return json(202, job({ status: 'queued' }))
    },
  })
  return { state, calls }
}

async function openDialog() {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Generate vacancy' }))
  const dialog = await screen.findByRole('dialog', { name: 'Generate vacancy' })
  await within(dialog).findByLabelText('Vacancy title')
  return { user, dialog }
}

async function fillAndSubmit() {
  const { user, dialog } = await openDialog()
  await user.type(within(dialog).getByLabelText('Vacancy title'), 'Cloud Engineer')
  await user.selectOptions(within(dialog).getByLabelText('Sector'), 'Finance')
  await user.click(within(dialog).getByRole('checkbox', { name: 'senior' }))
  await user.click(within(dialog).getByRole('checkbox', { name: 'hybrid' }))
  await user.click(within(dialog).getByRole('button', { name: 'Generate' }))
  return { user, dialog }
}

test('both top-level buttons are always visible', async () => {
  backend([vacancy()])
  const user = userEvent.setup()
  render(<App />)

  const expectBoth = () => {
    expect(
      screen.getByRole('button', { name: 'Generate vacancy' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Submitted vacancies' }),
    ).toBeInTheDocument()
  }

  await screen.findByRole('heading', { name: 'Drafts' })
  expectBoth()

  await user.click(screen.getByRole('button', { name: 'Submitted vacancies' }))
  await screen.findByRole('heading', { name: 'Submitted vacancies' })
  expectBoth()

  await user.click(screen.getByRole('button', { name: 'RecruitDesk' }))
  await user.click(
    await screen.findByRole('button', { name: 'Your vacancy is ready to be viewed' }),
  )
  await screen.findByRole('heading', { name: 'Cloud Engineer', level: 2 })
  expectBoth()
})

test('submitted vacancies shows the empty state', async () => {
  backend([vacancy()])
  const user = userEvent.setup()
  render(<App />)

  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )

  expect(
    await screen.findByText('No vacancies have yet been submitted'),
  ).toBeInTheDocument()
})

test('the dialog offers the choices from the server', async () => {
  backend()
  render(<App />)

  const { dialog } = await openDialog()

  const sector = within(dialog).getByLabelText('Sector')
  expect(within(sector).getAllByRole('option').map((o) => o.textContent)).toEqual(
    OPTIONS.sectors,
  )
  for (const level of OPTIONS.seniorities) {
    expect(within(dialog).getByRole('checkbox', { name: level })).not.toBeChecked()
  }
  for (const mode of OPTIONS.work_modes) {
    expect(within(dialog).getByRole('checkbox', { name: mode })).not.toBeChecked()
  }
  expect(within(dialog).getByLabelText('Company name (optional)')).toBeInTheDocument()
  expect(
    within(dialog).getByLabelText('Anything to emphasise (optional)'),
  ).toBeInTheDocument()
})

test('incomplete choices are explained and nothing is sent', async () => {
  const { calls } = backend()
  render(<App />)
  const { user, dialog } = await openDialog()

  await user.click(within(dialog).getByRole('button', { name: 'Generate' }))

  expect(within(dialog).getByText('Enter a vacancy title.')).toBeInTheDocument()
  expect(
    within(dialog).getByText('Choose at least one seniority.'),
  ).toBeInTheDocument()
  expect(
    within(dialog).getByText('Choose at least one work mode.'),
  ).toBeInTheDocument()
  expect(calls.map((call) => call.route)).not.toContain('POST /api/vacancies')
})

test('generating shows a spinner, then the ready button, then the vacancy', async () => {
  const { state, calls } = backend()
  render(<App />)

  const { user, dialog } = await fillAndSubmit()

  // The spinner has a text alternative.
  expect(await within(dialog).findByRole('status')).toHaveTextContent(
    'Writing the vacancy…',
  )
  expect(calls).toContainEqual({
    route: 'POST /api/vacancies',
    body: {
      sector: 'Finance',
      seniority: ['senior'],
      work_mode: ['hybrid'],
      title: 'Cloud Engineer',
      company: null,
      emphasis: null,
    },
  })

  // The job finishes on the server; the screen follows by polling.
  state.vacancies = [vacancy()]
  await user.click(
    await within(dialog).findByRole('button', {
      name: 'Your vacancy is ready to be viewed',
    }),
  )

  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(
    await screen.findByRole('heading', { name: 'Cloud Engineer', level: 2 }),
  ).toBeInTheDocument()
  // The draft opens for review, with each section in an editable field.
  expect(screen.getByLabelText('Required qualifications')).toHaveValue(
    '3 years of experience with Microsoft Azure',
  )
  expect(screen.getByRole('button', { name: 'Submit vacancy' })).toBeInTheDocument()
})

test('the dialog can be closed without losing the job', async () => {
  const { state } = backend()
  render(<App />)
  const { user, dialog } = await fillAndSubmit()
  await within(dialog).findByRole('status')

  await user.keyboard('{Escape}')

  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  // The page behind the dialog keeps following the job.
  expect(await screen.findByRole('status')).toHaveTextContent('Writing the vacancy…')

  state.vacancies = [vacancy()]
  expect(
    await screen.findByRole('button', { name: 'Your vacancy is ready to be viewed' }),
  ).toBeInTheDocument()
})

test('a job that was running before a reload is picked up again', async () => {
  const { state } = backend([GENERATING])

  render(<App />)

  // First "Loading…", then the status of the job that is still running.
  expect(await screen.findByText('Writing the vacancy…')).toHaveRole('status')
  state.vacancies = [vacancy()]
  expect(
    await screen.findByRole('button', { name: 'Your vacancy is ready to be viewed' }),
  ).toBeInTheDocument()
})

test('a failed job shows a clear message and a Retry button', async () => {
  const { state, calls } = backend([FAILED])
  const user = userEvent.setup()
  render(<App />)

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'The model is busy right now. Please try again in a moment.',
  )
  await user.click(screen.getByRole('button', { name: 'Retry' }))

  expect(await screen.findByRole('status')).toHaveTextContent('Writing the vacancy…')
  expect(calls.map((call) => call.route)).toContain('POST /api/jobs/job-1/retry')

  state.vacancies = [vacancy()]
  expect(
    await screen.findByRole('button', { name: 'Your vacancy is ready to be viewed' }),
  ).toBeInTheDocument()
})

test('a refusal from the server is shown in the dialog', async () => {
  mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancy-options': () => json(200, OPTIONS),
    'GET /api/vacancies': () => json(200, []),
    'POST /api/vacancies': () =>
      json(409, {
        error: 'limit_reached',
        message: 'This demo workspace has used all 10 vacancy generations.',
      }),
  })
  render(<App />)

  const { dialog } = await fillAndSubmit()

  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    'This demo workspace has used all 10 vacancy generations.',
  )
  // The form is still there, with what was typed.
  expect(within(dialog).getByLabelText('Vacancy title')).toHaveValue('Cloud Engineer')
})

test('the dialog closes with Escape and opens empty the next time', async () => {
  backend()
  render(<App />)
  const { user, dialog } = await openDialog()
  await user.type(within(dialog).getByLabelText('Vacancy title'), 'Half typed')

  await user.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  // Focus goes back to the button that opened the dialog.
  expect(screen.getByRole('button', { name: 'Generate vacancy' })).toHaveFocus()

  const reopened = await openDialog()
  expect(within(reopened.dialog).getByLabelText('Vacancy title')).toHaveValue('')
})

test('focus stays inside the open dialog', async () => {
  backend()
  render(<App />)
  const { user, dialog } = await openDialog()

  for (let presses = 0; presses < 25; presses += 1) {
    await user.tab()
    expect(dialog.contains(document.activeElement)).toBe(true)
  }
})

test('flagged wording is shown for review', async () => {
  backend([
    vacancy({
      flags: [
        { section: 'required_qualifications', term: 'young', attribute: 'age' },
      ],
    }),
  ])
  const user = userEvent.setup()
  render(<App />)

  await user.click(
    await screen.findByRole('button', { name: 'Your vacancy is ready to be viewed' }),
  )

  const flags = await screen.findByRole('region', { name: 'Wording to review' })
  expect(flags).toHaveTextContent('“young” in Required qualifications (age)')
})

test('reset demo states what is deleted and needs confirmation', async () => {
  const { calls } = backend([vacancy()])
  mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancies': () =>
      json(200, calls.some((c) => c.route === 'POST /api/workspace/reset') ? [] : [vacancy()]),
    'POST /api/workspace/reset': () => {
      calls.push({ route: 'POST /api/workspace/reset', body: null })
      return new Response(null, { status: 204 })
    },
  })
  const user = userEvent.setup()
  render(<App />)
  await screen.findByRole('button', { name: 'Your vacancy is ready to be viewed' })

  await user.click(screen.getByRole('button', { name: 'Reset demo' }))
  const dialog = await screen.findByRole('alertdialog', { name: 'Reset the demo?' })
  expect(dialog).toHaveTextContent(
    'This permanently deletes every vacancy in your workspace, with its candidates, selection script, lists and interview questions.',
  )
  expect(dialog).toHaveTextContent('The limits of this demo workspace are not reset.')

  await user.click(within(dialog).getByRole('button', { name: 'Keep my work' }))
  expect(calls.some((c) => c.route === 'POST /api/workspace/reset')).toBe(false)

  await user.click(screen.getByRole('button', { name: 'Reset demo' }))
  await user.click(await screen.findByRole('button', { name: 'Delete everything' }))

  expect(await screen.findByText(/Nothing here yet/)).toBeInTheDocument()
  expect(calls.some((c) => c.route === 'POST /api/workspace/reset')).toBe(true)
})
