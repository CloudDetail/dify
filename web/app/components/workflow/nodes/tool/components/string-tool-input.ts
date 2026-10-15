import type { ToolVarInputs } from '../types'
import { VarType } from '../types'

export function stringToolInputValue(input?: ToolVarInputs[string]): string {
  const value = input?.value
  // Tool execution accepts selectors, while the text editor needs a template.
  if (input?.type === VarType.variable && Array.isArray(value))
    return value.length ? `{{#${value.join('.')}#}}` : ''

  if (typeof value === 'string')
    return value
  if (typeof value === 'number' || typeof value === 'boolean')
    return String(value)
  return ''
}

export function stringToolInput(value: string): ToolVarInputs[string] {
  return { type: VarType.mixed, value }
}
