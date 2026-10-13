import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import App from './App.tsx'

// "TESTA" is an obviously fake code. Real codes never appear in the repository.
const SESSION = { workspace_id: 'workspace-1', idle_hours: 24 }

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

test('without a session only the code entry screen is shown', async () => {
  fetchMock.mockResolvedValueOnce(json(401, { error: 'no_session' }))

  render(<App />)

  expect(await screen.findByLabelText('Access code')).toBeInTheDocument()
  expect(screen.queryByText(/workspace is ready/i)).not.toBeInTheDocument()
})

test('with a session the code is not asked for again', async () => {
  fetchMock.mockResolvedValueOnce(json(200, SESSION))

  render(<App />)

  expect(await screen.findByText(/workspace is ready/i)).toBeInTheDocument()
  expect(screen.queryByLabelText('Access code')).not.toBeInTheDocument()
  // Only the session check: no code was redeemed.
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(fetchMock).toHaveBeenCalledWith('/api/session')
})

test('a valid code opens the workspace', async () => {
  fetchMock.mockResolvedValueOnce(json(401, { error: 'no_session' }))
  fetchMock.mockResolvedValueOnce(json(200, SESSION))
  const user = userEvent.setup()
  render(<App />)

  await user.type(await screen.findByLabelText('Access code'), 'testa')
  await user.click(screen.getByRole('button', { name: 'Enter' }))

  expect(await screen.findByText(/workspace is ready/i)).toBeInTheDocument()
  // The code is sent in the request body, not in the URL.
  expect(fetchMock).toHaveBeenLastCalledWith('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: 'testa' }),
  })
})

test('an invalid code shows the message from the server', async () => {
  fetchMock.mockResolvedValueOnce(json(401, { error: 'no_session' }))
  fetchMock.mockResolvedValueOnce(
    json(401, {
      error: 'invalid_code',
      message: 'That code is not valid. Check the code and try again.',
    }),
  )
  const user = userEvent.setup()
  render(<App />)

  await user.type(await screen.findByLabelText('Access code'), 'ZZZZZ')
  await user.click(screen.getByRole('button', { name: 'Enter' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'That code is not valid. Check the code and try again.',
  )
  expect(screen.getByLabelText('Access code')).toBeInTheDocument()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})

test('a used-up code shows the message with a contact link', async () => {
  fetchMock.mockResolvedValueOnce(json(401, { error: 'no_session' }))
  fetchMock.mockResolvedValueOnce(
    json(403, {
      error: 'code_exhausted',
      message:
        'This access code has been used the maximum number of times. Please contact the developer to get a new code.',
      contact_url: 'https://example.com/contact',
    }),
  )
  const user = userEvent.setup()
  render(<App />)

  await user.type(await screen.findByLabelText('Access code'), 'TESTA')
  await user.click(screen.getByRole('button', { name: 'Enter' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    /used the maximum number of times/,
  )
  expect(
    screen.getByRole('link', { name: 'Contact the developer' }),
  ).toHaveAttribute('href', 'https://example.com/contact')
})

test('a lockout shows the message from the server', async () => {
  fetchMock.mockResolvedValueOnce(json(401, { error: 'no_session' }))
  fetchMock.mockResolvedValueOnce(
    json(429, {
      error: 'too_many_attempts',
      message: 'Too many attempts. Please wait a while and try again.',
    }),
  )
  const user = userEvent.setup()
  render(<App />)

  await user.type(await screen.findByLabelText('Access code'), 'TESTA')
  await user.click(screen.getByRole('button', { name: 'Enter' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Too many attempts. Please wait a while and try again.',
  )
})

test('the Enter button is disabled until something is typed', async () => {
  fetchMock.mockResolvedValueOnce(json(401, { error: 'no_session' }))
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
  fetchMock.mockResolvedValueOnce(json(401, { error: 'no_session' }))
  fetchMock.mockRejectedValueOnce(new TypeError('network down'))
  const user = userEvent.setup()
  render(<App />)

  await user.type(await screen.findByLabelText('Access code'), 'TESTA')
  await user.click(screen.getByRole('button', { name: 'Enter' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not reach the server. Please try again.',
  )
})

test('an unreachable server on page load is reported', async () => {
  fetchMock.mockRejectedValueOnce(new TypeError('network down'))

  render(<App />)

  expect(await screen.findByRole('alert')).toHaveTextContent(
    /could not reach the server/i,
  )
})
