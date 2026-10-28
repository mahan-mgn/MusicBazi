import { describe, expect, it } from 'vitest'
import type { ArtistDetail, Track } from './types'
import { releaseSignature, tracksFromSelectedDiscography } from './artistDiscography'

const makeTrack = (id: string, album: string, albumId?: string): Track => ({
  id,
  title: id,
  artist: 'Artist',
  album,
  albumId,
  durationMs: 180000,
  artworkUrl: null,
  source: 'spotify',
  sourceUrl: `https://example.com/${id}`,
  previewUrl: null,
})

describe('tracksFromSelectedDiscography', () => {
  it('orders tracks by the captured release order and starts at the selected track', () => {
    const tracks = [
      makeTrack('old-1', 'Old', 'release-old'),
      makeTrack('new-1', 'New', 'release-new'),
      makeTrack('old-2', 'Old', 'release-old'),
      makeTrack('new-2', 'New', 'release-new'),
    ]

    expect(
      tracksFromSelectedDiscography(
        tracks,
        [
          { id: 'release-new', title: 'New' },
          { id: 'release-old', title: 'Old' },
        ],
        'new-1',
      ).map((track) => track.id),
    ).toEqual(['new-1', 'new-2', 'old-1', 'old-2'])
  })

  it('matches releases by title when tracks do not have album ids', () => {
    const tracks = [makeTrack('a', 'Earlier'), makeTrack('b', 'Later')]
    expect(
      tracksFromSelectedDiscography(
        tracks,
        [
          { id: 'later-id', title: 'Later' },
          { id: 'earlier-id', title: 'Earlier' },
        ],
        'b',
      ).map((track) => track.id),
    ).toEqual(['b', 'a'])
  })

  it('uses platform disc and track numbers when API results are out of order', () => {
    const tracks = [
      { ...makeTrack('later-track', 'Selected', 'selected'), discNumber: 1, trackNumber: 2 },
      { ...makeTrack('first-track', 'Selected', 'selected'), discNumber: 1, trackNumber: 1 },
      { ...makeTrack('next-release', 'Later', 'later'), discNumber: 1, trackNumber: 1 },
    ]

    expect(
      tracksFromSelectedDiscography(
        tracks,
        [
          { id: 'selected', title: 'Selected' },
          { id: 'later', title: 'Later' },
        ],
        'first-track',
      ).map((track) => track.id),
    ).toEqual(['first-track', 'later-track', 'next-release'])
  })

  it('preserves SoundCloud album track order using trackNumber even if tracks also appear as singles in releases', () => {
    const track7 = {
      ...makeTrack('sc:track:7', 'My Album', 'sc:playlist:album-1'),
      trackNumber: 7,
      source: 'soundcloud' as const,
    }
    const track8 = {
      ...makeTrack('sc:track:8', 'My Album', 'sc:playlist:album-1'),
      trackNumber: 8,
      source: 'soundcloud' as const,
    }
    const track9 = {
      ...makeTrack('sc:track:9', 'My Album', 'sc:playlist:album-1'),
      trackNumber: 9,
      source: 'soundcloud' as const,
    }

    // در پلتفرم ساندکلاد ممکن است ترک‌های آپلودشده علاوه بر آلبوم به عنوان سینگل هم در releases بیایند (با ترتیب جدید به قدیم)
    const releases = [
      { id: 'sc:track:9', title: 'Track 9' },
      { id: 'sc:track:8', title: 'Track 8' },
      { id: 'sc:track:7', title: 'Track 7' },
      { id: 'sc:playlist:album-1', title: 'My Album' },
    ]

    const result = tracksFromSelectedDiscography(
      [track9, track8, track7],
      releases,
      'sc:track:8',
      'soundcloud',
    ).map((t) => t.id)

    // ترک ۸ باید با ترک ۹ دنبال شود، نه ترک ۷
    expect(result).toEqual(['sc:track:8', 'sc:track:9'])
  })

  it('matches SoundCloud single releases by their track id', () => {
    const single = {
      ...makeTrack('sc:track:single-1', 'Single track', 'Unmatched metadata'),
      source: 'soundcloud' as const,
    }
    const later = {
      ...makeTrack('sc:track:single-2', 'Later track', 'Also unmatched'),
      source: 'soundcloud' as const,
    }

    expect(
      tracksFromSelectedDiscography(
        [later, single],
        [
          { id: single.id, title: 'Single' },
          { id: later.id, title: 'Later Single' },
        ],
        single.id,
      ).map((track) => track.id),
    ).toEqual([single.id, later.id])
  })

  it('filters out tracks from a different provider even when the release id matches', () => {
    const apple = { ...makeTrack('apple-track', 'Release', 'release'), source: 'apple' as const }
    const spotify = { ...makeTrack('spotify-track', 'Release', 'release'), source: 'spotify' as const }

    expect(
      tracksFromSelectedDiscography(
        [apple, spotify],
        [{ id: 'release', title: 'Release' }],
        'apple-track',
        'apple',
      ).map((track) => track.id),
    ).toEqual(['apple-track'])
  })

  it('matches Spotify and Apple singles when tracks lack albumId and release title has Single suffix', () => {
    const singleTrack: Track = {
      ...makeTrack('sp:track:single-1', 'Bikhiyal'),
      title: 'Bikhiyal',
      album: 'Bikhiyal',
      albumId: undefined,
      source: 'spotify',
    }
    const albumTrack: Track = {
      ...makeTrack('sp:track:album-1', 'Album Song', 'sp:album:album-1'),
      title: 'Album Song',
      album: 'Full Album',
      albumId: 'sp:album:album-1',
      source: 'spotify',
    }

    const releases = [
      { id: 'sp:album:single-release', title: 'Bikhiyal - Single' },
      { id: 'sp:album:album-1', title: 'Full Album' },
    ]

    const result = tracksFromSelectedDiscography(
      [singleTrack, albumTrack],
      releases,
      singleTrack.id,
      'spotify',
      singleTrack,
    )
    expect(result.map((t) => t.id)).toEqual(['sp:track:single-1', 'sp:track:album-1'])
  })

  it('matches selected track by trackDedupeKey when selectedTrackId is from a deduplicated single', () => {
    // The downloaded discography has the album version of the track
    const albumVersion: Track = {
      ...makeTrack('sp:track:album-ver', 'Hit Song', 'sp:album:1'),
      title: 'Hit Song',
      album: 'The Album',
      source: 'spotify',
    }
    const nextTrack: Track = {
      ...makeTrack('sp:track:album-next', 'Next Song', 'sp:album:1'),
      title: 'Next Song',
      album: 'The Album',
      source: 'spotify',
    }

    // But user selected the single version
    const singleVersion: Track = {
      ...makeTrack('sp:track:single-ver', 'Hit Song - Single'),
      title: 'Hit Song - Single',
      album: 'Hit Song',
      source: 'spotify',
    }

    const releases = [{ id: 'sp:album:1', title: 'The Album' }]

    const result = tracksFromSelectedDiscography(
      [albumVersion, nextTrack],
      releases,
      singleVersion.id,
      'spotify',
      singleVersion,
    )
    expect(result.map((t) => t.id)).toEqual(['sp:track:album-ver', 'sp:track:album-next'])
  })

  it('returns no replacement queue when the selected track is absent', () => {
    expect(
      tracksFromSelectedDiscography(
        [makeTrack('a', 'Release', 'release')],
        [{ id: 'release', title: 'Release' }],
        'missing',
      ),
    ).toEqual([])
  })
})

