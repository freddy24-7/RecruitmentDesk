import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.tsx'
import type { Vacancy, VacancySections } from './api.ts'
import { FAILED, json, mockApi, SESSION, SUBMITTED, vacancy } from './test/api.ts'

afterEach(() => {
  vi.unstubAllGlobals()
})

const GENERATED = vacancy().sections as VacancySections

/** A fake backend that keeps one vacancy and behaves like the real one. */
function backend(initial: Vacancy) {
  const state: { vacancies: Vacancy[] } = { vacancies: [initial] }
  const current = () => state.vacancies[0] as Vacancy
  const replace = (changes: Partial<Vacancy>) => {
    state.vacancies = [{ ...current(), ...changes }]
    return json(200, current())
  }
  const calls = mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancies': () => json(200, state.vacancies),
    'PUT /api/vacancies/vacancy-1/sections': (body) =>
      replace({
        sections: body as VacancySections,
        version: current().version + 1,
        edited: true,
      }),
    'POST /api/vacancies/vacancy-1/reset': () =>
      replace({
        sections: GENERATED,
        version: current().version + 1,
        edited: false,
      }),
    'POST /api/vacancies/vacancy-1/submit': () =>
      replace({
        status: 'submitted',
        submitted_at: '2026-10-13T13:00:00Z',
        actions: SUBMITTED.actions,
      }),
    'DELETE /api/vacancies/vacancy-1?confirm=true': () => {
      state.vacancies = []
      return new Response(null, { status: 204 })
    },
  })
  return { state, calls }
}

async function openDraft() {
  const user = userEvent.setup()
  render(<App />)
  await user.click(
    await screen.findByRole('button', { name: 'Your vacancy is ready to be viewed' }),
  )
  await screen.findByLabelText('The role')
  return user
}

function routes(calls: { route: string }[]): string[] {
  return calls.map((call) => call.route)
}

test('the review shows every section in an editable field', async () => {
  backend(vacancy())

  await openDraft()

  expect(screen.getByLabelText('Title')).toHaveValue('Cloud Engineer')
  expect(screen.getByLabelText('About the company')).toHaveValue(
    'Tulip Systems is a fictional company.',
  )
  expect(screen.getByLabelText('The role')).toHaveValue(
    'You build and run cloud platforms.',
  )
  // A list is edited as one item per line.
  expect(screen.getByLabelText('Responsibilities')).toHaveValue(
    'Design cloud infrastructure\nReview code',
  )
  expect(screen.getByLabelText('Required qualifications')).toBeInTheDocument()
  expect(screen.getByLabelText('Nice to have (optional)')).toBeInTheDocument()
  expect(screen.getByLabelText('What we offer')).toBeInTheDocument()
  expect(screen.getByLabelText('Location and work mode')).toBeInTheDocument()
  expect(screen.getByText(/Version 1, as generated/)).toBeInTheDocument()
})

test('an edit is saved as a new version', async () => {
  const { calls } = backend(vacancy())
  const user = await openDraft()
  const saveButton = screen.getByRole('button', { name: 'Save changes' })
  expect(saveButton).toBeDisabled()

  const responsibilities = screen.getByLabelText('Responsibilities')
  await user.clear(responsibilities)
  await user.type(responsibilities, 'Lead the team\n\n  Mentor engineers  ')
  expect(screen.getByText(/You have unsaved changes/)).toBeInTheDocument()
  await user.click(saveButton)

  expect(await screen.findByText(/Version 2, edited by you/)).toBeInTheDocument()
  expect(calls).toContainEqual({
    route: 'PUT /api/vacancies/vacancy-1/sections',
    body: { ...GENERATED, responsibilities: ['Lead the team', 'Mentor engineers'] },
  })
  expect(screen.getByLabelText('Responsibilities')).toHaveValue(
    'Lead the team\nMentor engineers',
  )
  expect(saveButton).toBeDisabled()
})

