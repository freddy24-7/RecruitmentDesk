import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.tsx'
import type { Job, Script, ScriptItem, Vacancy } from './api.ts'
import { job, json, mockApi, SESSION, SUBMITTED } from './test/api.ts'

afterEach(() => {
  vi.unstubAllGlobals()
})

function item(overrides: Partial<ScriptItem> = {}): ScriptItem {
  return {
    any_of: ['Microsoft Azure', 'AWS'],
    min_years: 3,
    kind: 'hard',
    reason: 'Experience with Microsoft Azure',
    grounded: true,
    enabled: true,
    ...overrides,
  }
}

const PROPOSED: ScriptItem[] = [
  item(),
  item({ any_of: ['Terraform'], min_years: 2, reason: '2 years of Terraform' }),
  item({
    any_of: ['Scrum'],
    min_years: 0,
    kind: 'soft',
    reason: 'Agile ways of working are a plus',
    grounded: false,
  }),
]

function scriptJob(overrides: Partial<Job> = {}): Job {
  return job({ id: 'job-3', type: 'script_proposal', status: 'running', ...overrides })
}

const READY = { exists: false, out_of_date: false, item_count: 0, proposal_ready: true }

/** A fake backend with one submitted vacancy and its script state. */
function backend(vacancy: Partial<Vacancy> = {}, script: Partial<Script> = {}) {
  const state: { vacancy: Vacancy; script: Script } = {
    vacancy: { ...SUBMITTED, ...vacancy },
    script: { saved: null, proposal: null, ...script },
  }
  const calls = mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancies': () => json(200, [state.vacancy]),
    'GET /api/vacancies/vacancy-1/script': () => json(200, state.script),
    'POST /api/vacancies/vacancy-1/script/proposal': () => {
      state.vacancy = { ...state.vacancy, script_job: scriptJob(), job: scriptJob() }
      return json(202, scriptJob())
    },
    'POST /api/jobs/job-3/retry': () => {
      state.vacancy = { ...state.vacancy, script_job: scriptJob(), job: scriptJob() }
      return json(202, scriptJob())
    },
    'PUT /api/vacancies/vacancy-1/script': (body) => {
      const { items } = body as { items: ScriptItem[] }
      state.script = {
        ...state.script,
        saved: {
          items,
          revision: (state.script.saved?.revision ?? 0) + 1,
          out_of_date: false,
          updated_at: '2026-10-13T14:00:00Z',
        },
      }
      state.vacancy = {
        ...state.vacancy,
        script: { ...state.vacancy.script, exists: true, out_of_date: false, item_count: items.length },
      }
      return json(200, state.script)
    },
  })
  /** As if the model finished its proposal. */
  const finishProposal = () => {
    const done = scriptJob({ status: 'done' })
    state.script = { ...state.script, proposal: { items: PROPOSED, current: true } }
    state.vacancy = { ...state.vacancy, script_job: done, job: done, script: READY }
  }
  return { state, calls, finishProposal }
}

function routes(calls: { route: string }[]): string[] {
  return calls.map((call) => call.route)
}

async function openDialog() {
  const user = userEvent.setup()
  render(<App />)
  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )
  await user.click(await screen.findByRole('button', { name: 'Open vacancy' }))
  await user.click(
    await screen.findByRole('button', { name: 'Generate selection script' }),
  )
  const dialog = await screen.findByRole('dialog', { name: 'Selection script' })
  return { user, dialog }
}

const withProposal = () =>
  backend(
    { script: READY, script_job: scriptJob({ status: 'done' }) },
    { proposal: { items: PROPOSED, current: true } },
  )

test('the dialog opens with a proposal from the model', async () => {
  const { calls, finishProposal } = backend()

  const { dialog } = await openDialog()

  // Nothing to show yet, so the model is asked, in the background.
  expect(await within(dialog).findByRole('status')).toHaveTextContent(
    'Reading the vacancy and proposing criteria…',
  )
  expect(routes(calls)).toContain('POST /api/vacancies/vacancy-1/script/proposal')

  finishProposal()

  // Keywords (with alternatives), years, and hard or soft, per item.
  const first = await within(dialog).findByRole('group', { name: 'Item 1' })
  expect(within(first).getByLabelText('Keywords')).toHaveValue('Microsoft Azure, AWS')
  expect(within(first).getByLabelText('Years')).toHaveValue('3')
  expect(within(first).getByLabelText('Requirement')).toHaveValue('hard')
  const third = within(dialog).getByRole('group', { name: 'Item 3' })
  expect(within(third).getByLabelText('Keywords')).toHaveValue('Scrum')
  expect(within(third).getByLabelText('Requirement')).toHaveValue('soft')
})

test('each item shows its reason, and says when it is not in the vacancy', async () => {
  withProposal()

  const { dialog } = await openDialog()

  const first = await within(dialog).findByRole('group', { name: 'Item 1' })
  expect(first).toHaveTextContent(
    'From the vacancy: “Experience with Microsoft Azure”',
  )
  expect(within(dialog).getByRole('group', { name: 'Item 3' })).toHaveTextContent(
    'Reason given by the model, not found in the vacancy text: “Agile ways of working are a plus”',
  )
})