const makeAlbum = (id: string) => ({
  id,
  title: id,
  artist: 'Artist',
  year: 2024,
  artworkUrl: 'https://example.com/art.jpg',
  trackCount: 5,
  source: 'spotify' as const,
  sourceUrl: `https://example.com/${id}`,
})

const makeArtist = (overrides: Partial<ArtistDetail> = {}): ArtistDetail => ({
  id: 'sp:artist:1',
  name: 'Artist',
  artworkUrl: 'https://example.com/artist.jpg',
  source: 'spotify',
  sourceUrl: 'https://example.com/artist',
  subtitle: 'Artist',
  topTracks: [],
  albums: [],
  playlists: [],
  likedTracks: [],
  repostedTracks: [],
  related: [],
  ...overrides,
})

describe('releaseSignature', () => {
  it('is stable across two payloads with the same releases', () => {
    // payloadِ تازه از شبکه همیشه شیءِ تازه است؛ امضا نباید تکان بخورد
    const a = makeArtist({ albums: [makeAlbum('r1'), makeAlbum('r2')] })
    const b = makeArtist({ albums: [makeAlbum('r1'), makeAlbum('r2')] })
    expect(releaseSignature(a)).toBe(releaseSignature(b))
  })

  it('changes when a release is added', () => {
    const before = makeArtist({ albums: [makeAlbum('r1')] })
    const after = makeArtist({ albums: [makeAlbum('r1'), makeAlbum('r2')] })
    expect(releaseSignature(after)).not.toBe(releaseSignature(before))
  })

  it('ignores a changed title, cover or year', () => {
    /*
     * قلبِ تصمیم: امضا فقط شناسه‌هاست. اگر عنوان و کاور هم می‌آمدند، یک
     * تغییرِ نامِ آلبوم کلِ دیسکوگرافیِ لودشده را دور می‌ریخت و دانلودِ دوباره‌ی
     * صدها ترک را بی‌دلیل به راه می‌انداخت.
     */
    const before = makeArtist({ albums: [makeAlbum('r1')] })
    const after = makeArtist({
      albums: [{ ...makeAlbum('r1'), title: 'Renamed', artworkUrl: 'https://example.com/new.jpg', year: 2025 }],
    })
    expect(releaseSignature(after)).toBe(releaseSignature(before))
  })

  it('covers singles and top tracks, not just albums', () => {
    // ساندکلاد و یوتیوب موزیک تک‌آهنگ‌ها را جدا می‌دهند؛ یک تک‌آهنگِ تازه هم
    // باید دیسکوگرافی را بی‌اعتبار کند
    const base = makeArtist({ albums: [makeAlbum('r1')] })
    expect(releaseSignature(makeArtist({ ...base, singles: [makeAlbum('s1')] }))).not.toBe(
      releaseSignature(base),
    )
    expect(releaseSignature(makeArtist({ ...base, topTracks: [makeTrack('t1', 'X')] }))).not.toBe(
      releaseSignature(base),
    )
  })

  it('tolerates absent optional lists', () => {
    const { singles, ...withoutSingles } = makeArtist({ albums: [makeAlbum('r1')] })
    void singles
    expect(() => releaseSignature(withoutSingles as ArtistDetail)).not.toThrow()
  })
})