test('reset asks for confirmation and then brings back the generated text', async () => {
  const { calls } = backend(
    vacancy({
      sections: { ...GENERATED, role_summary: 'My own words.' },
      version: 2,
      edited: true,
    }),
  )
  const user = await openDraft()
  expect(screen.getByLabelText('The role')).toHaveValue('My own words.')

  await user.click(screen.getByRole('button', { name: 'Reset to generated' }))
  const dialog = await screen.findByRole('alertdialog', {
    name: 'Reset to the generated text?',
  })
  // The dialog says what will be lost.
  expect(dialog).toHaveTextContent('All your edits to this vacancy are lost')

  // Declining changes nothing.
  await user.click(within(dialog).getByRole('button', { name: 'Keep my edits' }))
  expect(routes(calls)).not.toContain('POST /api/vacancies/vacancy-1/reset')
  expect(screen.getByLabelText('The role')).toHaveValue('My own words.')

  await user.click(screen.getByRole('button', { name: 'Reset to generated' }))
  await user.click(await screen.findByRole('button', { name: 'Reset' }))

  await waitFor(() =>
    expect(screen.getByLabelText('The role')).toHaveValue(
      'You build and run cloud platforms.',
    ),
  )
  expect(await screen.findByText(/Version 3, as generated/)).toBeInTheDocument()
})

test('reset is not offered when there is nothing to reset', async () => {
  backend(vacancy())

  await openDraft()

  expect(screen.getByRole('button', { name: 'Reset to generated' })).toBeDisabled()
})

test('cancel vacancy states what is deleted and does nothing without confirmation', async () => {
  const { calls } = backend(vacancy())
  const user = await openDraft()

  await user.click(screen.getByRole('button', { name: 'Cancel vacancy' }))

  const dialog = await screen.findByRole('alertdialog', {
    name: 'Cancel this vacancy?',
  })
  expect(dialog).toHaveTextContent('the vacancy “Cloud Engineer”')
  expect(dialog).toHaveTextContent('its generated text and all your edits')
  expect(dialog).toHaveTextContent('This cannot be undone.')

  await user.click(within(dialog).getByRole('button', { name: 'Keep vacancy' }))

  await waitFor(() =>
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument(),
  )
  // Focus goes back to the button that opened the confirmation.
  expect(screen.getByRole('button', { name: 'Cancel vacancy' })).toHaveFocus()
  expect(routes(calls).some((route) => route.startsWith('DELETE'))).toBe(false)
  expect(screen.getByLabelText('Title')).toHaveValue('Cloud Engineer')
})

test('confirming cancel deletes the vacancy and returns to the start', async () => {
  const { calls } = backend(vacancy())
  const user = await openDraft()

  await user.click(screen.getByRole('button', { name: 'Cancel vacancy' }))
  await user.click(await screen.findByRole('button', { name: 'Delete vacancy' }))

  expect(await screen.findByRole('heading', { name: 'Drafts' })).toBeInTheDocument()
  expect(screen.getByText(/Nothing here yet/)).toBeInTheDocument()
  // The confirmation flag is part of the request.
  expect(routes(calls)).toContain('DELETE /api/vacancies/vacancy-1?confirm=true')
})

test('escape closes the cancel confirmation without deleting', async () => {
  const { calls } = backend(vacancy())
  const user = await openDraft()
  await user.click(screen.getByRole('button', { name: 'Cancel vacancy' }))
  await screen.findByRole('alertdialog')

  await user.keyboard('{Escape}')

  await waitFor(() =>
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument(),
  )
  expect(routes(calls).some((route) => route.startsWith('DELETE'))).toBe(false)
})

test('submit saves unsaved edits first and moves the vacancy to submitted', async () => {
  const { calls } = backend(vacancy())
  const user = await openDraft()
  const role = screen.getByLabelText('The role')
  await user.clear(role)
  await user.type(role, 'You lead the platform team.')

  await user.click(screen.getByRole('button', { name: 'Submit vacancy' }))

  expect(
    await screen.findByRole('heading', { name: 'Submitted vacancies' }),
  ).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Cloud Engineer' })).toBeInTheDocument()
  expect(screen.getByText(/Submitted on 13 October 2026/)).toBeInTheDocument()
  expect(screen.queryByText('No vacancies have yet been submitted')).toBeNull()
  const made = routes(calls)
  expect(made.indexOf('PUT /api/vacancies/vacancy-1/sections')).toBeGreaterThan(-1)
  expect(made.indexOf('POST /api/vacancies/vacancy-1/submit')).toBeGreaterThan(
    made.indexOf('PUT /api/vacancies/vacancy-1/sections'),
  )
  // It left the drafts.
  await user.click(screen.getByRole('button', { name: 'RecruitDesk' }))
  expect(await screen.findByText(/Nothing here yet/)).toBeInTheDocument()
})