test('a waiting proposal is not asked for, and paid for, a second time', async () => {
  const { calls } = withProposal()

  const { dialog } = await openDialog()
  await within(dialog).findByRole('group', { name: 'Item 1' })

  expect(routes(calls)).not.toContain('POST /api/vacancies/vacancy-1/script/proposal')
})

test('the recruiter edits, removes and adds items, and submit saves the script', async () => {
  const { calls } = withProposal()
  const { user, dialog } = await openDialog()
  const first = await within(dialog).findByRole('group', { name: 'Item 1' })

  // Edit the keywords and the years.
  await user.clear(within(first).getByLabelText('Keywords'))
  await user.type(within(first).getByLabelText('Keywords'), 'Azure,  AWS , GCP')
  await user.clear(within(first).getByLabelText('Years'))
  await user.type(within(first).getByLabelText('Years'), '5')
  // Flip hard to soft.
  await user.selectOptions(
    within(within(dialog).getByRole('group', { name: 'Item 2' })).getByLabelText(
      'Requirement',
    ),
    'soft',
  )
  // Remove one, add one.
  await user.click(within(dialog).getByRole('button', { name: 'Remove item 3' }))
  await user.click(within(dialog).getByRole('button', { name: 'Add item' }))
  const added = within(dialog).getByRole('group', { name: 'Item 3' })
  await user.type(within(added).getByLabelText('Keywords'), 'Python')
  await user.selectOptions(within(added).getByLabelText('Requirement'), 'hard')

  await user.click(within(dialog).getByRole('button', { name: 'Submit' }))

  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(calls).toContainEqual({
    route: 'PUT /api/vacancies/vacancy-1/script',
    body: {
      items: [
        {
          any_of: ['Azure', 'AWS', 'GCP'],
          min_years: 5,
          kind: 'hard',
          reason: 'Experience with Microsoft Azure',
          grounded: false,
          enabled: true,
        },
        {
          any_of: ['Terraform'],
          min_years: 2,
          kind: 'soft',
          reason: '2 years of Terraform',
          grounded: false,
          enabled: true,
        },
        {
          any_of: ['Python'],
          min_years: 0,
          kind: 'hard',
          reason: '',
          grounded: false,
          enabled: true,
        },
      ],
    },
  })
  expect(await screen.findByText('Selection script ready (3 items).')).toBeInTheDocument()
})

test('cancel saves nothing', async () => {
  const { calls } = withProposal()
  const { user, dialog } = await openDialog()
  const first = await within(dialog).findByRole('group', { name: 'Item 1' })
  await user.type(within(first).getByLabelText('Keywords'), ', GCP')

  await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))

  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(routes(calls).some((route) => route.startsWith('PUT'))).toBe(false)
  expect(screen.queryByText(/Selection script ready/)).not.toBeInTheDocument()
})

test('escape also closes without saving', async () => {
  const { calls } = withProposal()
  const { user, dialog } = await openDialog()
  await within(dialog).findByRole('group', { name: 'Item 1' })

  await user.keyboard('{Escape}')

  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(routes(calls).some((route) => route.startsWith('PUT'))).toBe(false)
})

test.each([
  ['Keywords', '', 'Enter at least one keyword.'],
  ['Keywords', 'a, b, c, d, e', 'Use at most 4 alternatives.'],
  ['Years', '21', 'Years must be a whole number from 0 to 20.'],
  ['Years', 'two', 'Years must be a whole number from 0 to 20.'],
  ['Years', '2.5', 'Years must be a whole number from 0 to 20.'],
])('an invalid %s value "%s" is explained and nothing is saved', async (field, value, message) => {
  const { calls } = withProposal()
  const { user, dialog } = await openDialog()
  const first = await within(dialog).findByRole('group', { name: 'Item 1' })

  await user.clear(within(first).getByLabelText(field))
  if (value) {
    await user.type(within(first).getByLabelText(field), value)
  }
  await user.click(within(dialog).getByRole('button', { name: 'Submit' }))

  expect(within(first).getByText(message)).toBeInTheDocument()
  expect(routes(calls).some((route) => route.startsWith('PUT'))).toBe(false)
  expect(screen.getByRole('dialog')).toBeInTheDocument()
})

test('a script without items cannot be submitted', async () => {
  const { calls } = withProposal()
  const { user, dialog } = await openDialog()
  await within(dialog).findByRole('group', { name: 'Item 1' })

  for (const number of [3, 2, 1]) {
    await user.click(
      within(dialog).getByRole('button', { name: `Remove item ${number}` }),
    )
  }
  await user.click(within(dialog).getByRole('button', { name: 'Submit' }))

  expect(
    within(dialog).getByText('The script has no items. Add at least one.'),
  ).toBeInTheDocument()
  expect(routes(calls).some((route) => route.startsWith('PUT'))).toBe(false)
})

