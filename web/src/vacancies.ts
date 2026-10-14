import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  cancelVacancy,
  generateCandidates,
  getCandidate,
  getListEntry,
  getLists,
  getScript,
  listCandidates,
  listVacancies,
  proposeScript,
  resetVacancy,
  retryJob,
  saveScript,
  saveSections,
  submitVacancy,
} from './api.ts'
import type { Job, ScriptItem, Vacancy, VacancySections } from './api.ts'

export const VACANCIES_KEY = ['vacancies']

export function isRunning(job: Job | null): boolean {
  return job?.status === 'queued' || job?.status === 'running'
}

export function jobIsRunning(vacancy: Vacancy): boolean {
  return isRunning(vacancy.job)
}

// How often to ask for news while a job runs. Short in tests, so they are fast.
const POLL_MS = import.meta.env.MODE === 'test' ? 20 : 1500

/**
 * All vacancies of this workspace, each with its latest job. While one is
 * being generated the list is fetched again every moment, so the screen
 * follows the job without blocking, also after a reload.
 */
export function useVacancies() {
  return useQuery({
    queryKey: VACANCIES_KEY,
    queryFn: listVacancies,
    refetchInterval: (query) =>
      query.state.data?.some(
        (vacancy) => vacancy.status === 'generating' || jobIsRunning(vacancy),
      )
        ? POLL_MS
        : false,
  })
}

export function useRetryJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: retryJob,
    onSettled: () => queryClient.invalidateQueries({ queryKey: VACANCIES_KEY }),
  })
}

export function describeChoices(vacancy: Vacancy): string {
  const { sector, seniority, work_mode } = vacancy.parameters
  return [sector, seniority.join(', '), work_mode.join(', ')].join(' · ')
}

/** Put a vacancy that the server just returned into the cached list. */
function useStoreVacancy() {
  const queryClient = useQueryClient()
  return (updated: Vacancy) =>
    queryClient.setQueryData<Vacancy[]>(VACANCIES_KEY, (current) =>
      current?.map((vacancy) => (vacancy.id === updated.id ? updated : vacancy)),
    )
}

export function useSaveSections(vacancyId: string) {
  const store = useStoreVacancy()
  return useMutation({
    mutationFn: (sections: VacancySections) => saveSections(vacancyId, sections),
    onSuccess: store,
  })
}

export function useResetVacancy(vacancyId: string) {
  const store = useStoreVacancy()
  return useMutation({
    mutationFn: () => resetVacancy(vacancyId),
    onSuccess: store,
  })
}

export function useSubmitVacancy(vacancyId: string) {
  const store = useStoreVacancy()
  return useMutation({
    mutationFn: () => submitVacancy(vacancyId),
    onSuccess: store,
  })
}

export function useCancelVacancy(vacancyId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => cancelVacancy(vacancyId),
    onSuccess: () =>
      queryClient.setQueryData<Vacancy[]>(VACANCIES_KEY, (current) =>
        current?.filter((vacancy) => vacancy.id !== vacancyId),
      ),
  })
}

export function useGenerateCandidates(vacancyId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ count, replace }: { count: number; replace: boolean }) =>
      generateCandidates(vacancyId, count, replace),
    onSettled: () => queryClient.invalidateQueries({ queryKey: VACANCIES_KEY }),
  })
}

/**
 * The candidates of a vacancy. The key includes how many are ready and which
 * job made them, so the list is fetched again while CVs come in and after a
 * new run.
 */
export function useCandidates(vacancy: Vacancy) {
  return useQuery({
    queryKey: [
      'candidates',
      vacancy.id,
      vacancy.candidates.count,
      vacancy.candidates.out_of_date,
      vacancy.job?.id,
    ],
    queryFn: () => listCandidates(vacancy.id),
  })
}

export function useCandidate(vacancyId: string, candidateId: string) {
  return useQuery({
    queryKey: ['candidate', vacancyId, candidateId],
    queryFn: () => getCandidate(vacancyId, candidateId),
  })
}

/**
 * The script and the latest proposal. The key includes the proposal job and
 * the vacancy version, so it is fetched again when either changes.
 */
export function useScript(vacancy: Vacancy, enabled: boolean) {
  return useQuery({
    queryKey: [
      'script',
      vacancy.id,
      vacancy.version,
      vacancy.script_job?.id,
      vacancy.script_job?.status,
      vacancy.script.exists,
    ],
    queryFn: () => getScript(vacancy.id),
    enabled,
  })
}

export function useProposeScript(vacancyId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => proposeScript(vacancyId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: VACANCIES_KEY }),
  })
}

export function useSaveScript(vacancyId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (items: ScriptItem[]) => saveScript(vacancyId, items),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: VACANCIES_KEY }),
  })
}

/** Both lists. Fetched again after a new run, and when they go out of date. */
export function useLists(vacancy: Vacancy) {
  return useQuery({
    queryKey: [
      'lists',
      vacancy.id,
      vacancy.screening_job?.id,
      vacancy.screening_job?.status,
      vacancy.lists.out_of_date,
    ],
    queryFn: () => getLists(vacancy.id),
    enabled: vacancy.lists.exist,
  })
}

export function useListEntry(vacancyId: string, candidateId: string) {
  return useQuery({
    queryKey: ['list-entry', vacancyId, candidateId],
    queryFn: () => getListEntry(vacancyId, candidateId),
  })
}
