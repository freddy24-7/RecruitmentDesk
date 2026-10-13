import type { VacancySections } from './api.ts'

export const SECTION_NAMES: Record<keyof VacancySections, string> = {
  title: 'Title',
  company_intro: 'About the company',
  role_summary: 'The role',
  responsibilities: 'Responsibilities',
  required_qualifications: 'Required qualifications',
  nice_to_haves: 'Nice to have',
  what_we_offer: 'What we offer',
  location_and_work_mode: 'Location and work mode',
}

/** The order in which the sections are shown and edited. */
export const SECTION_ORDER = Object.keys(SECTION_NAMES) as (keyof VacancySections)[]

export const LIST_SECTIONS: ReadonlySet<keyof VacancySections> = new Set([
  'responsibilities',
  'required_qualifications',
  'nice_to_haves',
  'what_we_offer',
])

/** Nice-to-haves may stay empty; everything else is needed to submit. */
export const OPTIONAL_SECTIONS: ReadonlySet<keyof VacancySections> = new Set([
  'nice_to_haves',
])

export function sectionName(section: string): string {
  return section in SECTION_NAMES
    ? SECTION_NAMES[section as keyof VacancySections]
    : section
}

/** In the editor every section is text. A list is one item per line. */
export type SectionTexts = Record<keyof VacancySections, string>

export function toTexts(sections: VacancySections): SectionTexts {
  const texts = {} as SectionTexts
  for (const key of SECTION_ORDER) {
    const value = sections[key]
    texts[key] = Array.isArray(value) ? value.join('\n') : value
  }
  return texts
}

function lines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
}

export function toSections(texts: SectionTexts): VacancySections {
  return {
    title: texts.title.trim(),
    company_intro: texts.company_intro.trim(),
    role_summary: texts.role_summary.trim(),
    responsibilities: lines(texts.responsibilities),
    required_qualifications: lines(texts.required_qualifications),
    nice_to_haves: lines(texts.nice_to_haves),
    what_we_offer: lines(texts.what_we_offer),
    location_and_work_mode: texts.location_and_work_mode.trim(),
  }
}

export function sameSections(a: VacancySections, b: VacancySections): boolean {
  return JSON.stringify(toTexts(a)) === JSON.stringify(toTexts(b))
}
