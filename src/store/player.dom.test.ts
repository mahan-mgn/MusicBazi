// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextMuteState, usePlayer, type PlayItem } from './player'

window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
window.HTMLMediaElement.prototype.pause = vi.fn()

/**
 * دلیلِ وجودِ این تست: «بی‌صدا» دو چیزِ متفاوت بود که به هم چسبیده بودند —
 * پرچمِ `muted`ِ المنتِ صوتی، و بلندیِ صفر.
 *
 * کشیدنِ نوارِ بلندی تا ته، `muted` را در state روشن می‌کرد ولی هیچ‌وقت
 * `engine.setMuted` را صدا نمی‌زد. بعد دکمه‌ی بی‌صدا پرچمی را «برمی‌داشت» که
 * اصلاً بالا نرفته بود و بلندی صفر می‌ماند: آیکون می‌گفت صدا وصل است، کاربر
 * هیچ نمی‌شنید، و تنها راهِ نجات دستکاریِ دوباره‌ی خودِ نوار بود.
 */
describe('دکمه‌ی بی‌صدا', () => {
  it('برگشت از بی‌صدا وقتی بلندی صفر مانده، واقعاً صدا را برمی‌گرداند', () => {
    // نوار تا ته پایین کشیده شده: muted روشن، ولی بلندی هم صفر است
    expect(nextMuteState(0, true, 0.8)).toEqual({ muted: false, volume: 0.8 })
  })

  it('اگر بلندیِ قبلی هم صفر بود، به تهِ نوار برمی‌گردد نه به سکوت', () => {
    // وگرنه دکمه دوباره بی‌اثر می‌شد — همان بن‌بستِ اول
    expect(nextMuteState(0, true, 0)).toEqual({ muted: false, volume: 1 })
  })

  it('بی‌صدا کردن به بلندی دست نمی‌زند — نوار سرِ جایش می‌ماند', () => {
    expect(nextMuteState(0.6, false, 0.6)).toEqual({ muted: true, volume: 0.6 })
  })

  it('برگشت از بی‌صدا با بلندیِ سالم، همان بلندی را نگه می‌دارد', () => {
    expect(nextMuteState(0.6, true, 0.2)).toEqual({ muted: false, volume: 0.6 })
  })

  it('رفت‌وبرگشت همیشه به وضعیتِ شنیدنی ختم می‌شود', () => {
    for (const volume of [0, 0.01, 0.5, 1]) {
      const off = nextMuteState(volume, false, volume || 1)
      const on = nextMuteState(off.volume, off.muted, volume || 1)
      expect(on.muted).toBe(false)
      expect(on.volume).toBeGreaterThan(0)
    }
  })
})

const makePlayItem = (id: string): PlayItem => ({
  id,
  track: {
    id: `track-${id}`,
    title: `Title ${id}`,
    artist: 'Artist',
    durationMs: 180000,
    artworkUrl: null,
    source: 'spotify',
    sourceUrl: 'https://spotify.com',
    previewUrl: null,
  },
  streamUrl: `/stream/${id}`,
})

describe('playNext', () => {
  it('اگر صف خالی باشد، ترک جدید را به عنوان ترک اول شروع می‌کند', () => {
    usePlayer.setState({ queue: [], index: 0, playing: false })
    const t1 = makePlayItem('1')
    usePlayer.getState().playNext([t1])
    expect(usePlayer.getState().queue).toEqual([t1])
    expect(usePlayer.getState().index).toBe(0)
  })

  it('ترک جدید را بلافاصله بعد از ایندکس جاری درج می‌کند', () => {
    const t1 = makePlayItem('1')
    const t2 = makePlayItem('2')
    const t3 = makePlayItem('3')
    usePlayer.setState({ queue: [t1, t2, t3], index: 0, playing: true })
    const nextItem = makePlayItem('next')
    usePlayer.getState().playNext([nextItem])
    const q = usePlayer.getState().queue
    expect(q.map((x) => x.id)).toEqual(['1', 'next', '2', '3'])
    expect(usePlayer.getState().index).toBe(0)
  })

  it('چند ترک را با حفظ ترتیب بعد از ایندکس جاری قرار می‌دهد', () => {
    const t1 = makePlayItem('1')
    const t2 = makePlayItem('2')
    usePlayer.setState({ queue: [t1, t2], index: 1, playing: true })
    const next1 = makePlayItem('n1')
    const next2 = makePlayItem('n2')
    usePlayer.getState().playNext([next1, next2])
    const q = usePlayer.getState().queue
    expect(q.map((x) => x.id)).toEqual(['1', '2', 'n1', 'n2'])
    expect(usePlayer.getState().index).toBe(1)
  })
})

