import { describe, expect, it } from 'vitest'
import { money, pct, shiftMonth } from './api'

describe('money', () => {
  it('formats positive cents', () => {
    expect(money(123456)).toBe('$1,234.56')
  })
  it('formats negative cents with leading minus', () => {
    expect(money(-8412)).toBe('-$84.12')
  })
  it('adds a plus sign when asked', () => {
    expect(money(500, { sign: true })).toBe('+$5.00')
  })
  it('handles null/undefined', () => {
    expect(money(null)).toBe('—')
    expect(money(undefined)).toBe('—')
  })
})

describe('pct', () => {
  it('rounds to whole percent', () => {
    expect(pct(0.316)).toBe('32%')
    expect(pct(null)).toBe('—')
  })
})

describe('shiftMonth', () => {
  it('moves within a year', () => {
    expect(shiftMonth('2026-07', 1)).toBe('2026-08')
    expect(shiftMonth('2026-07', -1)).toBe('2026-06')
  })
  it('crosses year boundaries', () => {
    expect(shiftMonth('2026-01', -1)).toBe('2025-12')
    expect(shiftMonth('2025-12', 1)).toBe('2026-01')
    expect(shiftMonth('2026-03', -15)).toBe('2024-12')
  })
})