test('a refused submit shows which sections are empty', async () => {
  mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancies': () => json(200, [vacancy()]),
    'POST /api/vacancies/vacancy-1/submit': () =>
      json(422, {
        error: 'sections_incomplete',
        message: 'These sections are still empty: Responsibilities.',
      }),
  })
  const user = await openDraft()

  await user.click(screen.getByRole('button', { name: 'Submit vacancy' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'These sections are still empty: Responsibilities.',
  )
  expect(screen.getByLabelText('Title')).toBeInTheDocument()
})

test('a submitted vacancy shows its text and its actions', async () => {
  backend(SUBMITTED)
  const user = userEvent.setup()
  render(<App />)
  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )

  await user.click(await screen.findByRole('button', { name: 'Open vacancy' }))

  expect(
    await screen.findByRole('heading', { name: 'Responsibilities' }),
  ).toBeInTheDocument()
  expect(screen.getByText('Design cloud infrastructure')).toBeInTheDocument()
  // Read-only until "Edit vacancy" is chosen.
  expect(screen.queryByLabelText('The role')).not.toBeInTheDocument()
  const actions = screen.getByRole('list', { name: 'Actions' })
  expect(
    within(actions)
      .getAllByRole('button')
      .map((button) => button.textContent),
  ).toEqual([
    'Edit vacancy',
    'Generate candidates',
    'Generate selection script',
    'Generate long-list',
    'Generate short-list',
  ])
})

test('actions with missing prerequisites are visible, disabled, and say why', async () => {
  const { calls } = backend(SUBMITTED)
  const user = userEvent.setup()
  render(<App />)
  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )
  await user.click(await screen.findByRole('button', { name: 'Open vacancy' }))

  const longList = await screen.findByRole('button', { name: 'Generate long-list' })
  expect(longList).toHaveAttribute('aria-disabled', 'true')
  expect(longList).toHaveAccessibleDescription(
    'Generate candidates and a selection script first.',
  )
  expect(screen.getByRole('button', { name: 'Edit vacancy' })).not.toHaveAttribute(
    'aria-disabled',
  )

  const before = calls.length
  await user.click(longList)
  expect(calls.length).toBe(before)
})

test('edit vacancy opens the same editor, without cancel or submit', async () => {
  backend(SUBMITTED)
  const user = userEvent.setup()
  render(<App />)
  await user.click(
    await screen.findByRole('button', { name: 'Submitted vacancies' }),
  )
  await user.click(await screen.findByRole('button', { name: 'Open vacancy' }))

  await user.click(await screen.findByRole('button', { name: 'Edit vacancy' }))

  const role = await screen.findByLabelText('The role')
  expect(
    screen.queryByRole('button', { name: 'Cancel vacancy' }),
  ).not.toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Submit vacancy' }),
  ).not.toBeInTheDocument()

  await user.clear(role)
  await user.type(role, 'Sharper wording.')
  await user.click(screen.getByRole('button', { name: 'Save changes' }))
  expect(await screen.findByText(/Version 2, edited by you/)).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Stop editing' }))
  expect(await screen.findByText('Sharper wording.')).toBeInTheDocument()
  expect(screen.queryByLabelText('The role')).not.toBeInTheDocument()
})

test('a failed vacancy can be cancelled from its card, after confirmation', async () => {
  const { calls } = backend(FAILED)
  const user = userEvent.setup()
  render(<App />)

  await user.click(await screen.findByRole('button', { name: 'Cancel vacancy' }))
  const dialog = await screen.findByRole('alertdialog')
  expect(dialog).toHaveTextContent('the vacancy “Cloud Engineer”')
  await user.click(within(dialog).getByRole('button', { name: 'Delete vacancy' }))

  expect(await screen.findByText(/Nothing here yet/)).toBeInTheDocument()
  expect(routes(calls)).toContain('DELETE /api/vacancies/vacancy-1?confirm=true')
})
