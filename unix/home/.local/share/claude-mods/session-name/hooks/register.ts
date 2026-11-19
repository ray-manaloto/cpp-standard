import type { EngineInterface, Register } from 'claude-code'
import {
  DATE_ARGV, DATE_TIMEOUT_MS, HC_TIMEOUT_MS, LS_TIMEOUT_MS, RENAME_TIMEOUT_MS, SESSION_LABEL,
  decide, excerpt, namedSource, parseDate, tabIdFromHcGet, tabNameFromListing,
} from './name.ts'

// #303: a Claude session takes its herdr tab's name, so one `<base>-<stamp>`
// string names both and resumes by it. On classic.SessionStart for startup,
// resume and fork, the tab is found through the terminal (`HC_TERMINAL_ID` ->
// `hc get` -> the `herdr.tab` label -> `herdr-app ls`): a stamped tab name is
// kept as the session title, an unstamped one gains a D61 stamp from /bin/date
// and the tab is renamed to it, and the session id is stored as the terminal's
// `session` label for a later resume by id. On clear and compact nothing runs:
// the session keeps the name it already has.
//
// Every process call is bounded (`timeoutMs`); any failure is logged to the
// debug log and the session goes on unnamed. This file never throws. Pure
// helpers live in ./name.ts; every `$` call stays in this file (a hooks module
// may not pass `$` to a function it imports).

// The session title the session starts under, or undefined when it goes on
// unnamed: no terminal, an unreadable tab, a failed stamp or rename. A failed
// label is logged and the title kept, so the tab and session never disagree.
async function sessionTitleFor(
  $: EngineInterface,
  e: { source: string; session_id?: string },
): Promise<string | undefined> {
  try {
    const terminal = await $.env.get('HC_TERMINAL_ID')
    if (terminal === undefined || terminal === '') return undefined
    const got = await $.process.run(['hc', 'get', terminal, '--json'], { timeoutMs: HC_TIMEOUT_MS })
    if (got.exitCode !== 0) {
      throw new Error(`hc get ${terminal} exited ${got.exitCode}: ${excerpt(got.stderr)}`)
    }
    const tabId = tabIdFromHcGet(got.stdout, terminal)
    const listing = await $.process.run(['herdr-app', 'ls'], { timeoutMs: LS_TIMEOUT_MS })
    if (listing.exitCode !== 0) {
      throw new Error(`herdr-app ls exited ${listing.exitCode}: ${excerpt(listing.stderr)}`)
    }
    const tabName = tabNameFromListing(listing.stdout, tabId)
    const action = decide(e.source, tabName)
    if (action === undefined) throw new Error(`tab ${tabId} has no name to keep or extend`)
    let title: string
    if (action.kind === 'keep') {
      title = action.name
    } else {
      const date = await $.process.run([...DATE_ARGV], { timeoutMs: DATE_TIMEOUT_MS })
      if (date.exitCode !== 0) throw new Error(`date exited ${date.exitCode}: ${excerpt(date.stderr)}`)
      const stamp = parseDate(date.stdout)
      if (stamp === undefined) throw new Error(`date output unexpected: ${excerpt(date.stdout)}`)
      title = `${action.base}-${stamp}`
      const rename = await $.process.run(
        ['herdr-app', 'do', 'tab.rename', '--id', tabId, '--name', title],
        { timeoutMs: RENAME_TIMEOUT_MS },
      )
      if (rename.exitCode !== 0) {
        throw new Error(`tab.rename to ${title} exited ${rename.exitCode}: ${excerpt(rename.stderr)}`)
      }
    }
    const sid = e.session_id ?? (await $.session.id())
    const label = await $.process.run(['hc', 'label', terminal, `${SESSION_LABEL}=${sid}`], {
      timeoutMs: HC_TIMEOUT_MS,
    })
    if (label.exitCode !== 0) {
      // The tab may already carry the new name, so the session takes it too; only the resume-by-id label is lost.
      $.ui.log(`session-name: hc label session exited ${label.exitCode}: ${excerpt(label.stderr)}`, { to: 'debug' })
    }
    return title
  } catch (error) {
    try {
      $.ui.log(`session-name: ${error instanceof Error ? error.message : String(error)}`, { to: 'debug' })
    } catch {
      // Nothing more to tell: the session goes on unnamed.
    }
    return undefined
  }
}

export const register: Register = on => {
  // next(e) goes first, so the rest of the chain is never held up by the
  // lookups; the title rides on its result.
  on('classic.SessionStart', async ($, e, next) => {
    const result = await next(e)
    if (!namedSource(e.source)) return result
    const sessionTitle = await sessionTitleFor($, e)
    return sessionTitle === undefined ? result : { ...result, sessionTitle }
  })
}
