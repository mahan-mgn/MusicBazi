import type {
  Album,
  AlbumDetail,
  Artist,
  ArtistDetail,
  Playlist,
  Source,
  Track,
} from '../types'

const min = (m: number, s = 0) => (m * 60 + s) * 1000

interface Seed {
  title: string
  m: number
  s: number
}

const MARD_E_TANHA: Seed[] = [
  { title: 'Gonjeshkak', m: 3, s: 33 },
  { title: 'Saghf', m: 5, s: 10 },
  { title: 'Avar', m: 5, s: 9 },
  { title: 'Ayeneha (Maskh)', m: 4, s: 15 },
  { title: 'Mard-e Tanha', m: 3, s: 5 },
  { title: 'Koodakaneh', m: 5, s: 31 },
  { title: 'Shabaneh, Pt. I', m: 5, s: 9 },
  { title: 'Jomeh', m: 4, s: 33 },
  { title: 'Hafteye Khakestari', m: 4, s: 46 },
  { title: 'Shabaneh, Pt. II', m: 4, s: 33 },
  { title: 'Asir-e Shab', m: 4, s: 42 },
  { title: 'Morgh-e Sahar', m: 3, s: 20 },
  { title: 'Vahdat', m: 1, s: 44 },
]

function makeTracks(album: Album, seeds: Seed[]): Track[] {
  return seeds.map((seed, i) => ({
    id: `${album.id}:t${i + 1}`,
    title: seed.title,
    artist: album.artist,
    album: album.title,
    albumId: album.id,
    durationMs: min(seed.m, seed.s),
    artworkUrl: null,
    source: album.source,
    sourceUrl: `${album.sourceUrl}?i=${i + 1}`,
    previewUrl: null,
  }))
}

export const ALBUMS: Album[] = [
  {
    id: 'al-mard-e-tanha',
    title: 'Mard-E Tanha',
    artist: 'Farhad Mehrad',
    year: 1978,
    artworkUrl: null,
    trackCount: MARD_E_TANHA.length,
    source: 'apple',
    sourceUrl: 'https://music.apple.com/us/album/mard-e-tanha/1801042661',
  },
  {
    id: 'al-black-cats',
    title: 'Farhad In Black Cats: Studio Sketches',
    artist: 'Farhad Mehrad',
    year: 1968,
    artworkUrl: null,
    trackCount: 11,
    source: 'apple',
    sourceUrl: 'https://music.apple.com/us/album/farhad-in-black-cats/1801042001',
  },
  {
    id: 'al-barf',
    title: 'Barf',
    artist: 'Farhad Mehrad',
    year: 1988,
    artworkUrl: null,
    trackCount: 9,
    source: 'apple',
    sourceUrl: 'https://music.apple.com/us/album/barf/1801042112',
  },
  {
    id: 'al-khab-dar-bidari',
    title: 'Khab Dar Bidari',
    artist: 'Farhad Mehrad',
    year: 1993,
    artworkUrl: null,
    trackCount: 8,
    source: 'deezer',
    sourceUrl: 'https://www.deezer.com/album/12345678',
  },
  {
    id: 'al-covers-iii',
    title: 'The Covers Collection III: Studio Sketches',
    artist: 'Farhad Mehrad',
    year: 1971,
    artworkUrl: null,
    trackCount: 10,
    source: 'apple',
    sourceUrl: 'https://music.apple.com/us/album/covers-iii/1801043330',
  },
  {
    id: 'al-live-vienna',
    title: 'Live in Vienna, 1993',
    artist: 'Farhad Mehrad',
    year: 1993,
    artworkUrl: null,
    trackCount: 12,
    source: 'soundcloud',
    sourceUrl: 'https://soundcloud.com/farhad/sets/live-vienna-1993',
  },
  {
    id: 'al-echoes',
    title: 'Echoes of My Mind',
    artist: 'Farhad Mehrad',
    year: 1995,
    artworkUrl: null,
    trackCount: 7,
    source: 'deezer',
    sourceUrl: 'https://www.deezer.com/album/12345679',
  },
  {
    id: 'al-live-tehran',
    title: 'Live In Tehran, 1988',
    artist: 'Farhad Mehrad',
    year: 1988,
    artworkUrl: null,
    trackCount: 14,
    source: 'soundcloud',
    sourceUrl: 'https://soundcloud.com/farhad/sets/live-tehran-1988',
  },
]

const ALBUM_TRACKS: Record<string, Seed[]> = {
  'al-mard-e-tanha': MARD_E_TANHA,
  'al-barf': [
    { title: 'Barf', m: 6, s: 12 },
    { title: 'Sar-Oomad Zemestoon', m: 4, s: 2 },
    { title: 'Vahdat', m: 3, s: 51 },
    { title: 'Kooch', m: 5, s: 22 },
    { title: 'Ghesse-ye Do Mahi', m: 4, s: 8 },
    { title: 'Shabaneh', m: 5, s: 44 },
    { title: 'Ayeneha', m: 4, s: 30 },
    { title: 'Parvaz', m: 3, s: 58 },
    { title: 'Sokoot', m: 6, s: 3 },
  ],
}

