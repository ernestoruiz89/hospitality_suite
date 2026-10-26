import { useRef } from "react"
import { execute } from "./api"
import { CommandKeys } from "./idempotentCommand"

export type SendCommand = <T>(action: string, data: Record<string, unknown>) => Promise<T>

/** Keep the key until the server confirms the exact command and payload. */
export function useIdempotentCommand(property: string): SendCommand {
  const keys = useRef(new CommandKeys())
  return async function send<T>(action: string, data: Record<string, unknown>): Promise<T> {
    return keys.current.run(property, action, data,
      (key) => execute<T>(property, action, data, key))
  }
}
