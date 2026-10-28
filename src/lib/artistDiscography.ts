import { normalizeTrackTitle, trackDedupeKey } from './radio'
import type { ArtistDetail, ArtistDiscographyContext, Track } from './types'

/**
 * اثر انگشتِ فهرستِ انتشار — «آیا این آرتیستِ تازه واقعاً چیزِ جدیدی دارد؟».
 *
 * فقط شناسه‌ها، نه عنوان و کاور: با انتشارِ تازه ممکن است عنوانِ آلبومی عوض شود
 * یا کاورش نو شود، ولی آن‌چه دیسکوگرافیِ لودشده را بی‌اعتبار می‌کند *آلبومِ
 * تازه* است. اگر امضا شاملِ عنوان و کاور هم بود، یک تغییرِ نام، دانلودِ دوباره‌ی
 * صدها ترک را بی‌دلیل به راه می‌انداخت.
 */
export function releaseSignature(artist: ArtistDetail): string {
  const ids: string[] = []
  for (const list of [artist.albums, artist.singles, artist.topTracks]) {
    for (const item of list ?? []) ids.push(item.id)
  }
  return ids.join('|')
}

/** Find the selected release's tracks by provider ID, using its exact title only as a fallback. */
export function tracksForRelease(
  tracks: Track[],
  release: { id: string; title: string },
  source?: Track['source'],
): Track[] {
  const normalizeTitle = (title: string) => title.trim().toLocaleLowerCase().replace(/[‌\s]+/g, ' ')
  const matchingSource = tracks.filter((track) => !source || track.source === source)
  const byId = matchingSource.filter(
    (track) => track.albumId === release.id || (track.source === 'soundcloud' && track.id === release.id),
  )
  const candidates = byId.length
    ? byId
    : matchingSource.filter(
        (track) => track.album && normalizeTitle(track.album) === normalizeTitle(release.title),
      )

  const seen = new Set<string>()
  return candidates
    .map((track, index) => ({ track, index }))
    .sort((a, b) => {
      const discA = a.track.discNumber ?? 1
      const discB = b.track.discNumber ?? 1
      if (discA !== discB) return discA - discB
      if (a.track.trackNumber != null && b.track.trackNumber != null) {
        return a.track.trackNumber - b.track.trackNumber
      }
      return a.index - b.index
    })
    .map(({ track }) => track)
    .filter((track) => {
      if (seen.has(track.id)) return false
      seen.add(track.id)
      return true
    })
}

/** Return the selected track and later releases in the release order captured from the artist page. */
export function tracksFromSelectedDiscography(
  tracks: Track[],
  releases: ArtistDiscographyContext['releases'],
  selectedTrackId: string,
  source?: Track['source'],
  selectedTrack?: Track,
): Track[] {
  const releaseRank = new Map<string, number>()
  const releaseNameRank = new Map<string, number>()
  releases.forEach((release, index) => {
    releaseRank.set(release.id, index)
    const raw = release.title.trim().toLocaleLowerCase()
    const norm = normalizeTrackTitle(release.title)
    if (!releaseNameRank.has(raw)) releaseNameRank.set(raw, index)
    if (!releaseNameRank.has(norm)) releaseNameRank.set(norm, index)
  })

  const ordered = tracks
    .filter((track) => !source || track.source === source)
    .map((track, index) => {
      // اولویت با رتبه آلبوم است تا همه ترک‌های آلبوم یک رتبه بگیرند و با شماره ترک مرتب شوند.
      // تطبیق با شناسه‌ی خودِ ترک (singleReleaseRank) یا عنوان نرمال‌شده برای سینگل‌های بدون albumId
      const rawAlbum = track.album?.trim().toLocaleLowerCase()
      const normAlbum = track.album ? normalizeTrackTitle(track.album) : undefined
      const normTitle = track.title ? normalizeTrackTitle(track.title) : undefined
      const albumReleaseRank =
        (track.albumId && releaseRank.get(track.albumId)) ??
        (rawAlbum && releaseNameRank.get(rawAlbum)) ??
        (normAlbum && releaseNameRank.get(normAlbum)) ??
        (normTitle && releaseNameRank.get(normTitle))
      const singleReleaseRank = releaseRank.get(track.id)
      const rank = albumReleaseRank ?? singleReleaseRank
      return { track, index, rank }
    })
    .filter((entry): entry is { track: Track; index: number; rank: number } => entry.rank !== undefined)
    .sort((a, b) => {
      if (a.rank !== b.rank) return a.rank - b.rank

      // APIهای دیسکوگرافی گاهی ترک‌های یک آلبوم را با ترتیب متفاوت از صفحه
      // برمی‌گردانند؛ شماره دیسک و ترک ترتیب اصلی انتشار را تعیین می‌کنند.
      const discA = a.track.discNumber ?? 1
      const discB = b.track.discNumber ?? 1
      if (discA !== discB) return discA - discB
      if (a.track.trackNumber != null && b.track.trackNumber != null) {
        return a.track.trackNumber - b.track.trackNumber
      }
      return a.index - b.index
    })

  const seen = new Set<string>()
  const unique = ordered.filter(({ track }) => {
    if (seen.has(track.id)) return false
    seen.add(track.id)
    return true
  })
  let selectedIndex = unique.findIndex(({ track }) => track.id === selectedTrackId)
  if (selectedIndex < 0 && selectedTrack) {
    const key = trackDedupeKey(selectedTrack)
    selectedIndex = unique.findIndex(({ track }) => trackDedupeKey(track) === key)
  }
  return selectedIndex < 0 ? [] : unique.slice(selectedIndex).map(({ track }) => track)
}
