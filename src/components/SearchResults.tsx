import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { digits } from '../lib/format'
import { useI18n } from '../lib/i18n'
import { SOURCE_LABEL, type Album, type Artist, type Playlist, type SearchResults as Results, type Source, type Track } from '../lib/types'
import AnimatedList from './AnimatedList'
import Artwork from './Artwork'
import EmptyState from './EmptyState'
import { useIntranet } from '../store/net'
import SpotlightCard from './SpotlightCard'
import SourceBadge from './SourceBadge'
import TrackRow from './TrackRow'
import { AlbumCard, ArtistCard, PlaylistRow } from './cards'
import { ChevronIcon, PauseIcon, PlayIcon, SearchIcon } from './icons'
import SourceLogo, { SOURCE_COLOR } from './logos'

interface Props {
  results: Results
  playingId: string | null
  onTogglePlay: (track: Track) => void
  onOpenAlbum: (album: Album) => void
  onOpenArtist: (artist: Artist) => void
  onOpenPlaylist: (playlist: Playlist) => void
}

type TabId = 'all' | 'songs' | 'artists' | 'albums' | 'playlists'

/** تعداد کارت‌هایی که در ردیفِ افقیِ تب «همه» نشان داده می‌شود */
const RAIL_COUNT = 8
/** تعداد آهنگ‌های کنارِ برترین نتیجه — ۴ تا برای هماهنگی ارتفاع با کارت نتیجه برتر */
const TOP_SONGS_COUNT = 4
const PREVIEW_COUNT = 5

type TopResultItem =
  | { kind: 'artist'; data: Artist }
  | { kind: 'track'; data: Track }
  | { kind: 'album'; data: Album }
  | { kind: 'playlist'; data: Playlist }

/**
 * ترتیبِ اولویتِ پلتفرم برای «برترین نتیجه» — ساندکلاد اول، اسپاتیفای دوم،
 * بقیه هرچه باشد بعد از این دوتا (بدون ترجیح خاصی بین‌شان).
 */
const TOP_RESULT_SOURCE_PRIORITY: Source[] = ['soundcloud', 'spotify']

/** در یک پلتفرمِ مشخص (یا همه‌ی پلتفرم‌ها اگر source داده نشود)، نوع با بالاترین اولویت را برمی‌گرداند */
function bestOfSource(results: Results, source?: Source): TopResultItem | null {
  const only = <T extends { source: Source }>(arr: T[]) =>
    source ? arr.filter((x) => x.source === source) : arr

  const artists = only(results.artists)
  if (artists[0]) return { kind: 'artist', data: artists[0] }
  const tracks = only(results.tracks)
  if (tracks[0]) return { kind: 'track', data: tracks[0] }
  const albums = only(results.albums)
  if (albums[0]) return { kind: 'album', data: albums[0] }
  const playlists = only(results.playlists)
  if (playlists[0]) return { kind: 'playlist', data: playlists[0] }
  return null
}

function pickTopResult(results: Results): TopResultItem | null {
  for (const source of TOP_RESULT_SOURCE_PRIORITY) {
    const item = bestOfSource(results, source)
    if (item) return item
  }
  return bestOfSource(results)
}

function SectionHeader({
  title,
  count,
  onShowAll,
}: {
  title: string
  count: number
  onShowAll?: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="flex items-center justify-between">
      <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-2">{title}</h2>
      {onShowAll && (
        <button
          onClick={onShowAll}
          className="inline-flex items-center gap-1 text-xs text-accent transition hover:brightness-125"
        >
          {t.showAll(count)}
          <ChevronIcon className="size-3.5" />
        </button>
      )}
    </div>
  )
}

