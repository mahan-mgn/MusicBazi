"""
استخراج متادیتا و جستجو در یوتیوب موزیک (YouTube Music) با ytmusicapi.
کاتالوگ کامل هنرمند بر اساس الگوی معماری BitChord (مرور آلبوم‌ها، تک‌آهنگ‌ها، ترک‌ها و هنرمندان مرتبط).
همه‌ی توابع بلاک‌کننده‌اند و باید در thread اجرا شوند.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from ytmusicapi import YTMusic

from ..config import PROXY, YOUTUBE_MUSIC_ENABLED
from ..models import Album, AlbumDetail, Artist, ArtistDetail, Playlist, SearchResults, Track

log = logging.getLogger(__name__)

_client: YTMusic | None = None


def enabled() -> bool:
    """آیا کاتالوگ یوتیوب موزیک در جستجو فعال است؟"""
    return YOUTUBE_MUSIC_ENABLED


def _get_client() -> YTMusic:
    """ساخت نمونه‌ی عمومی کلاینت ytmusicapi با پروکسی در صورت وجود."""
    global _client
    if _client is None:
        proxies = {"http": PROXY, "https": PROXY} if PROXY else None
        _client = YTMusic(proxies=proxies)
    return _client


def _best_thumb(item: dict[str, Any]) -> str | None:
    """انتخاب باکیفیت‌ترین کاور از میان بندانگشتی‌های یوتیوب موزیک."""
    thumbs = [t for t in (item.get("thumbnails") or []) if t.get("url")]
    if not thumbs:
        return None
    sized = [t for t in thumbs if t.get("width")]
    if sized:
        return max(sized, key=lambda t: t["width"])["url"]
    return thumbs[-1]["url"]


def _clean_artists(artists: list[dict[str, Any]] | None) -> str:
    """ترکیب نام هنرمندان با ویرگول."""
    if not artists:
        return "ناشناس"
    names = [a.get("name", "").strip() for a in artists if a.get("name")]
    return ", ".join(names) if names else "ناشناس"


def _item_to_track(item: dict[str, Any], default_artist: str | None = None) -> Track | None:
    """تبدیل ردیف آهنگ YouTube Music به مدل استاندارد Track."""
    video_id = item.get("videoId")
    credits_id = str(item.get("creditsBrowseId") or "")
    if credits_id.startswith("MPTC") and len(credits_id) == 15:
        video_id = credits_id[4:]
    if not video_id:
        return None

    raw_artists = item.get("artists") or []
    first_artist_id = raw_artists[0].get("id") if raw_artists else None
    artist_id = f"ytm:artist:{first_artist_id}" if first_artist_id else None

    album_dict = item.get("album") or {}
    album_name = album_dict.get("name") if isinstance(album_dict, dict) else None
    album_id = (
        f"ytm:album:{album_dict['id']}"
        if isinstance(album_dict, dict) and album_dict.get("id")
        else None
    )

    duration_sec = item.get("duration_seconds")
    if duration_sec is None:
        raw_dur = str(item.get("duration") or "")
        parts = raw_dur.split(":")
        try:
            if len(parts) == 2:
                duration_sec = int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                duration_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            else:
                duration_sec = 0
        except ValueError:
            duration_sec = 0

    artist_name = _clean_artists(raw_artists)
    if artist_name == "ناشناس" and default_artist:
        artist_name = default_artist

    return Track(
        id=f"ytm:track:{video_id}",
        title=item.get("title") or "بدون عنوان",
        artist=artist_name,
        album=album_name,
        albumId=album_id,
        durationMs=int(duration_sec or 0) * 1000,
        artworkUrl=_best_thumb(item),
        source="youtube_music",
        sourceUrl=f"https://music.youtube.com/watch?v={video_id}",
        previewUrl=None,
        explicit=bool(item.get("isExplicit")),
        artistId=artist_id,
        trackNumber=item.get("trackNumber"),
    )


def search(query: str, limit: int = 20) -> SearchResults:
    """
    جستجوی مستقل در کاتالوگ YouTube Music.
    ترک‌ها، آلبوم‌ها و هنرمندان رسمی مستقیماً از اندپوینت‌های فیلترشده استخراج می‌شوند.
    """
    q = query.strip()
    if not q:
        return SearchResults(query=query)

    try:
        client = _get_client()
        raw_songs = client.search(q, filter="songs", limit=limit)
    except Exception as exc:
        log.warning("YouTube Music songs search error for %r: %s", q, exc)
        raw_songs = []

    try:
        client = _get_client()
        raw_artists = client.search(q, filter="artists", limit=10)
    except Exception as exc:
        log.warning("YouTube Music artists search error for %r: %s", q, exc)
        raw_artists = []

    try:
        client = _get_client()
        raw_albums = client.search(q, filter="albums", limit=10)
    except Exception as exc:
        log.warning("YouTube Music albums search error for %r: %s", q, exc)
        raw_albums = []

    tracks: list[Track] = []
    albums: list[Album] = []
    artists: list[Artist] = []
    seen_artists: set[str] = set()
    seen_albums: set[str] = set()

    for item in raw_artists or []:
        if not isinstance(item, dict):
            continue
        bid = item.get("browseId")
        name = item.get("artist") or item.get("name")
        if bid and name and bid not in seen_artists:
            seen_artists.add(bid)
            artists.append(
                Artist(
                    id=f"ytm:artist:{bid}",
                    name=name,
                    artworkUrl=_best_thumb(item),
                    source="youtube_music",
                    sourceUrl=f"https://music.youtube.com/channel/{bid}",
                    subtitle="YouTube Music",
                    kind="artist",
                    verified=True,
                )
            )

    for item in raw_albums or []:
        if not isinstance(item, dict):
            continue
        bid = item.get("browseId")
        title = item.get("title")
        if bid and title and bid not in seen_albums:
            seen_albums.add(bid)
            raw_type = (item.get("type") or "").lower()
            rel_type = raw_type if raw_type in ("album", "single", "ep", "compilation") else "album"
            albums.append(
                Album(
                    id=f"ytm:album:{bid}",
                    title=title,
                    artist=_clean_artists(item.get("artists")),
                    year=int(item.get("year") or 0),
                    trackCount=1,
                    artworkUrl=_best_thumb(item),
                    source="youtube_music",
                    sourceUrl=f"https://music.youtube.com/browse/{bid}",
                    releaseType=rel_type,
                )
            )

    for item in raw_songs or []:
        if not isinstance(item, dict):
            continue
        track = _item_to_track(item)
        if track:
            tracks.append(track)

        alb_dict = item.get("album") or {}
        if isinstance(alb_dict, dict):
            alb_id = alb_dict.get("id")
            alb_name = alb_dict.get("name")
            if alb_id and alb_name and alb_id not in seen_albums:
                seen_albums.add(alb_id)
                albums.append(
                    Album(
                        id=f"ytm:album:{alb_id}",
                        title=alb_name,
                        artist=_clean_artists(item.get("artists")),
                        year=int(item.get("year") or 0),
                        trackCount=1,
                        artworkUrl=_best_thumb(item),
                        source="youtube_music",
                        sourceUrl=f"https://music.youtube.com/browse/{alb_id}",
                    )
                )

        # اضافه کردن هنرمند فقط اگر جستجوی اصلی خالی بود، نام با کوئری هم‌خوانی داشت، و کاور موجود بود
        if not artists:
            for a in item.get("artists") or []:
                aid = a.get("id")
                aname = a.get("name")
                if aid and aname and aid not in seen_artists:
                    if q.lower() in aname.lower() or aname.lower() in q.lower():
                        thumb = _best_thumb(item)
                        if thumb:
                            seen_artists.add(aid)
                            artists.append(
                                Artist(
                                    id=f"ytm:artist:{aid}",
                                    name=aname,
                                    artworkUrl=thumb,
                                    source="youtube_music",
                                    sourceUrl=f"https://music.youtube.com/channel/{aid}",
                                    subtitle="YouTube Music",
                                    kind="artist",
                                    verified=True,
                                )
                            )

    return SearchResults(query=query, tracks=tracks, albums=albums, artists=artists)


def get_album(browse_id: str) -> AlbumDetail | None:
    """دریافت جزییات کامل آلبوم از YouTube Music."""
    clean_id = browse_id.removeprefix("ytm:album:").removeprefix("yt:album:")
    try:
        client = _get_client()
        alb = client.get_album(clean_id)
        if not alb:
            return None
        title = alb.get("title") or "بدون عنوان"
        artist = _clean_artists(alb.get("artists"))
        art_url = _best_thumb(alb)
        tracks: list[Track] = []
        for t in alb.get("tracks") or []:
            vid = t.get("videoId")
            credits_id = str(t.get("creditsBrowseId") or "")
            if credits_id.startswith("MPTC") and len(credits_id) == 15:
                vid = credits_id[4:]
            if not vid:
                continue
            tracks.append(
                Track(
                    id=f"ytm:track:{vid}",
                    title=t.get("title") or "بدون عنوان",
                    artist=_clean_artists(t.get("artists")) or artist,
                    album=title,
                    albumId=f"ytm:album:{clean_id}",
                    durationMs=int(t.get("duration_seconds") or 0) * 1000,
                    artworkUrl=art_url,
                    source="youtube_music",
                    sourceUrl=f"https://music.youtube.com/watch?v={vid}",
                    explicit=bool(t.get("isExplicit")),
                    trackNumber=t.get("trackNumber"),
                )
            )
        raw_type = (alb.get("type") or "").lower()
        release_type = (
            raw_type if raw_type in ("album", "single", "ep", "compilation") else "album"
        )
        return AlbumDetail(
            id=f"ytm:album:{clean_id}",
            title=title,
            artist=artist,
            year=int(alb.get("year") or 0),
            artworkUrl=art_url,
            trackCount=len(tracks),
            source="youtube_music",
            sourceUrl=f"https://music.youtube.com/browse/{clean_id}",
            durationMs=sum(t.durationMs for t in tracks),
            tracks=tracks,
            releaseType=release_type,
        )
    except Exception as exc:
        log.warning("YouTube Music get_album error for %s: %s", clean_id, exc)
        return None


def resolve_handle_to_channel_id(handle_or_url: str) -> str | None:
    """تبدیل هندل یوتیوب (مانند @Gxcciflame) به channel_id (با پیشوند UC)."""
    clean = handle_or_url.strip()
    if "/@" in clean:
        clean = "@" + clean.split("/@")[-1].split("?")[0].split("/")[0]
    elif not clean.startswith("@") and not clean.startswith("UC"):
        clean = f"@{clean}"

    url = f"https://www.youtube.com/{clean}" if clean.startswith("@") else f"https://www.youtube.com/channel/{clean}"
    try:
        proxies = {"http://": PROXY, "https://": PROXY} if PROXY else None
        with httpx.Client(timeout=8.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, proxy=PROXY) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                if m := re.search(r'itemprop="channelId"\s+content="(UC[\w-]+)"', resp.text):
                    return m.group(1)
                if m := re.search(r'youtube\.com/channel/(UC[\w-]+)', resp.text):
                    return m.group(1)
                if m := re.search(r'"channelId":"(UC[\w-]+)"', resp.text):
                    return m.group(1)
                if m := re.search(r'"browseId":"(UC[\w-]+)"', resp.text):
                    return m.group(1)
    except Exception as exc:
        log.warning("Failed to resolve handle %s via HTTP: %s", handle_or_url, exc)

    return None


def _fetch_channel_avatar(channel_id: str) -> str | None:
    """دریافت آواتارِ مربع کانال از متادیتای یوتیوب."""
    clean = channel_id.removeprefix("ytm:artist:").removeprefix("yt:artist:")
    url = f"https://www.youtube.com/channel/{clean}" if clean.startswith("UC") else f"https://www.youtube.com/@{clean.lstrip('@')}"
    try:
        with httpx.Client(
            timeout=4.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            proxy=PROXY,
        ) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                if m := re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', resp.text):
                    img = m.group(1)
                    if "ggpht.com" in img or "googleusercontent.com" in img:
                        return img
                if m := re.search(r'"avatar":\s*\{\s*"thumbnails":\s*\[\s*\{\s*"url":\s*"([^"]+)"', resp.text):
                    return m.group(1)
    except Exception as exc:
        log.debug("Failed to fetch channel avatar for %s: %s", channel_id, exc)
    return None


def get_artist(channel_id: str) -> ArtistDetail | None:
    """
    دریافت کاتالوگ جامع هنرمند از YouTube Music:
    - فهرست کامل ترک‌ها از پلی‌لیست رسمی Top Songs
    - کلیه آلبوم‌ها و تک‌آهنگ‌ها/EPها با پیمایش browseId و params مربوطه
    - ویدیوهای رسمی هنرمند
    - هنرمندان مرتبط (Related)
    - بیوگرافی و تصویر پروفایل
    """
    clean_id = channel_id.removeprefix("ytm:artist:").removeprefix("yt:artist:")
    original_handle: str | None = None
    if clean_id.startswith("@") or "/@" in clean_id:
        original_handle = "@" + clean_id.split("/@")[-1].split("?")[0].lstrip("@")
        resolved = resolve_handle_to_channel_id(clean_id)
        if resolved:
            clean_id = resolved

    try:
        client = _get_client()

        # ضبط پاسخ خام جهت استخراج آواتار مربع از microformat در صورت وجود
        raw_response: dict[str, Any] = {}
        orig_send = getattr(client, "_send_request", None)
        if callable(orig_send):
            def _captured_send(endpoint: str, body: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
                res = orig_send(endpoint, body, *args, **kwargs)
                if endpoint == "browse" and isinstance(res, dict) and body.get("browseId") == clean_id:
                    raw_response.update(res)
                return res
            client._send_request = _captured_send

        try:
            art = client.get_artist(clean_id)
        finally:
            if callable(orig_send):
                client._send_request = orig_send

        if not art:
            return None
        name = art.get("name") or "ناشناس"
        description = art.get("description")

        # ۱. بنر عریض: تامبنیل‌هایی با نسبت عرض به ارتفاع حداقل ۱.۵
        banner_url: str | None = None
        thumbs = art.get("thumbnails") or []
        wide_thumbs = [
            t for t in thumbs
            if (t.get("width") or 0) >= (t.get("height") or 0) * 1.5 and t.get("url")
        ]
        if wide_thumbs:
            banner_url = max(wide_thumbs, key=lambda t: t.get("width") or 0)["url"]

        # ۲. آواتار مربع: هرگز بنر عریض نباید به عنوان آواتار برگردد چون در قاب گرد زوم می‌شود
        artwork: str | None = None
        square_thumbs = [
            t for t in thumbs
            if t.get("url") and (
                (t.get("width") and t.get("height") and t["width"] == t["height"])
                or ("=s" in t["url"] and "=w" not in t["url"])
            )
        ]
        if square_thumbs:
            artwork = max(square_thumbs, key=lambda t: t.get("width") or 0)["url"]

        if not artwork and raw_response:
            mf_thumbs = (
                raw_response.get("microformat", {})
                .get("microformatDataRenderer", {})
                .get("thumbnail", {})
                .get("thumbnails", [])
            )
            for t in mf_thumbs or []:
                if t.get("url") and ("ggpht.com" in t["url"] or "googleusercontent.com" in t["url"]):
                    artwork = t["url"]
                    break

        if not artwork:
            artwork = _fetch_channel_avatar(clean_id)

        # ponytail: اگر بنر عریض هست ولی آواتار مربع پیدا نشد، artwork را خالی بگذار
        # تا فرانت بنر را داخل قاب گرد زوم نکند. اگر اصلاً بنر نبود، به _best_thumb فالبک بزن
        artwork = artwork or (None if banner_url else _best_thumb(art))

        # ۱. استخراج کامل ترک‌های بخش Songs (مشابه الگوی BitChord)
        top_tracks: list[Track] = []
        songs_sec = art.get("songs") or {}
        songs_playlist_id = songs_sec.get("browseId")
        if songs_playlist_id:
            try:
                pl = client.get_playlist(songs_playlist_id, limit=150)
                for t in pl.get("tracks") or []:
                    track = _item_to_track(t, default_artist=name)
                    if track:
                        track.artistId = f"ytm:artist:{clean_id}"
                        top_tracks.append(track)
            except Exception as pl_exc:
                log.warning("YouTube Music get_playlist failed for %s: %s", songs_playlist_id, pl_exc)

        # در صورت عدم دریافت یا خالی بودن پلی‌لیست، استفاده از آهنگ‌های اولیه هدر
        if not top_tracks:
            for s in songs_sec.get("results") or []:
                track = _item_to_track(s, default_artist=name)
                if track:
                    track.artistId = f"ytm:artist:{clean_id}"
                    top_tracks.append(track)

        # ۲. استخراج دیسکوگرافی با تفکیک دقیق آلبوم‌ها و تک‌آهنگ‌ها
        albums_list: list[Album] = []
        singles_list: list[Album] = []
        seen_release_ids: set[str] = set()

        def _map_release(r: dict[str, Any], default_type: str) -> Album | None:
            bid = r.get("browseId")
            title = r.get("title")
            if not bid or not title or bid in seen_release_ids:
                return None
            seen_release_ids.add(bid)
            raw_type = (r.get("type") or default_type).lower()
            rel_type = (
                raw_type
                if raw_type in ("album", "single", "ep", "compilation")
                else default_type
            )
            return Album(
                id=f"ytm:album:{bid}",
                title=title,
                artist=_clean_artists(r.get("artists")) if r.get("artists") else name,
                year=int(r.get("year") or 0),
                trackCount=1,
                artworkUrl=_best_thumb(r),
                source="youtube_music",
                sourceUrl=f"https://music.youtube.com/browse/{bid}",
                artistId=f"ytm:artist:{clean_id}",
                releaseType=rel_type,  # type: ignore[arg-type]
            )

        # آلبوم‌ها
        albums_sec = art.get("albums") or {}
        if albums_sec.get("browseId") and albums_sec.get("params"):
            try:
                full_albs = client.get_artist_albums(
                    albums_sec["browseId"], albums_sec["params"], limit=100
                )
                for a in full_albs or []:
                    mapped = _map_release(a, default_type="album")
                    if mapped:
                        albums_list.append(mapped)
            except Exception as alb_exc:
                log.warning("YouTube Music get_artist_albums failed for %s: %s", clean_id, alb_exc)

        if not albums_list:
            for a in albums_sec.get("results") or []:
                mapped = _map_release(a, default_type="album")
                if mapped:
                    albums_list.append(mapped)

        # تک‌آهنگ‌ها و EPها
        singles_sec = art.get("singles") or {}
        if singles_sec.get("browseId") and singles_sec.get("params"):
            try:
                full_singles = client.get_artist_albums(
                    singles_sec["browseId"], singles_sec["params"], limit=100
                )
                for s in full_singles or []:
                    mapped = _map_release(s, default_type="single")
                    if mapped:
                        singles_list.append(mapped)
            except Exception as single_exc:
                log.warning("YouTube Music get_artist_singles failed for %s: %s", clean_id, single_exc)

        if singles_sec.get("results"):
            for s in singles_sec.get("results") or []:
                mapped = _map_release(s, default_type="single")
                if mapped:
                    singles_list.append(mapped)

        # ۳. ویدیوهای رسمی (Music Videos)
        videos_list: list[Track] = []
        vid_sec = art.get("videos") or {}
        for v in vid_sec.get("results") or []:
            vid = v.get("videoId")
            if not vid:
                continue
            v_title = v.get("title") or "بدون عنوان"
            v_art = _best_thumb(v)
            v_artists = _clean_artists(v.get("artists")) if v.get("artists") else name
            v_views = v.get("views")
            videos_list.append(
                Track(
                    id=f"ytm:track:{vid}",
                    title=v_title,
                    artist=v_artists,
                    durationMs=0,
                    artworkUrl=v_art,
                    source="youtube_music",
                    sourceUrl=f"https://music.youtube.com/watch?v={vid}",
                    artistId=f"ytm:artist:{clean_id}",
                    views=str(v_views) if v_views else None,
                )
            )

        # ۴. پلی‌لیست‌ها و حضور در (Featured / Playlists)
        playlists_list: list[Playlist] = []
        vid_browse_id = vid_sec.get("browseId")
        if vid_browse_id:
            vid_results = vid_sec.get("results") or []
            v_art = _best_thumb(vid_results[0]) if vid_results else artwork
            playlists_list.append(
                Playlist(
                    id=f"ytm:playlist:{vid_browse_id}",
                    title="ویدیوهای رسمی",
                    owner=name,
                    trackCount=len(vid_results),
                    artworkUrl=v_art,
                    source="youtube_music",
                    sourceUrl=f"https://music.youtube.com/playlist?list={vid_browse_id}",
                )
            )

        pl_sec = art.get("playlists") or {}
        for p in pl_sec.get("results") or []:
            pid = p.get("playlistId") or p.get("browseId")
            if not pid:
                continue
            playlists_list.append(
                Playlist(
                    id=f"ytm:playlist:{pid}",
                    title=p.get("title") or "پلی‌لیست",
                    owner=p.get("author") or name,
                    trackCount=int(p.get("count") or 0) if str(p.get("count") or "").isdigit() else 0,
                    artworkUrl=_best_thumb(p),
                    source="youtube_music",
                    sourceUrl=f"https://music.youtube.com/playlist?list={pid}",
                )
            )

        # ۵. هنرمندان مرتبط (Related Artists)
        related_artists: list[Artist] = []
        related_sec = art.get("related") or {}
        for r in related_sec.get("results") or []:
            rbid = r.get("browseId")
            rtitle = r.get("title")
            if rbid and rtitle:
                related_artists.append(
                    Artist(
                        id=f"ytm:artist:{rbid}",
                        name=rtitle,
                        artworkUrl=_best_thumb(r),
                        source="youtube_music",
                        sourceUrl=f"https://music.youtube.com/channel/{rbid}",
                        subtitle=r.get("subscribers") or "YouTube Music",
                        kind="artist",
                    )
                )

        subs = art.get("subscribers") or art.get("views")
        monthly_listeners = art.get("monthlyListeners")
        subtitle = (
            f"{monthly_listeners} شنونده ماهانه"
            if monthly_listeners
            else f"{subs} دنبال‌کننده"
            if subs
            else "YouTube Music"
        )

        all_releases = albums_list + singles_list

        return ArtistDetail(
            id=f"ytm:artist:{clean_id}",
            name=name,
            artworkUrl=artwork,
            source="youtube_music",
            sourceUrl=f"https://music.youtube.com/channel/{clean_id}",
            subtitle=subtitle,
            kind="artist",
            topTracks=top_tracks,
            albums=all_releases,
            singles=singles_list,
            videos=videos_list,
            playlists=playlists_list,
            related=related_artists,
            description=description,
            handle=original_handle,
            bannerUrl=banner_url,
            subscriberCount=str(subs) if subs else None,
            monthlyListeners=str(monthly_listeners) if monthly_listeners else None,
        )
    except Exception as exc:
        log.warning("YouTube Music get_artist error for %s: %s", clean_id, exc)
        return None


def get_suggestions(query: str) -> list[str]:
    """پیشنهادهای جستجوی زنده (مشابه searchSuggestions در BitChord)."""
    q = query.strip()
    if not q:
        return []
    try:
        client = _get_client()
        return client.get_search_suggestions(q)
    except Exception:
        return []
