import type { Engine, Register } from 'claude-code'

// A retro ends with its run-skill lines: one or more trailing lines, each exactly `/run-skill-generator <unit>: <what>`
// in backticks. Only that trailing block counts, so a quoted example or a relayed rule mid-text never starts a run, and
// a line still holding a <placeholder> is skipped.
const LINE = /^`\/run-skill-generator\s+([^`\n<>]+?:[^`\n<>]+?)`$/
const LOG = '.local/state/run-skill-auto/log.jsonl'

function lines(text: string | undefined): string[] {
  const rows = (text ?? "").split("\n").map(r => r.trim()).filter(r => r !== "")
  const found: string[] = []
  for (let i = rows.length - 1; i >= 0; i--) {
    const m = LINE.exec(rows[i])
    if (m === null) break
    found.unshift(m[1].trim().replace(/\s+/g, " "))
  }
  return found
}

const key = (args: string) => `ran:${args.toLowerCase()}`

export const register: Register = on => {
  // A run that started but did not finish (session ended, build broke) is still recorded: the mod cannot see a skill
  // run's end. /run-skill-forget <unit>: <what> clears that record, and the next reply ending with the line reruns it.
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'run-skill-forget',
      description: "Clear run-skill-auto's record of a /run-skill-generator line so it can run again",
      argumentHint: '<unit>: <what to drive>',
    })
    return next(e)
  })
  on('command.run', { command: 'run-skill-forget' }, async ($, e) => {
    const args = e.args.trim().replace(/\s+/g, ' ')
    if (args === '') return { text: 'run-skill-forget: give the text after /run-skill-generator (<unit>: <what>).' }
    const had = (await $.store.get(key(args))) != null
    await $.store.delete(key(args))
    return { text: had ? `run-skill-auto: forgot "${args}"; a reply ending with it runs it again.` : `run-skill-auto: no record of "${args}".` }
  })

  // The session's own reply, main loop only. runAll is not awaited: command.run queues until the session is idle
  // and rejects inside a hook the turn waits on.
  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    if (e.agentId === undefined) void runAll($, lines(done.text))
    return done
  })

  // In brief mode the reply goes through these tools, so their text is read too.
  on('tool.call', { tool: 'SendMessage' }, async ($, e, next) => {
    const ran = await next(e)
    if (e.agentId === undefined) void runAll($, lines(String((e as { message?: unknown }).message ?? '')))
    return ran
  })
  on('tool.call', { tool: 'SendUserMessage' }, async ($, e, next) => {
    const ran = await next(e)
    if (e.agentId === undefined) void runAll($, lines(String((e as { message?: unknown }).message ?? '')))
    return ran
  })
}

// Starts each line once, across sessions and reloads: the store key is claimed before the run.
async function runAll($: Engine, found: string[]) {
  for (const args of found) {
    if ((await $.store.get(key(args))) != null) continue
    await $.store.set(key(args), { at: new Date().toISOString(), state: 'queued' })
    let state = 'started'
    let detail = ''
    try {
      await $.command.run({ command: 'run-skill-generator', args })
    } catch (err) {
      state = 'refused'
      detail = String(err)
    }
    // A refused run never started, so its record is cleared and a later line retries it.
    if (state === 'refused') await $.store.delete(key(args))
    else await $.store.set(key(args), { at: new Date().toISOString(), state, detail })
    try {
      const home = (await $.env.get("HOME")) ?? ""
      const path = `${home}/${LOG}`
      const old = (await $.fs.exists(path)) ? String(await $.fs.read(path)) : ""
      const row = JSON.stringify({ at: new Date().toISOString(), state, args, detail })
      await $.fs.write(path, `${old}${row}\n`)
    } catch {
      // The store record above is the source of truth; the file is a convenience for the coordinator.
    }
    $.ui.toast(`run-skill-auto: ${state} /run-skill-generator ${args}`)
  }
}