function TopResultCard({
  item,
  playingId,
  onTogglePlay,
  onOpenAlbum,
  onOpenArtist,
  onOpenPlaylist,
}: {
  item: TopResultItem
  playingId: string | null
  onTogglePlay: (track: Track) => void
  onOpenAlbum: (album: Album) => void
  onOpenArtist: (artist: Artist) => void
  onOpenPlaylist: (playlist: Playlist) => void
}) {
  const { t } = useI18n()

  const meta = (() => {
    switch (item.kind) {
      case 'artist':
        return {
          title: item.data.name,
          subtitle: null as string | null,
          type: t.typeArtist,
          source: item.data.source,
          artworkUrl: item.data.artworkUrl,
          seed: item.data.id,
          rounded: 'rounded-full' as const,
        }
      case 'track':
        return {
          title: item.data.title,
          subtitle: item.data.artist,
          type: t.typeSong,
          source: item.data.source,
          artworkUrl: item.data.artworkUrl,
          seed: item.data.albumId ?? item.data.id,
          rounded: 'rounded-xl' as const,
        }
      case 'album':
        return {
          title: item.data.title,
          subtitle: item.data.artist,
          type: t.typeAlbum,
          source: item.data.source,
          artworkUrl: item.data.artworkUrl,
          seed: item.data.id,
          rounded: 'rounded-xl' as const,
        }
      case 'playlist':
        return {
          title: item.data.title,
          subtitle: item.data.owner,
          type: t.typePlaylist,
          source: item.data.source,
          artworkUrl: item.data.artworkUrl,
          seed: item.data.id,
          rounded: 'rounded-xl' as const,
        }
    }
  })()

  const playing = item.kind === 'track' && playingId === item.data.id

  const body = (
    <>
      <span
        aria-hidden
        className="src-glow pointer-events-none absolute -inset-4 -z-10 rounded-2xl blur-2xl"
        style={{ '--src': SOURCE_COLOR[meta.source] } as React.CSSProperties}
      />
      <Artwork
        src={meta.artworkUrl}
        alt={meta.title}
        seed={meta.seed}
        rounded={meta.rounded}
        className="size-24 shadow-lg shadow-black/30"
      />
      <div className="mt-auto min-w-0 pt-3">
        <p className="bidi truncate text-xl font-bold">{meta.title}</p>
        {meta.subtitle && (
          <p className="bidi truncate text-sm text-muted">
            <bdi>{meta.subtitle}</bdi>
          </p>
        )}
        <p className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-muted">
          {meta.type}
          <SourceBadge source={meta.source} />
        </p>
      </div>
    </>
  )

  if (item.kind === 'track') {
    const track = item.data
    return (
      <SpotlightCard className="group relative flex min-h-64 w-full flex-col overflow-hidden rounded-2xl bg-panel-2 p-5">
        {body}
        <button
          onClick={() => onTogglePlay(track)}
          aria-label={playing ? t.stopPreview : t.playTrack(track.title)}
          className={`absolute bottom-5 end-5 grid size-11 place-items-center rounded-full bg-accent text-accent-fg shadow-lg shadow-black/40 transition ${
            playing ? '' : 'hover-reveal opacity-0 translate-y-1 group-hover:translate-y-0 group-hover:opacity-100'
          }`}
        >
          {playing ? <PauseIcon className="size-5" /> : <PlayIcon className="size-5" />}
        </button>
      </SpotlightCard>
    )
  }

  const onClick =
    item.kind === 'artist'
      ? () => onOpenArtist(item.data)
      : item.kind === 'album'
        ? () => onOpenAlbum(item.data)
        : () => onOpenPlaylist(item.data)

  return (
    <SpotlightCard
      as="button"
      onClick={onClick}
      className="group relative flex min-h-64 w-full flex-col overflow-hidden rounded-2xl bg-panel-2 p-5 text-start transition hover:bg-panel-2/70"
    >
      {body}
    </SpotlightCard>
  )
}

