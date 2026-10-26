import assert from "node:assert/strict"
import { test } from "node:test"
import { CommandKeys } from "../src/idempotentCommand.ts"
import { execute } from "../src/api.ts"

test("reuses a key after a lost response and releases it after confirmation", async () => {
  let sequence = 0
  const commands = new CommandKeys(() => `request-${++sequence}`)
  const sent: string[] = []
  const transport = async (key: string) => {
    sent.push(key)
    if (sent.length === 1) throw new Error("response lost after commit")
    return { payment: "PAY-1" }
  }
  const payload = { amount: "25.00", reference: "REF-1" }

  await assert.rejects(commands.run("HOTEL-1", "pms_cash_movement", payload, transport))
  assert.deepEqual(await commands.run("HOTEL-1", "pms_cash_movement", payload, transport),
    { payment: "PAY-1" })
  assert.deepEqual(sent, ["request-1", "request-1"])

  await commands.run("HOTEL-1", "pms_cash_movement", payload, transport)
  assert.equal(sent[2], "request-2")
})

test("keeps distinct keys for different properties, actions and payloads", async () => {
  let sequence = 0
  const commands = new CommandKeys(() => `request-${++sequence}`)
  const seen: string[] = []
  const fail = async (key: string): Promise<void> => {
    seen.push(key)
    throw new Error("response lost")
  }
  for (const [property, action, amount] of [
    ["HOTEL-1", "pms_receivable", "10.00"],
    ["HOTEL-2", "pms_receivable", "10.00"],
    ["HOTEL-1", "pms_apply_advance", "10.00"],
    ["HOTEL-1", "pms_receivable", "20.00"],
  ]) {
    await assert.rejects(commands.run(property, action, { amount }, fail))
  }
  assert.deepEqual(seen, ["request-1", "request-2", "request-3", "request-4"])
  await assert.rejects(commands.run("HOTEL-1", "pms_receivable", { amount: "10.00" }, fail))
  assert.equal(seen[4], "request-1")
})

test("retries the same HTTP command after the server commits but its response is lost", async () => {
  let sequence = 0
  const commands = new CommandKeys(() => `request-${++sequence}`)
  const originalFetch = globalThis.fetch
  const originalWindow = (globalThis as typeof globalThis & { window?: unknown }).window
  const requests: Record<string, unknown>[] = []
  const committed = new Map<string, { payment: string }>()
  let journalCount = 0
  ;(globalThis as typeof globalThis & { window: unknown }).window = { csrf_token: "test-csrf" }
  globalThis.fetch = async (_input, init) => {
    assert.equal(init?.method, "POST")
    assert.equal((init?.headers as Record<string, string>)["X-Frappe-CSRF-Token"], "test-csrf")
    const request = JSON.parse(String(init?.body)) as Record<string, unknown>
    requests.push(request)
    const key = String(request.request_key)
    if (!committed.has(key)) committed.set(key, { payment: `PAY-${++journalCount}` })
    if (requests.length === 1) throw new Error("connection closed after commit")
    return new Response(JSON.stringify({ message: committed.get(key) }), {
      status: 200, headers: { "Content-Type": "application/json" },
    })
  }
  try {
    const data = { amount: "25.00", reference: "REF-1" }
    const send = () => commands.run("HOTEL-1", "pms_cash_movement", data,
      (key) => execute<{ payment: string }>("HOTEL-1", "pms_cash_movement", data, key))
    await assert.rejects(send(), /connection closed after commit/)
    assert.deepEqual(await send(), { payment: "PAY-1" })
    assert.equal(journalCount, 1)
    assert.equal(requests.length, 2)
    assert.deepEqual(requests[0], requests[1])
  } finally {
    globalThis.fetch = originalFetch
    if (originalWindow === undefined) delete (globalThis as typeof globalThis & { window?: unknown }).window
    else (globalThis as typeof globalThis & { window: unknown }).window = originalWindow
  }
})

test("coalesces simultaneous identical sends and keeps their key if delivery fails", async () => {
  let sequence = 0
  const commands = new CommandKeys(() => `request-${++sequence}`)
  const sent: string[] = []
  let rejectFirst!: (reason: Error) => void
  const first = (_key: string) => new Promise<string>((_resolve, reject) => {
    rejectFirst = reject
  })
  const data = { amount: "25.00" }
  const a = commands.run("HOTEL-1", "pms_cash_movement", data, (key) => {
    sent.push(key)
    return first(key)
  })
  const b = commands.run("HOTEL-1", "pms_cash_movement", data, (key) => {
    sent.push(key)
    return first(key)
  })
  await Promise.resolve()
  assert.deepEqual(sent, ["request-1"])
  rejectFirst(new Error("response lost"))
  await assert.rejects(a, /response lost/)
  await assert.rejects(b, /response lost/)
  assert.equal(await commands.run("HOTEL-1", "pms_cash_movement", data, async (key) => {
    sent.push(key)
    return "PAY-1"
  }), "PAY-1")
  assert.deepEqual(sent, ["request-1", "request-1"])
})
