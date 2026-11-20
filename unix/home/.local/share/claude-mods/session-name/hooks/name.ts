// Pure helpers of the session-name mod: no `$` here, because a hooks module
// may not pass `$` to a function it imports (plugins/mods/create, static
// analysis rules). `register.ts` holds every engine call.

// The D61 stamp (claude-code-marketplace session-start, D61/D208): /bin/date
// with this format, its %z cut to the hour (`-0600` -> `-06`), validated before
// use. python/agents/tabname.py builds the launcher's names on the same shape.
export const DATE_ARGV = ['/bin/date', '+%Y%m%dT%H%M%S.%N%z'] as const
const DATE_SHAPE = /^\d{8}T\d{6}\.\d{9}[+-]\d{4}$/

// A stamped name ends in `-\d{8}T\d{6}\.\d{9}[+-]\d{2}`: what tabname.py builds
// and what a launcher tab carries.
const STAMPED = /-\d{8}T\d{6}\.\d{9}[+-]\d{2}$/

// Every process call is bounded; a child outlasting its wait is killed and the
// call rejects.
export const DATE_TIMEOUT_MS = 5_000
export const HC_TIMEOUT_MS = 5_000
export const LS_TIMEOUT_MS = 5_000
export const RENAME_TIMEOUT_MS = 5_000

export const TERMINAL_ENV = 'HC_TERMINAL_ID'
export const TAB_LABEL = 'herdr.tab'
export const SESSION_LABEL = 'session'

// The classic.SessionStart sources a session is named on; clear and compact
// leave the name the session already has.
const NAMED_SOURCES: ReadonlySet<string> = new Set(['startup', 'resume', 'fork'])

export function namedSource(source: string): boolean {
  return NAMED_SOURCES.has(source)
}

export function isStamped(name: string): boolean {
  return STAMPED.test(name)
}

// What the hook does with the tab's name: keep it as the session title, or
// build `<base>-<stamp>` and rename the tab to it.
export type Action =
  | { kind: 'keep'; name: string }
  | { kind: 'rename'; base: string }

export function decide(source: string, tabName: string | undefined): Action | undefined {
  if (!namedSource(source) || tabName === undefined || tabName === '') return undefined
  return isStamped(tabName) ? { kind: 'keep', name: tabName } : { kind: 'rename', base: tabName }
}

// `date` output on the D61 shape, its offset cut to the hour; undefined when
// the output is anything else (a BSD date without %N, an error line).
export function parseDate(stdout: string): string | undefined {
  const text = stdout.trim()
  return DATE_SHAPE.test(text) ? text.slice(0, -2) : undefined
}

// What a logged reason may carry of engine or OS text: its first 120 characters.
export function excerpt(text: string): string {
  return text.trim().slice(0, 120)
}

const isBag = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

// The terminal's tab id, from `hc get <terminal> --json`'s `labels`. Throws on
// anything else: the caller logs it and the session goes on unnamed.
export function tabIdFromHcGet(stdout: string, terminal: string): string {
  let reply: unknown
  try {
    reply = JSON.parse(stdout)
  } catch {
    throw new Error(`hc get ${terminal} gave no JSON: ${excerpt(stdout)}`)
  }
  const id = isBag(reply) && isBag(reply.labels) ? reply.labels[TAB_LABEL] : undefined
  if (typeof id !== 'string' || id === '') {
    throw new Error(`hc get ${terminal} gave no ${TAB_LABEL} label: ${excerpt(stdout)}`)
  }
  return id
}

// The name of the tab `tabId` in `herdr-app ls` output; '' when the tab has
// none (an unnamed tab shows as its number). Throws when the listing is not
// the spaces shape or the tab is missing.
export function tabNameFromListing(stdout: string, tabId: string): string {
  let reply: unknown
  try {
    reply = JSON.parse(stdout)
  } catch {
    throw new Error(`herdr-app ls gave no JSON: ${excerpt(stdout)}`)
  }
  const spaces = isBag(reply) ? reply.spaces : undefined
  if (!Array.isArray(spaces)) {
    throw new Error(`herdr-app ls gave no spaces list: ${excerpt(stdout)}`)
  }
  for (const space of spaces) {
    for (const tab of isBag(space) && Array.isArray(space.tabs) ? space.tabs : []) {
      if (isBag(tab) && tab.id === tabId) return typeof tab.name === 'string' ? tab.name : ''
    }
  }
  throw new Error(`no tab ${tabId} in herdr-app ls`)
}