export default function SearchResults({
  results,
  playingId,
  onTogglePlay,
  onOpenAlbum,
  onOpenArtist,
  onOpenPlaylist,
}: Props) {
  const [tab, setTab] = useState<TabId>('all')
  const [selectedSource, setSelectedSource] = useState<Source | null>(null)
  const { t, lang } = useI18n()

  // پیش‌گرم‌سازی ۲ ترک اول نتایج جستجو تا موقع کلیک کاربر آهنگ بلافاصله پلی شود
  useEffect(() => {
    if (!results.tracks.length) return
    const topTracks = results.tracks.slice(0, 2)
    const timers: ReturnType<typeof setTimeout>[] = []
    topTracks.forEach((track, i) => {
      const timer = setTimeout(() => {
        void api.prefetchStream?.(track)
      }, i * 600)
      timers.push(timer)
    })
    return () => {
      timers.forEach((t) => clearTimeout(t))
    }
  }, [results.tracks])

  // در حالتِ اینترانت این نتایج از کشِ سرور آمده‌اند، نه از کاتالوگ‌ها. نگفتنش
  // یعنی کاربر فکر می‌کند کاتالوگ فقیر شده — و دنبال آهنگی می‌گردد که فقط
  // «هنوز از اینجا رد نشده».
  const intranet = useIntranet()

  // پلتفرم‌های موجود در نتایج جستجو
  const availableSources = useMemo(() => {
    const present = new Set<Source>()
    for (const tr of results.tracks) present.add(tr.source)
    for (const ar of results.artists) present.add(ar.source)
    for (const al of results.albums) present.add(al.source)
    for (const pl of results.playlists) present.add(pl.source)
    return (['spotify', 'soundcloud', 'apple', 'deezer', 'youtube', 'youtube_music'] as const).filter((s) =>
      present.has(s),
    )
  }, [results])

  const sourceCount = useCallback(
    (source: Source) => {
      return (
        results.tracks.filter((tr) => tr.source === source).length +
        results.artists.filter((ar) => ar.source === source).length +
        results.albums.filter((al) => al.source === source).length +
        results.playlists.filter((pl) => pl.source === source).length
      )
    },
    [results],
  )

  const displayResults = useMemo(() => {
    if (!selectedSource) return results
    return {
      query: results.query,
      tracks: results.tracks.filter((tr) => tr.source === selectedSource),
      artists: results.artists.filter((ar) => ar.source === selectedSource),
      albums: results.albums.filter((al) => al.source === selectedSource),
      playlists: results.playlists.filter((pl) => pl.source === selectedSource),
    }
  }, [results, selectedSource])

  const counts = {
    songs: displayResults.tracks.length,
    artists: displayResults.artists.length,
    albums: displayResults.albums.length,
    playlists: displayResults.playlists.length,
  }
  const total = counts.songs + counts.artists + counts.albums + counts.playlists

  if (total === 0 && !selectedSource) {
    return (
      <EmptyState
        icon={<SearchIcon className="size-5" />}
        text={intranet ? t.intranetNoResults : t.noResults(results.query)}
      />
    )
  }

  const tabs = (
    [
      { id: 'all', label: t.all, count: total },
      { id: 'songs', label: t.songs, count: counts.songs },
      { id: 'artists', label: t.artists, count: counts.artists },
      { id: 'albums', label: t.albums, count: counts.albums },
      { id: 'playlists', label: t.playlists, count: counts.playlists },
    ] satisfies { id: TabId; label: string; count: number }[]
  ).filter((x) => x.count > 0)

  const isAll = tab === 'all'
  const topResult = isAll ? (selectedSource ? bestOfSource(displayResults, selectedSource) : pickTopResult(displayResults)) : null

  return (
    <div className="rise overflow-hidden rounded-2xl border border-line-soft bg-panel/50">
      <div className="flex items-center justify-between gap-3 border-b border-line-soft px-4 py-3">
        <p className="truncate text-sm">
          {t.resultsFor('')}
          <span className="font-semibold text-accent">{results.query}</span>
        </p>
        <span className="shrink-0 text-[11px] text-muted-2">{t.foundSoFar(total)}</span>
      </div>

      {intranet && (
        <p className="border-b border-line-soft bg-panel-2/60 px-4 py-2 text-[11px] leading-relaxed text-muted-2">
          <span className="font-semibold text-muted">{t.intranetResults}</span>{' '}
          {t.intranetResultsHint}
        </p>
      )}

      {/* چیپ‌های فیلتر پلتفرم‌ها (اسپاتیفای، ساندکلاد، اپل، دیزر) */}
      {availableSources.length > 1 && (
        <div className="flex items-center gap-1.5 overflow-x-auto border-b border-line-soft px-4 py-2.5 no-scrollbar">
          <button
            type="button"
            onClick={() => setSelectedSource(null)}
            className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[11px] transition ${
              !selectedSource
                ? 'bg-accent font-semibold text-accent-fg'
                : 'bg-panel-2 text-muted hover:text-fg'
            }`}
          >
            {t.all}
          </button>
          {availableSources.map((source) => (
            <button
              key={source}
              type="button"
              onClick={() => setSelectedSource((cur) => (cur === source ? null : source))}
              className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition ${
                selectedSource === source
                  ? 'border-accent bg-accent/15 font-semibold text-accent'
                  : 'border-line bg-panel-2 text-muted hover:text-fg'
              }`}
            >
              <SourceLogo source={source} className="size-3" />
              <span>{SOURCE_LABEL[source]}</span>
              <span className="text-[10px] opacity-70">({digits(sourceCount(source), lang)})</span>
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-1.5 border-b border-line-soft px-4 py-2.5">
        {tabs.map((x) => (
          <button
            key={x.id}
            onClick={() => setTab(x.id)}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition ${
              tab === x.id
                ? 'bg-accent font-semibold text-accent-fg'
                : 'bg-panel-2 text-muted hover:text-fg'
            }`}
          >
            {x.label}
            <span className={tab === x.id ? 'opacity-70' : 'text-muted-2'}>
              {digits(x.count, lang)}
            </span>
          </button>
        ))}
      </div>

      <div className="space-y-8 p-4">
        {isAll && (topResult || counts.songs > 0) && (
          <section className="grid items-start gap-4 md:grid-cols-2">
            {topResult && (
              <div className="flex flex-col gap-3">
                <SectionHeader title={t.topResult} count={0} />
                <TopResultCard
                  item={topResult}
                  playingId={playingId}
                  onTogglePlay={onTogglePlay}
                  onOpenAlbum={onOpenAlbum}
                  onOpenArtist={onOpenArtist}
                  onOpenPlaylist={onOpenPlaylist}
                />
              </div>
            )}

            {counts.songs > 0 && (
              <div className="flex flex-col gap-3">
                <SectionHeader title={t.songs} count={0} />
                <AnimatedList className="space-y-0.5">
                  {displayResults.tracks.slice(0, TOP_SONGS_COUNT).map((x) => (
                    <TrackRow
                      key={x.id}
                      track={x}
                      playingId={playingId}
                      onTogglePlay={onTogglePlay}
                      showSource
                    />
                  ))}
                </AnimatedList>
                {counts.songs > TOP_SONGS_COUNT && (
                  <button
                    onClick={() => setTab('songs')}
                    className="inline-flex items-center gap-1 text-xs text-accent transition hover:brightness-125"
                  >
                    {t.showAll(counts.songs)}
                    <ChevronIcon className="size-3.5" />
                  </button>
                )}
              </div>
            )}
          </section>
        )}

        {tab === 'songs' && counts.songs > 0 && (
          <section className="space-y-3">
            <SectionHeader title={t.songs} count={counts.songs} />
            <AnimatedList className="space-y-0.5">
              {displayResults.tracks.map((x) => (
                <TrackRow
                  key={x.id}
                  track={x}
                  playingId={playingId}
                  onTogglePlay={onTogglePlay}
                  showSource
                />
              ))}
            </AnimatedList>
          </section>
        )}

        {(isAll || tab === 'artists') && counts.artists > 0 && (
          <section className="space-y-3">
            <SectionHeader
              title={t.artists}
              count={counts.artists}
              onShowAll={isAll && counts.artists > PREVIEW_COUNT ? () => setTab('artists') : undefined}
            />
            {isAll ? (
              <div className="no-scrollbar -mx-1 flex gap-1 overflow-x-auto px-1">
                {displayResults.artists.slice(0, RAIL_COUNT).map((x) => (
                  <div key={x.id} className="w-28 shrink-0 sm:w-32">
                    <ArtistCard artist={x} onOpen={() => onOpenArtist(x)} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
                {displayResults.artists.map((x) => (
                  <ArtistCard key={x.id} artist={x} onOpen={() => onOpenArtist(x)} />
                ))}
              </div>
            )}
          </section>
        )}

        {(isAll || tab === 'albums') && counts.albums > 0 && (
          <section className="space-y-3">
            <SectionHeader
              title={t.albums}
              count={counts.albums}
              onShowAll={isAll && counts.albums > PREVIEW_COUNT ? () => setTab('albums') : undefined}
            />
            {isAll ? (
              <div className="no-scrollbar -mx-1 flex gap-1 overflow-x-auto px-1">
                {displayResults.albums.slice(0, RAIL_COUNT).map((x) => (
                  <div key={x.id} className="w-32 shrink-0 sm:w-36">
                    <AlbumCard album={x} onOpen={() => onOpenAlbum(x)} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                {displayResults.albums.map((x) => (
                  <AlbumCard key={x.id} album={x} onOpen={() => onOpenAlbum(x)} />
                ))}
              </div>
            )}
          </section>
        )}

        {(isAll || tab === 'playlists') && counts.playlists > 0 && (
          <section className="space-y-3">
            <SectionHeader
              title={t.playlists}
              count={counts.playlists}
              onShowAll={
                isAll && counts.playlists > PREVIEW_COUNT ? () => setTab('playlists') : undefined
              }
            />
            <div className="space-y-0.5">
              {(isAll ? displayResults.playlists.slice(0, PREVIEW_COUNT) : displayResults.playlists).map((x) => (
                <PlaylistRow key={x.id} playlist={x} onOpen={() => onOpenPlaylist(x)} />
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
