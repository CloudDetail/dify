/** @jest-environment node */
import { VarType } from '../types'
import { stringToolInput, stringToolInputValue } from './string-tool-input'

describe('string tool parameters in the editor', () => {
  it('renders the deployed Pod selector as a template without changing the graph value', () => {
    const input = { type: VarType.variable, value: ['17430589567120', 'pod'] }
    expect(stringToolInputValue(input)).toBe('{{#17430589567120.pod#}}')
    expect(input.value).toEqual(['17430589567120', 'pod'])
  })

  it('preserves nested selectors and system variables', () => {
    expect(stringToolInputValue({ type: VarType.variable, value: ['node', 'result', 'pod'] })).toBe('{{#node.result.pod#}}')
    expect(stringToolInputValue({ type: VarType.variable, value: ['sys', 'user_id'] })).toBe('{{#sys.user_id#}}')
  })

  it.each([undefined, null, []])('renders an empty selector as empty text: %p', (value) => {
    expect(stringToolInputValue({ type: VarType.variable, value })).toBe('')
  })

  it.each(['plain text', '{{#node.pod#}}\nsuffix', 0, false])('keeps scalar content: %p', (value) => {
    expect(stringToolInputValue({ type: VarType.constant, value })).toBe(String(value))
  })

  it('saves edited selectors as mixed templates and preserves them on reopening', () => {
    const before = { type: VarType.variable, value: ['node', 'pod'] }
    const edited = stringToolInput(`${stringToolInputValue(before)} suffix`)
    expect(edited).toEqual({ type: VarType.mixed, value: '{{#node.pod#}} suffix' })
    expect(stringToolInputValue(edited)).toBe('{{#node.pod#}} suffix')
    expect(stringToolInput('')).toEqual({ type: VarType.mixed, value: '' })
  })
})