describe('replaceQueue', () => {
  it('replaces the queue while keeping the currently playing item active', () => {
    const current = makePlayItem('current')
    const stale = makePlayItem('stale')
    const replacementCurrent = { ...makePlayItem('current'), streamUrl: '/replacement/current' }
    const next = makePlayItem('next')
    usePlayer.setState({ queue: [current, stale], index: 0, playing: true })

    usePlayer.getState().replaceQueue([replacementCurrent, next], 0)

    expect(usePlayer.getState().queue.map((item) => item.id)).toEqual(['current', 'next'])
    expect(usePlayer.getState().queue[0]).toBe(current)
    expect(usePlayer.getState().index).toBe(0)
    expect(usePlayer.getState().playing).toBe(true)
  })
})

describe('shuffle and history navigation in usePlayer', () => {
  it('setShuffle controls shuffle mode directly', () => {
    usePlayer.setState({ shuffle: false })
    usePlayer.getState().setShuffle(true)
    expect(usePlayer.getState().shuffle).toBe(true)

    usePlayer.getState().setShuffle(false)
    expect(usePlayer.getState().shuffle).toBe(false)
  })

  it('prev() in shuffle mode navigates back to previously played track from history', () => {
    const items = [makePlayItem('0'), makePlayItem('1'), makePlayItem('2'), makePlayItem('3')]
    usePlayer.getState().play(items, 0)
    usePlayer.getState().setShuffle(true)
    expect(usePlayer.getState().index).toBe(0)

    // Simulate next() jumping to index 3
    vi.spyOn(Math, 'random').mockReturnValue(0.99) // will pick candidate near end
    usePlayer.getState().next()
    const secondIndex = usePlayer.getState().index
    expect(secondIndex).not.toBe(0)

    // Calling prev() at position 0 should go back to 0 (the track in historyStack)
    usePlayer.setState({ position: 0 })
    usePlayer.getState().prev()
    expect(usePlayer.getState().index).toBe(0)

    vi.restoreAllMocks()
  })

  it('setSleepTimer supports track_end mode', () => {
    usePlayer.getState().setSleepTimer('track_end')
    expect(usePlayer.getState().sleepAt).toBe('track_end')

    usePlayer.getState().setSleepTimer(null)
    expect(usePlayer.getState().sleepAt).toBeNull()
  })

  it('playNext و enqueue اقلامِ از قبل موجود در صف را اضافه نمی‌کنند (dedupe)', () => {
    const t1 = makePlayItem('1')
    const t2 = makePlayItem('2')
    usePlayer.setState({ queue: [t1, t2], index: 0, playing: true })

    // افزودن تکراری با playNext
    usePlayer.getState().playNext([t1, makePlayItem('3')])
    expect(usePlayer.getState().queue.map((x) => x.id)).toEqual(['1', '3', '2'])

    // افزودن تکراری با enqueue
    usePlayer.getState().enqueue([t1, t2, makePlayItem('4')])
    expect(usePlayer.getState().queue.map((x) => x.id)).toEqual(['1', '3', '2', '4'])
  })

  it('clearQueue فقط ترک در حال پخش را نگه می‌دارد و ایندکس را صفر می‌کند', () => {
    const t1 = makePlayItem('1')
    const t2 = makePlayItem('2')
    const t3 = makePlayItem('3')
    usePlayer.setState({ queue: [t1, t2, t3], index: 1, playing: true })

    usePlayer.getState().clearQueue(true)
    const { queue, index } = usePlayer.getState()
    expect(queue.length).toBe(1)
    expect(queue[0].id).toBe('2')
    expect(index).toBe(0)
  })

  it('drop با اندیس فقط ردیفِ مشخص‌شده را حذف می‌کند', () => {
    const t1 = makePlayItem('1')
    const t2 = makePlayItem('2')
    const t3 = makePlayItem('3')
    usePlayer.setState({ queue: [t1, t2, t3], index: 0, playing: true })

    usePlayer.getState().drop('2', 1)
    expect(usePlayer.getState().queue.map((x) => x.id)).toEqual(['1', '3'])
  })
})

describe('buffering state in usePlayer', () => {
  it('load sets buffering: true and playing: false until audio starts playing', () => {
    usePlayer.setState({ playing: false, buffering: false })
    const item = makePlayItem('buffering-test')
    usePlayer.getState().play([item], 0)

    expect(usePlayer.getState().buffering).toBe(true)
    expect(usePlayer.getState().playing).toBe(false)
  })
})

