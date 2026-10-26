/** Keep responses from older searches from replacing the current view. */
export function createLatestRequest() {
  let active: AbortController | null = null

  return {
    async run<T>(request: (signal: AbortSignal) => Promise<T>,
      onResult: (result: T) => void, onError: (issue: unknown) => void) {
      active?.abort()
      const controller = new AbortController()
      active = controller
      try {
        const result = await request(controller.signal)
        if (active === controller && !controller.signal.aborted) onResult(result)
      } catch (issue) {
        if (active === controller && !controller.signal.aborted) onError(issue)
      } finally {
        if (active === controller) active = null
      }
    },
    abort() {
      active?.abort()
      active = null
    },
  }
}
