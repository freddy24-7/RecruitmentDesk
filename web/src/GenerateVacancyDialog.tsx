import * as Dialog from '@radix-ui/react-dialog'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { generateVacancy, getVacancyOptions } from './api.ts'
import type { VacancyChoices, VacancyOptions } from './api.ts'
import Spinner from './Spinner.tsx'
import { useVacancies, VACANCIES_KEY } from './vacancies.ts'
import VacancyStatus from './VacancyStatus.tsx'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  onView: (vacancyId: string) => void
}

/**
 * The "Generate vacancy" dialog. Radix Dialog traps focus, closes on Escape
 * and labels the dialog for screen readers.
 */
function GenerateVacancyDialog({ open, onOpenChange, onView }: Props) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog">
          <Dialog.Title>Generate vacancy</Dialog.Title>
          {/* Mounted only while open, so every visit starts with an empty form. */}
          <DialogBody
            onView={(vacancyId) => {
              onOpenChange(false)
              onView(vacancyId)
            }}
          />
          <Dialog.Close asChild>
            <button type="button" className="dialog-close" aria-label="Close">
              ×
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function DialogBody({ onView }: { onView: (vacancyId: string) => void }) {
  const options = useQuery({
    queryKey: ['vacancy-options'],
    queryFn: getVacancyOptions,
    staleTime: Infinity,
  })
  // Set once the job has started: from then on the dialog follows that vacancy.
  const [vacancyId, setVacancyId] = useState<string | null>(null)

  if (vacancyId !== null) {
    return <Progress vacancyId={vacancyId} onView={onView} />
  }
  if (options.isPending) {
    return <Spinner label="Loading…" />
  }
  if (options.isError) {
    return (
      <p role="alert" className="problem">
        {options.error.message}
      </p>
    )
  }
  return <ChoicesForm options={options.data} onStarted={setVacancyId} />
}

function Progress({
  vacancyId,
  onView,
}: {
  vacancyId: string
  onView: (vacancyId: string) => void
}) {
  const vacancies = useVacancies()
  const vacancy = vacancies.data?.find((candidate) => candidate.id === vacancyId)

  if (!vacancy) {
    return <Spinner label="Writing the vacancy…" />
  }
  return (
    <div>
      <VacancyStatus vacancy={vacancy} onView={onView} />
      {vacancy.status === 'generating' && (
        <Dialog.Description>
          This takes a moment. You can close this window: the vacancy keeps
          being written and will be waiting for you.
        </Dialog.Description>
      )}
    </div>
  )
}

function toggle(values: string[], value: string): string[] {
  return values.includes(value)
    ? values.filter((existing) => existing !== value)
    : [...values, value]
}

function ChoicesForm({
  options,
  onStarted,
}: {
  options: VacancyOptions
  onStarted: (vacancyId: string) => void
}) {
  const queryClient = useQueryClient()
  const [sector, setSector] = useState(options.sectors[0] ?? '')
  const [seniority, setSeniority] = useState<string[]>([])
  const [workMode, setWorkMode] = useState<string[]>([])
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState('')
  const [emphasis, setEmphasis] = useState('')
  const [checked, setChecked] = useState(false)

  const start = useMutation({
    mutationFn: (choices: VacancyChoices) => generateVacancy(choices),
    onSuccess: async (started) => {
      await queryClient.invalidateQueries({ queryKey: VACANCIES_KEY })
      onStarted(started.vacancy_id)
    },
  })

  const problems = {
    title: title.trim().length < 2 ? 'Enter a vacancy title.' : null,
    seniority: seniority.length === 0 ? 'Choose at least one seniority.' : null,
    workMode: workMode.length === 0 ? 'Choose at least one work mode.' : null,
  }
  const valid = !problems.title && !problems.seniority && !problems.workMode

  function submit(event: FormEvent) {
    event.preventDefault()
    setChecked(true)
    if (!valid) {
      return
    }
    start.mutate({
      sector,
      seniority,
      work_mode: workMode,
      title: title.trim(),
      company: company.trim() || null,
      emphasis: emphasis.trim() || null,
    })
  }

  return (
    <form onSubmit={submit} noValidate>
      <Dialog.Description>
        Make a few choices. The model writes a vacancy that you can review
        before anything is submitted.
      </Dialog.Description>

      <div className="field">
        <label htmlFor="vacancy-title">Vacancy title</label>
        <input
          id="vacancy-title"
          type="text"
          value={title}
          maxLength={options.title_max}
          onChange={(event) => setTitle(event.target.value)}
          aria-invalid={checked && problems.title ? true : undefined}
          aria-describedby={
            checked && problems.title ? 'vacancy-title-problem' : undefined
          }
        />
        {checked && problems.title && (
          <p id="vacancy-title-problem" className="problem">
            {problems.title}
          </p>
        )}
      </div>

      <div className="field">
        <label htmlFor="vacancy-sector">Sector</label>
        <select
          id="vacancy-sector"
          value={sector}
          onChange={(event) => setSector(event.target.value)}
        >
          {options.sectors.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      <fieldset
        aria-describedby={
          checked && problems.seniority ? 'seniority-problem' : undefined
        }
      >
        <legend>Seniority</legend>
        {options.seniorities.map((level) => (
          <label key={level} className="choice">
            <input
              type="checkbox"
              checked={seniority.includes(level)}
              onChange={() => setSeniority(toggle(seniority, level))}
            />
            {level}
          </label>
        ))}
        {checked && problems.seniority && (
          <p id="seniority-problem" className="problem">
            {problems.seniority}
          </p>
        )}
      </fieldset>

      <fieldset
        aria-describedby={
          checked && problems.workMode ? 'work-mode-problem' : undefined
        }
      >
        <legend>Work mode</legend>
        {options.work_modes.map((mode) => (
          <label key={mode} className="choice">
            <input
              type="checkbox"
              checked={workMode.includes(mode)}
              onChange={() => setWorkMode(toggle(workMode, mode))}
            />
            {mode}
          </label>
        ))}
        {checked && problems.workMode && (
          <p id="work-mode-problem" className="problem">
            {problems.workMode}
          </p>
        )}
      </fieldset>

      <div className="field">
        <label htmlFor="vacancy-company">Company name (optional)</label>
        <input
          id="vacancy-company"
          type="text"
          value={company}
          maxLength={options.company_max}
          onChange={(event) => setCompany(event.target.value)}
          aria-describedby="vacancy-company-hint"
        />
        <p id="vacancy-company-hint" className="hint">
          Leave empty to have a fictional name made up.
        </p>
      </div>

      <div className="field">
        <label htmlFor="vacancy-emphasis">Anything to emphasise (optional)</label>
        <textarea
          id="vacancy-emphasis"
          value={emphasis}
          rows={3}
          maxLength={options.emphasis_max}
          onChange={(event) => setEmphasis(event.target.value)}
        />
      </div>

      {start.isError && (
        <p role="alert" className="problem">
          {start.error.message}
        </p>
      )}

      <div className="actions">
        <Dialog.Close asChild>
          <button type="button">Cancel</button>
        </Dialog.Close>
        <button type="submit" className="primary" disabled={start.isPending}>
          {start.isPending ? 'Starting…' : 'Generate'}
        </button>
      </div>
    </form>
  )
}

export default GenerateVacancyDialog