test('the dialog explains hard, soft and alternatives', async () => {
  withProposal()

  const { dialog } = await openDialog()
  await within(dialog).findByRole('group', { name: 'Item 1' })

  expect(dialog).toHaveTextContent('Hard: a candidate must meet it to be listed.')
  expect(dialog).toHaveTextContent('Soft: it adds to the score but is not required.')
  expect(dialog).toHaveTextContent('years are not added up across alternatives')
})

test('a saved script opens for editing, not the old proposal', async () => {
  backend(
    { script: { exists: true, out_of_date: false, item_count: 1, proposal_ready: true } },
    {
      saved: {
        items: [item({ any_of: ['Kubernetes'], min_years: 1, kind: 'soft' })],
        revision: 2,
        out_of_date: false,
        updated_at: '2026-10-13T14:00:00Z',
      },
      proposal: { items: PROPOSED, current: true },
    },
  )

  const { dialog } = await openDialog()

  const first = await within(dialog).findByRole('group', { name: 'Item 1' })
  expect(within(first).getByLabelText('Keywords')).toHaveValue('Kubernetes')
  expect(within(dialog).queryByRole('group', { name: 'Item 2' })).not.toBeInTheDocument()
  expect(dialog).toHaveTextContent('The saved script for this vacancy.')
})

test('a script of an edited vacancy is marked out of date', async () => {
  backend(
    { script: { exists: true, out_of_date: true, item_count: 1, proposal_ready: false } },
    {
      saved: {
        items: [item()],
        revision: 1,
        out_of_date: true,
        updated_at: '2026-10-13T14:00:00Z',
      },
    },
  )
  const user = userEvent.setup()
  render(<App />)
  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )

  // On the list, as a status chip.
  const chips = await screen.findByRole('list', { name: 'Status' })
  expect(within(chips).getByText('script out of date')).toBeInTheDocument()

  // On the vacancy.
  await user.click(screen.getByRole('button', { name: 'Open vacancy' }))
  expect(await screen.findByText(/Selection script out of date\./)).toBeInTheDocument()

  // In the dialog, where it is still there to review: not thrown away.
  await user.click(screen.getByRole('button', { name: 'Generate selection script' }))
  const dialog = await screen.findByRole('dialog', { name: 'Selection script' })
  expect(await within(dialog).findByRole('note')).toHaveTextContent(
    'Out of date. The vacancy was edited after this script was saved.',
  )
  expect(
    within(within(dialog).getByRole('group', { name: 'Item 1' })).getByLabelText('Keywords'),
  ).toHaveValue('Microsoft Azure, AWS')
})

test('a ready script shows as a status chip', async () => {
  backend({
    script: { exists: true, out_of_date: false, item_count: 4, proposal_ready: true },
  })
  const user = userEvent.setup()
  render(<App />)

  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )

  const chips = await screen.findByRole('list', { name: 'Status' })
  expect(within(chips).getByText('script ready')).toBeInTheDocument()
})

test('a proposal that fails shows the message and can be retried', async () => {
  const { state, calls } = backend()
  const { user, dialog } = await openDialog()
  await within(dialog).findByRole('status')

  // The job fails on the server while the dialog is open.
  const failed = scriptJob({
    status: 'failed',
    error_kind: 'llm_rate_limited',
    message: 'The model is busy right now. Please try again in a moment.',
  })
  state.vacancy = { ...state.vacancy, script_job: failed, job: failed }

  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    'The model is busy right now. Please try again in a moment.',
  )
  await user.click(within(dialog).getByRole('button', { name: 'Retry' }))

  expect(await within(dialog).findByRole('status')).toBeInTheDocument()
  expect(routes(calls)).toContain('POST /api/jobs/job-3/retry')
})

test('a new proposal can be asked for from the dialog', async () => {
  const { calls } = withProposal()
  const { user, dialog } = await openDialog()
  await within(dialog).findByRole('group', { name: 'Item 1' })

  await user.click(within(dialog).getByRole('button', { name: 'Ask for a new proposal' }))

  expect(await within(dialog).findByRole('status')).toHaveTextContent(
    'Reading the vacancy and proposing criteria…',
  )
  expect(routes(calls)).toContain('POST /api/vacancies/vacancy-1/script/proposal')
})

test('a refusal to propose is shown in the dialog', async () => {
  mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancies': () => json(200, [SUBMITTED]),
    'GET /api/vacancies/vacancy-1/script': () =>
      json(200, { saved: null, proposal: null }),
    'POST /api/vacancies/vacancy-1/script/proposal': () =>
      json(409, {
        error: 'limit_reached',
        message:
          'This demo workspace has used all 20 script proposals. You can still edit and save the script by hand.',
      }),
  })

  const { dialog } = await openDialog()

  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    'This demo workspace has used all 20 script proposals.',
  )
})
