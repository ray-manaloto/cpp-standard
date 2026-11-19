import { describe, expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

import { decide, isStamped, namedSource, parseDate, tabIdFromHcGet, tabNameFromListing, TERMINAL_ENV } from './name'

// The fixed world: one space, one tab, one terminal. The tab carries the
// unstamped base (`w1`) unless the case names it; /bin/date says DATE_OUT.
const SID = 'sess-1'
const TERMINAL = 't1'
const TAB = 'tb1'
const BASE = 'w1'
const DATE_OUT = '20261119T120850.005365000-0600\n'
const STAMP = '20261119T120850.005365000-06'
const NAMED = `${BASE}-${STAMP}`

type World = {
  calls: string[][]
  logs: string[]
  renamed: () => string | undefined
  labeled: () => string | undefined
}

// Answers every process call the mod makes; `fail` breaks the named step, and
// `tabName` renames the tab in the listing (default: the unstamped base).
const world = (
  on: On,
  opts: { env?: Record<string, string>; tabName?: string; fail?: 'hcGet' | 'ls' | 'date' | 'rename' | 'label' } = {},
): World => {
  const env = opts.env ?? { [TERMINAL_ENV]: TERMINAL }
  on('env.get', (_, e) => ({ value: env[e.name] }))
  on('session.id', () => ({ value: SID }))
  const logs: string[] = []
  on('ui.log', (_, e) => {
    logs.push(e.text)
    return { value: undefined }
  })
  // No settings hook runs beneath: the classic chain ends here.
  on('classic.SessionStart', () => ({}))
  const calls: string[][] = []
  on('process.run', (_, e) => {
    calls.push([...e.argv])
    const [cmd, sub] = e.argv
    const ok = (stdout: string) => ({
      exitCode: 0,
      stdout,
      stderr: '',
      isStdoutTruncated: false,
      isStderrTruncated: false,
    })
    const failed = (stderr: string) => ({
      exitCode: 1,
      stdout: '',
      stderr,
      isStdoutTruncated: false,
      isStderrTruncated: false,
    })
    if (cmd === 'hc' && sub === 'get') {
      return { value: opts.fail === 'hcGet' ? failed('no such terminal') : ok(JSON.stringify({ labels: { 'herdr.tab': TAB } })) }
    }
    if (cmd === 'herdr-app' && sub === 'ls') {
      if (opts.fail === 'ls') return { value: failed('herdr is gone') }
      const name = opts.tabName === undefined ? BASE : opts.tabName
      return { value: ok(JSON.stringify({ spaces: [{ id: 'sp1', tabs: [{ id: TAB, name }] }] })) }
    }
    if (cmd === '/bin/date') {
      return { value: opts.fail === 'date' ? failed('date: bad format') : ok(DATE_OUT) }
    }
    if (cmd === 'herdr-app' && sub === 'do') {
      return { value: opts.fail === 'rename' ? failed('no such tab') : ok('{"ok":true}') }
    }
    if (cmd === 'hc' && sub === 'label') {
      return { value: opts.fail === 'label' ? failed('no such terminal') : ok('') }
    }
    return { value: failed(`unexpected call: ${e.argv.join(' ')}`) }
  })
  return {
    calls,
    logs,
    renamed: () => {
      const call = calls.find(c => c[0] === 'herdr-app' && c[1] === 'do' && c[2] === 'tab.rename')
      return call === undefined ? undefined : call[call.indexOf('--name') + 1]
    },
    labeled: () => {
      const call = calls.find(c => c[0] === 'hc' && c[1] === 'label')
      return call === undefined ? undefined : call[3]
    },
  }
}

// Drives the session through the engine as the classic hook dispatch does.
const start = ($: Engine, source: 'startup' | 'resume' | 'fork' | 'clear' | 'compact') =>
  $.classic.SessionStart({ source, session_id: SID })

test('startup with an unstamped tab renames the tab and names and labels the session', async ($, on) => {
  const w = world(on)
  const r = await start($, 'startup')
  expect(r.sessionTitle).toBe(NAMED)
  expect(w.renamed()).toBe(NAMED)
  expect(w.labeled()).toBe(`session=${SID}`)
  expect(w.logs).toEqual([])
})

test('startup with a stamped tab keeps it: no rename, no date, sessionTitle = tab name', async ($, on) => {
  const w = world(on, { tabName: NAMED })
  const r = await start($, 'startup')
  expect(r.sessionTitle).toBe(NAMED)
  expect(w.renamed()).toBeUndefined()
  expect(w.calls.some(c => c[0] === '/bin/date')).toBe(false)
  expect(w.labeled()).toBe(`session=${SID}`)
})

for (const source of ['resume', 'fork'] as const) {
  test(`${source} renames an unstamped tab to a stamped name again`, async ($, on) => {
    const w = world(on)
    const r = await start($, source)
    expect(r.sessionTitle).toBe(NAMED)
    expect(w.renamed()).toBe(NAMED)
    expect(w.labeled()).toBe(`session=${SID}`)
  })
}

test('resume with a stamped tab keeps the tab name', async ($, on) => {
  const w = world(on, { tabName: NAMED })
  const r = await start($, 'resume')
  expect(r.sessionTitle).toBe(NAMED)
  expect(w.renamed()).toBeUndefined()
  expect(w.labeled()).toBe(`session=${SID}`)
})

test('/clear and compact run nothing: no sessionTitle, no process calls', async ($, on) => {
  const w = world(on)
  for (const source of ['clear', 'compact'] as const) {
    const r = await start($, source)
    expect(r.sessionTitle).toBeUndefined()
    expect(w.calls).toEqual([])
  }
})

test('no HC_TERMINAL_ID passes through: unnamed, no process calls', async ($, on) => {
  const w = world(on, { env: {} })
  const r = await start($, 'startup')
  expect(r.sessionTitle).toBeUndefined()
  expect(w.calls).toEqual([])
  expect(w.logs).toEqual([])
})

test('a failed hc get leaves the session unnamed, logged once', async ($, on) => {
  const w = world(on, { fail: 'hcGet' })
  const r = await start($, 'startup')
  expect(r.sessionTitle).toBeUndefined()
  expect(w.renamed()).toBeUndefined()
  expect(w.labeled()).toBeUndefined()
  expect(w.logs.length).toBe(1)
})

test('a tab with no name leaves the session unnamed', async ($, on) => {
  const w = world(on, { tabName: '' })
  const r = await start($, 'startup')
  expect(r.sessionTitle).toBeUndefined()
  expect(w.renamed()).toBeUndefined()
  expect(w.logs.length).toBe(1)
})

test('a failed date renames nothing and leaves the session unnamed', async ($, on) => {
  const w = world(on, { fail: 'date' })
  const r = await start($, 'startup')
  expect(r.sessionTitle).toBeUndefined()
  expect(w.renamed()).toBeUndefined()
  expect(w.logs.length).toBe(1)
})

test('a failed rename leaves the session unnamed and unlabeled', async ($, on) => {
  const w = world(on, { fail: 'rename' })
  const r = await start($, 'startup')
  expect(r.sessionTitle).toBeUndefined()
  expect(w.renamed()).toBe(NAMED)
  expect(w.labeled()).toBeUndefined()
  expect(w.logs.length).toBe(1)
})

test('a failed label keeps the title, so tab and session still agree, logged once', async ($, on) => {
  const w = world(on, { fail: 'label' })
  const r = await start($, 'startup')
  expect(r.sessionTitle).toBe(NAMED)
  expect(w.renamed()).toBe(NAMED)
  expect(w.logs.length).toBe(1)
})

describe('pure helpers', () => {
  test('parseDate validates the D61 shape and cuts the offset to the hour', () => {
    expect(parseDate(DATE_OUT)).toBe(STAMP)
    expect(parseDate('20261119T120850.005365000+0530\n')).toBe('20261119T120850.005365000+05')
    expect(parseDate('no')).toBeUndefined()
    expect(parseDate('20261119T120850.005365000-0600 extra')).toBeUndefined()
  })

  test('isStamped takes the cut offset at the end only', () => {
    expect(isStamped(NAMED)).toBe(true)
    expect(isStamped('w1-20261119T120850.005365000-0600')).toBe(false)
    expect(isStamped('w1-20261119T120850')).toBe(false)
    expect(isStamped('w1')).toBe(false)
  })

  test('namedSource covers startup, resume and fork, not clear and compact', () => {
    expect(namedSource('startup')).toBe(true)
    expect(namedSource('resume')).toBe(true)
    expect(namedSource('fork')).toBe(true)
    expect(namedSource('clear')).toBe(false)
    expect(namedSource('compact')).toBe(false)
  })

  test('decide keeps a stamped tab, renames an unstamped one, and skips the unnamed sources', () => {
    expect(decide('startup', BASE)).toEqual({ kind: 'rename', base: BASE })
    expect(decide('resume', BASE)).toEqual({ kind: 'rename', base: BASE })
    expect(decide('fork', BASE)).toEqual({ kind: 'rename', base: BASE })
    expect(decide('startup', NAMED)).toEqual({ kind: 'keep', name: NAMED })
    expect(decide('clear', BASE)).toBeUndefined()
    expect(decide('compact', NAMED)).toBeUndefined()
    expect(decide('startup', '')).toBeUndefined()
    expect(decide('startup', undefined)).toBeUndefined()
  })

  test('tabIdFromHcGet reads the herdr.tab label and rejects anything else', () => {
    expect(tabIdFromHcGet(JSON.stringify({ labels: { 'herdr.tab': TAB } }), TERMINAL)).toBe(TAB)
    expect(() => tabIdFromHcGet('not json', TERMINAL)).toThrow()
    expect(() => tabIdFromHcGet('{"labels":{}}', TERMINAL)).toThrow()
    expect(() => tabIdFromHcGet('{"labels":{"herdr.tab":""}}', TERMINAL)).toThrow()
  })

  test('tabNameFromListing finds the tab and reports an unnamed tab as empty', () => {
    expect(tabNameFromListing(JSON.stringify({ spaces: [{ id: 'sp1', tabs: [{ id: TAB, name: BASE }] }] }), TAB)).toBe(BASE)
    expect(tabNameFromListing(JSON.stringify({ spaces: [{ id: 'sp1', tabs: [{ id: TAB }] }] }), TAB)).toBe('')
    expect(() => tabNameFromListing(JSON.stringify({ spaces: [] }), TAB)).toThrow()
    expect(() => tabNameFromListing('not json', TAB)).toThrow()
  })
})
