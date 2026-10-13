import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  cancelVacancy,
  listVacancies,
  resetVacancy,
  retryJob,
  saveSections,
  submitVacancy,
} from './api.ts'
import type { Vacancy, VacancySections } from './api.ts'

export const VACANCIES_KEY = ['vacancies']

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
      query.state.data?.some((vacancy) => vacancy.status === 'generating')
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
