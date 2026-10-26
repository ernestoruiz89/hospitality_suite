import assert from "node:assert/strict"
import test from "node:test"

import { createLatestRequest } from "../src/latestRequest.ts"

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test("an older property response cannot replace the current journal page", async () => {
  const requests = createLatestRequest()
  const first = deferred<string>()
  const second = deferred<string>()
  const pages: string[] = []
  const errors: unknown[] = []
  let firstSignal: AbortSignal | undefined
  const oldLoad = requests.run((signal) => {
    firstSignal = signal
    return first.promise
  }, (page) => pages.push(page), (issue) => errors.push(issue))
  const newLoad = requests.run(() => second.promise,
    (page) => pages.push(page), (issue) => errors.push(issue))

  assert.equal(firstSignal?.aborted, true)
  second.resolve("new hotel")
  await newLoad
  first.resolve("old hotel") // Simulates a response that ignores AbortSignal.
  await oldLoad
  assert.deepEqual(pages, ["new hotel"])
  assert.deepEqual(errors, [])
})

test("aborted searches do not replace a newer result with an error", async () => {
  const requests = createLatestRequest()
  const first = deferred<string>()
  const second = deferred<string>()
  const pages: string[] = []
  const errors: unknown[] = []
  const oldLoad = requests.run(() => first.promise,
    (page) => pages.push(page), (issue) => errors.push(issue))
  const newLoad = requests.run(() => second.promise,
    (page) => pages.push(page), (issue) => errors.push(issue))
  first.reject(new Error("old failure"))
  second.resolve("latest page")
  await Promise.all([oldLoad, newLoad])
  assert.deepEqual(pages, ["latest page"])
  assert.deepEqual(errors, [])
})

test("unmounting suppresses even a late successful response", async () => {
  const requests = createLatestRequest()
  const pending = deferred<string>()
  const pages: string[] = []
  const load = requests.run(() => pending.promise,
    (page) => pages.push(page), () => assert.fail("unexpected error"))
  requests.abort()
  pending.resolve("old page")
  await load
  assert.deepEqual(pages, [])
})
