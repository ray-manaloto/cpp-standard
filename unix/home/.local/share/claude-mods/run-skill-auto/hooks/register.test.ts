import { expect, test } from 'claude-code/testing'

function fakes(on: any) {
  const store = new Map<string, unknown>()
  const files = new Map<string, string>()
  on("store.get", (_: any, e: any) => ({ value: store.get(e.key) ?? null }))
  on("store.set", (_: any, e: any) => { store.set(e.key, e.value); return { value: undefined } })
  on("store.delete", (_: any, e: any) => { store.delete(e.key); return { value: undefined } })
  on("env.get", () => ({ value: "/home/test" }))
  on("fs.exists", (_: any, e: any) => ({ value: files.has(e.path) }))
  on("fs.read", (_: any, e: any) => ({ value: files.get(e.path) ?? "" }))
  on("fs.write", (_: any, e: any) => { files.set(e.path, e.text); return { value: undefined } })
  on("ui.toast", () => ({ value: undefined }))
  return files
}

async function send($: any, message: string) {
  await $.tool.call({ tool: 'SendUserMessage', message, status: 'normal' })
  for (let i = 0; i < 400; i++) await Promise.resolve()
}

test('a trailing run-skill line runs once, and only once', async ($, on) => {
  const ran: string[] = []
  const files = fakes(on)
  on('tool.call', { tool: 'SendUserMessage' }, () => ({ result: 'ok' }))
  on('command.run', (_, e) => {
    ran.push(`${e.command} ${e.args}`)
    return { text: '' }
  })

  await send($, 'Retro done.\nrun-skill candidates: x\n`/run-skill-generator cpp container: build, run, remove`')
  await send($, 'again\n`/run-skill-generator cpp container: build, run, remove`')

  expect(ran).toEqual(['run-skill-generator cpp container: build, run, remove'])
})

test('a quoted template or a mid-text line never runs', async ($, on) => {
  const ran: string[] = []
  const files = fakes(on)
  on('tool.call', { tool: 'SendUserMessage' }, () => ({ result: 'ok' }))
  on('command.run', (_, e) => {
    ran.push(e.args)
    return { text: '' }
  })

  await send($, 'Rule: end with `/run-skill-generator <unit>: <what to drive>`')
  await send($, '`/run-skill-generator <unit>: <what to drive>`')
  await send($, '`/run-skill-generator a: b`\nmore text after it')

  expect(ran).toEqual([])
})

test('/run-skill-forget clears a record so the line runs again', async ($, on) => {
  const ran: string[] = []
  fakes(on)
  on('tool.call', { tool: 'SendUserMessage' }, () => ({ result: 'ok' }))
  on('command.run', { command: 'run-skill-generator' }, (_, e) => {
    ran.push(e.args)
    return { text: '' }
  })

  const line = '`/run-skill-generator a: b`'
  await send($, line)
  await send($, line)
  const forgot = await $.command.run({ command: 'run-skill-forget', args: 'a: b' })
  await send($, line)

  expect(forgot.text).toContain('forgot')
  expect(ran).toEqual(['a: b', 'a: b'])
})
