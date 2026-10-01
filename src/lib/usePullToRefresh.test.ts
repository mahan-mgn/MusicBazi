// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { MAX_PULL, PULL_THRESHOLD } from './usePullToRefresh'

describe('usePullToRefresh logic', () => {
  it('threshold is positive and less than max pull', () => {
    expect(PULL_THRESHOLD).toBeGreaterThan(0)
    expect(PULL_THRESHOLD).toBeLessThan(MAX_PULL)
  })
})
