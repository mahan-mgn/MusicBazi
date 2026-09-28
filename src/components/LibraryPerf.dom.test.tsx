// @vitest-environment jsdom
// Library perf regression test (English comments kept on purpose).
//
// Before the fix, every keystroke/tab in the Library was a 120-413ms long
// task: each parent rerender rebuilt all rows (no memo, fresh queue array and
// closures every render), and a global `playing` subscription made every
// play/pause rerender every row. Pillars asserted here (by RENDER CALL COUNTS,
// not timing - timing is flaky on CI):
//   1) LibraryRow / TrackTile are memo components
//   2) a parent rerender with stable props triggers ZERO row work
//   3) play/pause flips only the involved row (1/3 of rows), not all
// Row work is counted via useI18n calls: every rendered row body (plus its
// RowMenu) calls it exactly once, and memoized rows that short-circuit call
// nothing.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LibraryItem } from '../lib/types'
import { usePlayer, type PlayItem } from '../store/player'
import { LibraryRow, toPlayItem } from './LibraryRow'
import { TrackTile } from './Shelf'

let i18nCalls = 0
vi.mock('../lib/i18n', async (orig) => {
  const mod = await (orig as () => Promise<Record<string, unknown>>)(
  ) as { useI18n: () => unknown } & Record<string, unknown>
  const real = mod.useI18n
  return {
    ...mod,
    useI18n: () => {
      i18nCalls++
      return real()
    },
  }
})

const item = (id: string): LibraryItem => ({
  jobId: id,
  track: {
    id,
    title: `T-${id}`,
    artist: 'A',
    durationMs: 200000,
    artworkUrl: null,
    source: 'deezer',
    sourceUrl: `https://deezer.com/track/${id}`,
    previewUrl: null,
  } as LibraryItem['track'],
  quality: '320',
  format: 'mp3',
  bytes: 1000,
  fileUrl: `/api/files/${id}.mp3`,
  streamUrl: `/api/stream/${id}`,
  createdAt: 1,
})

let host: HTMLDivElement
let root: Root

const stable = {
  onRemove: () => {},
  onToggleSelect: () => {},
  selected: false,
  selectable: false,
}

function renderList(items: LibraryItem[], queue: PlayItem[]) {
  act(() => {
    root.render(
      <>
        {items.map((x, i) => (
          <LibraryRow
            key={x.jobId}
            item={x}
            queue={queue}
            index={i}
            number={i + 1}
            {...stable}
          />
        ))}
      </>,
    )
  })
}

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  i18nCalls = 0
  usePlayer.setState({ queue: [], index: 0, playing: false })
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

describe('library row memoization', () => {
  it('LibraryRow and TrackTile are memo components', () => {
    const MEMO = Symbol.for('react.memo')
    expect((LibraryRow as unknown as { $$typeof: symbol }).$$typeof).toBe(MEMO)
    expect((TrackTile as unknown as { $$typeof: symbol }).$$typeof).toBe(MEMO)
  })

  it('parent rerender with stable props does zero row work', () => {
    const items = [item('a'), item('b'), item('c')]
    const queue = items.map(toPlayItem)
    renderList(items, queue)
    expect(i18nCalls).toBeGreaterThan(0) // all rows mounted
    i18nCalls = 0
    // identical props/identities => every memo short-circuits (the old code
    // rebuilt all rows here; this is the search-keystroke path)
    renderList(items, queue)
    expect(i18nCalls).toBe(0)
  })

  it('play/pause rerenders only the current row, not its siblings', () => {
    const items = [item('a'), item('b'), item('c')]
    const queue = items.map(toPlayItem)
    renderList(items, queue)
    const mount = i18nCalls
    expect(mount % 3).toBe(0) // uniform per-row cost
    i18nCalls = 0

    act(() => usePlayer.setState({ queue, index: 1, playing: true }))
    // only the involved row (and its parts) rerender; the old global `playing`
    // prop re-rendered EVERY row, i.e. exactly `mount` calls here
    expect(i18nCalls).toBeGreaterThan(0)
    expect(i18nCalls).toBeLessThan(mount)

    i18nCalls = 0
    act(() => usePlayer.setState({ playing: false }))
    expect(i18nCalls).toBeLessThan(mount)
  })
})
