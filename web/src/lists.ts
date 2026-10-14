/** Names and types shared by the list pages. */

export type WhichList = 'long' | 'short'

/** Always visible on the lists (PRD F7). */
export const NOTICE = 'Suggestions to support a recruiter. A person decides.'

const FLAG_NAMES: Record<string, string> = {
  hard_requirement_not_met: 'Hard requirement not met',
  keyword_not_in_cv: 'Removed: the model named a keyword that is not in the CV',
  years_corrected: 'Corrected: years stated by the model did not match the CV',
  strength_unsupported: 'Removed: a strength that the CV does not support',
  concern_contradicted: 'Removed: a concern that the CV contradicts',
  sentence_unsupported: 'Removed: a sentence that the CV does not support',
}

export function flagName(kind: string): string {
  return FLAG_NAMES[kind] ?? kind
}

/** The request for a screening run. Owned by the workspace. */
export type StartScreening = {
  mutate: (replace: boolean) => void
  isPending: boolean
  error: Error | null
}