describe('finite Artist Shuffle sessions', () => {
  afterEach(() => {
    usePlayer.setState({
      queue: [],
      index: 0,
      playing: false,
      repeat: 'off',
      shuffle: false,
      radio: false,
      radioLoading: false,
      artistShuffleSession: null,
    })
    vi.restoreAllMocks()
  })

  it('plays every unique track ID once in the session’s forward path', () => {
    const items = [makePlayItem('a'), makePlayItem('b'), makePlayItem('c'), makePlayItem('d')]
    const duplicateTrack = { ...makePlayItem('duplicate-alias'), track: items[1].track }
    usePlayer.setState({ repeat: 'all', shuffle: true, radio: true })

    usePlayer.getState().playArtistShuffle([...items, duplicateTrack], 'artist-1')

    const sessionQueue = usePlayer.getState().queue
    expect(sessionQueue).toHaveLength(4)
    expect(new Set(sessionQueue.map((item) => item.track.id))).toEqual(
      new Set(items.map((item) => item.track.id)),
    )
    expect(usePlayer.getState().artistShuffleSession).toEqual({ artistId: 'artist-1' })

    const played = [sessionQueue[0].track.id]
    for (let i = 1; i < sessionQueue.length; i++) {
      usePlayer.getState().next()
      played.push(usePlayer.getState().queue[usePlayer.getState().index].track.id)
    }
    usePlayer.getState().next()

    expect(played).toHaveLength(4)
    expect(new Set(played)).toEqual(new Set(items.map((item) => item.track.id)))
    expect(usePlayer.getState().index).toBe(sessionQueue.length - 1)
    expect(usePlayer.getState().queue).toHaveLength(4)
    expect(usePlayer.getState().playing).toBe(false)
    expect(usePlayer.getState().radio).toBe(true)
    expect(usePlayer.getState().artistShuffleSession).toEqual({
      artistId: 'artist-1',
      completed: true,
    })
  })

  it('does not start an empty queue and stops safely for one track', () => {
    usePlayer.setState({ queue: [], index: 0, playing: false, radio: true, repeat: 'all' })
    usePlayer.getState().playArtistShuffle([], 'empty-artist')
    expect(usePlayer.getState().queue).toEqual([])
    expect(usePlayer.getState().artistShuffleSession).toBeNull()

    const only = makePlayItem('only')
    usePlayer.getState().playArtistShuffle([only], 'single-artist')
    expect(usePlayer.getState().queue.map((item) => item.track.id)).toEqual([only.track.id])
    usePlayer.getState().next()
    expect(usePlayer.getState().queue).toHaveLength(1)
    expect(usePlayer.getState().index).toBe(0)
    expect(usePlayer.getState().playing).toBe(false)
    expect(usePlayer.getState().artistShuffleSession).toEqual({
      artistId: 'single-artist',
      completed: true,
    })
  })

  it('keeps repeat-one and radio from extending the session while preserving navigation', () => {
    const items = [makePlayItem('repeat-a'), makePlayItem('repeat-b'), makePlayItem('repeat-c')]
    usePlayer.setState({ repeat: 'one', radio: true })
    usePlayer.getState().playArtistShuffle(items, 'repeat-artist')

    const firstTrackId = usePlayer.getState().queue[0].track.id
    usePlayer.getState().next()
    const secondTrackId = usePlayer.getState().queue[usePlayer.getState().index].track.id
    usePlayer.getState().prev()
    expect(usePlayer.getState().queue[usePlayer.getState().index].track.id).toBe(firstTrackId)
    usePlayer.getState().next()
    expect(usePlayer.getState().queue[usePlayer.getState().index].track.id).toBe(secondTrackId)

    usePlayer.getState().next()
    usePlayer.getState().next()
    expect(usePlayer.getState().queue).toHaveLength(3)
    expect(usePlayer.getState().playing).toBe(false)
    expect(usePlayer.getState().radio).toBe(true)
    expect(usePlayer.getState().artistShuffleSession?.completed).toBe(true)
  })

  it('returns to normal player rules when a different queue is played', () => {
    usePlayer.getState().playArtistShuffle([makePlayItem('artist')], 'artist-1')
    usePlayer.getState().play([makePlayItem('ordinary')], 0)
    expect(usePlayer.getState().artistShuffleSession).toBeNull()
  })
})
