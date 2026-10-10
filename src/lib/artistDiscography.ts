import type { ArtistDiscographyContext, Track } from './types'

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
): Track[] {
  const releaseRank = new Map<string, number>()
  const releaseNameRank = new Map<string, number>()
  releases.forEach((release, index) => {
    releaseRank.set(release.id, index)
    releaseNameRank.set(release.title.trim().toLocaleLowerCase(), index)
  })

  const ordered = tracks
    .filter((track) => !source || track.source === source)
    .map((track, index) => {
      // SoundCloud در دیسکوگرافی، هر سینگل را با شناسه‌ی خودِ ترک نشان می‌دهد.
      const singleReleaseRank = track.source === 'soundcloud' ? releaseRank.get(track.id) : undefined
      const rank = singleReleaseRank ?? (track.albumId && releaseRank.get(track.albumId)) ??
        (track.album ? releaseNameRank.get(track.album.trim().toLocaleLowerCase()) : undefined)
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
  const selectedIndex = unique.findIndex(({ track }) => track.id === selectedTrackId)
  return selectedIndex < 0 ? [] : unique.slice(selectedIndex).map(({ track }) => track)
}