/** آلبومی که لیست دستی ندارد، ترک‌هایش تولید می‌شود */
function fallbackSeeds(album: Album): Seed[] {
  return Array.from({ length: album.trackCount }, (_, i) => ({
    title: `${album.title} — Track ${i + 1}`,
    m: 3 + ((i * 7) % 4),
    s: (i * 23) % 60,
  }))
}

export function albumDetail(album: Album): AlbumDetail {
  const seeds = ALBUM_TRACKS[album.id] ?? fallbackSeeds(album)
  const tracks = makeTracks(album, seeds)
  return {
    ...album,
    trackCount: tracks.length,
    durationMs: tracks.reduce((sum, t) => sum + t.durationMs, 0),
    tracks,
  }
}

/**
 * هنرمندها — به‌ازای هر پلتفرم یک ردیف.
 *
 * «فرهاد مهراد» عمداً از هر چهار کاتالوگ آمده: سرور هم همین کار را می‌کند و
 * یکتاسازی فقط درونِ هر منبع است، تا صفحه‌ی هر پلتفرم در دسترس بماند.
 */
export const ARTISTS: Artist[] = [
  { name: 'فرهاد مهراد', subtitle: '۱۳ آلبوم', source: 'apple' },
  { name: 'فرهاد مهراد', subtitle: '۸۹٬۴۰۰ دنبال‌کننده', source: 'deezer' },
  { name: 'Farhad Mehrad', subtitle: 'Persian Classic', source: 'spotify' },
  { name: 'farhad-mehrad', subtitle: '۲٬۱۰۰ دنبال‌کننده', source: 'soundcloud' },
  { name: 'mhrab', subtitle: 'هنرمند', source: 'apple' },
  { name: 'fred', subtitle: 'هنرمند', source: 'deezer' },
  { name: 'hjlrnly', subtitle: 'ساندکلاد', source: 'soundcloud' },
  { name: 'مهیار قدادی', subtitle: 'هنرمند', source: 'apple' },
].map((a, i) => ({
  id: `ar-${i}`,
  name: a.name,
  subtitle: a.subtitle,
  artworkUrl: null,
  source: a.source as Source,
  sourceUrl: `https://music.apple.com/us/artist/${i}`,
}))

export const PLAYLISTS: Playlist[] = [
  {
    id: 'pl-1',
    title: 'فرهاد مهراد',
    owner: 'ebrahim saraf',
    trackCount: 32,
    artworkUrl: null,
    source: 'deezer',
    sourceUrl: 'https://www.deezer.com/playlist/1111',
  },
  {
    id: 'pl-2',
    title: 'بهترین های فرهاد مهراد | The Best of Farhad Mehrad',
    owner: 'linss',
    trackCount: 41,
    artworkUrl: null,
    source: 'deezer',
    sourceUrl: 'https://www.deezer.com/playlist/2222',
  },
  {
    id: 'pl-3',
    title: 'فرهاد مهراد',
    owner: 'Ali Rrsa',
    trackCount: 19,
    artworkUrl: null,
    source: 'soundcloud',
    sourceUrl: 'https://soundcloud.com/alirrsa/sets/farhad',
  },
  {
    id: 'pl-4',
    title: 'فرهاد مهراد — کامل',
    owner: 's_mv',
    trackCount: 66,
    artworkUrl: null,
    source: 'soundcloud',
    sourceUrl: 'https://soundcloud.com/smv/sets/farhad-full',
  },
]

/** ترک‌های تخت برای سکشن «آهنگ‌ها» در نتایج جستجو */
export const TOP_TRACKS: Track[] = albumDetail(ALBUMS[0]).tracks.slice(0, 8)

/**
 * صفحه‌ی هنرمند در مود دمو.
 * کاتالوگ ماک فقط یک هنرمند واقعی دارد، پس دیسکوگرافی همه‌ی آلبوم‌هاست.
 */
export function artistDetail(artist: Artist): ArtistDetail {
  return {
    ...artist,
    subtitle: `${ALBUMS.length} آلبوم`,
    topTracks: TOP_TRACKS,
    albums: [...ALBUMS].sort((a, b) => b.year - a.year),
    // پلی‌لیستِ همان کاتالوگِ ماک — برای دیدنِ بخشِ پلی‌لیست‌های صفحه بدون سرور
    playlists: PLAYLISTS.filter((p) => p.source === artist.source),
    // فقط برای دموی ساندکلاد پر است؛ بقیه‌ی پلتفرم‌ها این تب‌ها را ندارند
    likedTracks: artist.source === 'soundcloud' ? TOP_TRACKS.slice(0, 3) : [],
    repostedTracks: artist.source === 'soundcloud' ? TOP_TRACKS.slice(3, 5) : [],
    related: artist.source === 'deezer' ? ARTISTS.filter((a) => a.source === 'deezer' && a.id !== artist.id).slice(0, 4) : [],
    radio: artist.source === 'deezer' ? TOP_TRACKS.slice(0, 5) : [],
  }
}
