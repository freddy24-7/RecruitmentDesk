import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App.tsx'
import { json, mockApi, SESSION } from './test/api.ts'

// "TESTA" is an obviously fake code. Real codes never appear in the repository.

const NO_SESSION = () => json(401, { error: 'no_session' })

afterEach(() => {
  vi.unstubAllGlobals()
})

async function enterCode(code: string) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Access code'), code)
  await user.click(screen.getByRole('button', { name: 'Enter' }))
}

test('without a session only the code entry screen is shown', async () => {
  mockApi({ 'GET /api/session': NO_SESSION })

  render(<App />)

  expect(await screen.findByLabelText('Access code')).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Generate vacancy' }),
  ).not.toBeInTheDocument()
})

test('with a session the code is not asked for again', async () => {
  const calls = mockApi({
    'GET /api/session': () => json(200, SESSION),
    'GET /api/vacancies': () => json(200, []),
  })

  render(<App />)

  expect(
    await screen.findByRole('button', { name: 'Generate vacancy' }),
  ).toBeInTheDocument()
  expect(screen.queryByLabelText('Access code')).not.toBeInTheDocument()
  // No code was redeemed.
  expect(calls.map((call) => call.route)).not.toContain('POST /api/session')
})

test('a valid code opens the workspace', async () => {
  const calls = mockApi({
    'GET /api/session': NO_SESSION,
    'POST /api/session': () => json(200, SESSION),
    'GET /api/vacancies': () => json(200, []),
  })
  render(<App />)

  await enterCode('testa')

  expect(
    await screen.findByRole('button', { name: 'Generate vacancy' }),
  ).toBeInTheDocument()
  // The code is sent in the request body, not in the URL.
  expect(calls).toContainEqual({
    route: 'POST /api/session',
    body: { code: 'testa' },
  })
})

test('an invalid code shows the message from the server', async () => {
  mockApi({
    'GET /api/session': NO_SESSION,
    'POST /api/session': () =>
      json(401, {
        error: 'invalid_code',
        message: 'That code is not valid. Check the code and try again.',
      }),
  })
  render(<App />)

  await enterCode('ZZZZZ')

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'That code is not valid. Check the code and try again.',
  )
  expect(screen.getByLabelText('Access code')).toBeInTheDocument()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})

test('a used-up code shows the message with a contact link', async () => {
  mockApi({
    'GET /api/session': NO_SESSION,
    'POST /api/session': () =>
      json(403, {
        error: 'code_exhausted',
        message:
          'This access code has been used the maximum number of times. Please contact the developer to get a new code.',
        contact_url: 'https://example.com/contact',
      }),
  })
  render(<App />)

  await enterCode('TESTA')

  expect(await screen.findByRole('alert')).toHaveTextContent(
    /used the maximum number of times/,
  )
  expect(
    screen.getByRole('link', { name: 'Contact the developer' }),
  ).toHaveAttribute('href', 'https://example.com/contact')
})

test('a lockout shows the message from the server', async () => {
  mockApi({
    'GET /api/session': NO_SESSION,
    'POST /api/session': () =>
      json(429, {
        error: 'too_many_attempts',
        message: 'Too many attempts. Please wait a while and try again.',
      }),
  })
  render(<App />)

  await enterCode('TESTA')

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Too many attempts. Please wait a while and try again.',
  )
})

test('the Enter button is disabled until something is typed', async () => {
  mockApi({ 'GET /api/session': NO_SESSION })
  const user = userEvent.setup()
  render(<App />)

  const button = await screen.findByRole('button', { name: 'Enter' })
  expect(button).toBeDisabled()

  await user.type(screen.getByLabelText('Access code'), '   ')
  expect(button).toBeDisabled()

  await user.type(screen.getByLabelText('Access code'), 'TESTA')
  expect(button).toBeEnabled()
})

test('a network failure while entering a code is reported', async () => {
  let first = true
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      if (first) {
        first = false
        return json(401, { error: 'no_session' })
      }
      throw new TypeError('network down')
    }),
  )
  render(<App />)

  await enterCode('TESTA')

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not reach the server. Please try again.',
  )
})

test('an unreachable server on page load is reported', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('network down')
    }),
  )

  render(<App />)

  expect(await screen.findByRole('alert')).toHaveTextContent(
    /could not reach the server/i,
  )
})

test('when the session ends, the visitor is back at the code entry screen', async () => {
  mockApi({
    'GET /api/session': () => json(200, SESSION),
    // The session expired between the two calls.
    'GET /api/vacancies': () =>
      json(401, { error: 'no_session', message: 'Enter an access code.' }),
  })

  render(<App />)

  expect(await screen.findByLabelText('Access code')).toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Generate vacancy' }),
  ).not.toBeInTheDocument()
})
