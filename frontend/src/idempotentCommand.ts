export class CommandKeys {
  #pending = new Map<string, string>()
  #inFlight = new Map<string, Promise<unknown>>()
  #newKey: () => string

  constructor(newKey: () => string = () => crypto.randomUUID()) {
    this.#newKey = newKey
  }

  async run<T>(property: string, action: string, data: Record<string, unknown>,
    send: (key: string) => Promise<T>): Promise<T> {
    const signature = JSON.stringify([property, action, data])
    const active = this.#inFlight.get(signature) as Promise<T> | undefined
    if (active) return active
    let key = this.#pending.get(signature)
    if (!key) {
      key = this.#newKey()
      this.#pending.set(signature, key)
    }
    const request = Promise.resolve().then(() => send(key)).then((result) => {
      this.#pending.delete(signature)
      return result
    }).finally(() => this.#inFlight.delete(signature))
    this.#inFlight.set(signature, request)
    return request
  }
}
