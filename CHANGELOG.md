# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

## [1.3.0] — 2026-10-28

### Added

- **Optional user accounts.** Local accounts (username plus password, hashed with
  `hashlib.scrypt` so it installs in Termux without a C extension) and optional
  Google sign-in. Sessions are HMAC-signed bearer tokens stored under
  `MUSICBAZI_DATA_DIR`, so they survive restarts and container rebuilds. With no
  accounts configured the app behaves exactly as before: everything belongs to
  the built-in `guest` account.
- **Per-user provider credentials.** Spotify, Genius, and YouTube cookies are
  stored per account instead of globally, and library entries track ownership.
  Profile photos are mirrored to server disk so they survive a connectivity
  outage.
- **Short-lived media tokens.** `<audio>`, `<img>`, and `EventSource` cannot send
  an `Authorization` header, so those routes accept a media token in the `mt`
  query parameter instead.
- **Multi-source lyrics.** A shared provider pipeline behind a registry with a
  circuit breaker, supporting LRC and TTML, with per-song source selection in Now
  Playing. Providers are selectable per user and fetch failures are reported as
  machine-readable errors instead of silently falling through.
- **Web parity for the native audio engine.** The Android DSP chain is ported to
  pure TypeScript and driven through an AudioWorklet (with a Biquad fallback):
  parametric EQ, loudness, spatial processing, crossfade, and the transition
  planner. Includes the Android-style equalizer settings UI.
- **Artwork-derived page theming**, a page cache, queue prewarm, and an audio
  pipeline diagnostics panel that reports the active output path.

### Fixed

- **CI was red on `main` and on open pull requests.** `pytest-asyncio` was
  installed in the developer's virtualenv but missing from
  `server/requirements-dev.txt`, so 156 async tests failed in CI while passing
  locally. The dependency is now declared and pinned.
- **The forced `MUSICBAZI_STREAM_V2=1` default** in `server/app/config.py`
  contradicted both the feature-flag module's documented "default OFF" contract
  and the README. Removed; enable it via `.env` or `docker-compose.yml`, which
  already set it.
- **Archive layout used the ZIP label as an artist folder.** Downloading an album
  whose label was not literally `Artist - Album` produced an `Album/…` directory
  that no music library recognises as an artist.
- **Stream read-ahead was scheduled after the yield** instead of before, so the
  next chunk was never actually prefetched before the client received the
  current one.
- **The resolved-URL cache ignored its injected clock**, so expiry was measured
  against wall time while TTL used the injected clock.
- **YouTube Music album tracks resolved to music videos.** The `creditsBrowseId`
  mapping to the clean studio track had been lost, so OMV entries played the clip
  audio (with effects and dialogue) instead of the song.

### Changed

- Repository hygiene: local pytest scratch directories, temp WAV files, and
  stray Vite bundles are now gitignored and removed; the Telegram-bot entrypoint
  files are tracked and documented.
- README rewritten: accurate badges, screenshots, a table of contents, links to
  the Persian deployment docs, and a troubleshooting section.

## [1.2.0] — 2026-10-10

### Added

- BitChord v1.8 native audio engine on Android: dual-player peer engine with
  equal-power crossfading, a zero-allocation Float32 PCM pipeline, an SVF
  parametric equalizer, spatial audio, loudness normalization, direct USB DAC
  probing, and Bluetooth codec telemetry.
- InnerTubeX stream bridge (Kotlin/JVM microservice) and Stream v2 live
  orchestration with client health monitoring, stream recovery, and HLS manifest
  rewriting.
- YouTube and YouTube Music catalog integration, including artist discography,
  channel tabs, and video browsing.
- Audio pipeline diagnostic modal, hardened Now Playing dismiss gestures, and
  configurable Docker host ports.

## [1.1.0] — 2026-10-05

### Added

- Native Android audio engine foundation: DSP chain, crossfade controller, audio
  output negotiation, and the golden audio test suite.
- Download resilience: stream fallback, job reattachment, and catalog
  `appearsOn` data.

## [1.0.0] — 2026-10-02

### Added

- Initial release: catalog aggregation (Apple Music, Deezer, Spotify), smart
  audio resolving via YouTube and SoundCloud, transcoding with ID3 tagging and
  cover art, EBU R128 loudness normalization, synchronized lyrics, offline-first
  caching for intranet outages, Telegram bot, and the Capacitor Android app.

[Unreleased]: https://github.com/mahan-mgn/MusicBazi/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/mahan-mgn/MusicBazi/compare/v1.2...v1.3.0
[1.2.0]: https://github.com/mahan-mgn/MusicBazi/compare/v1.1...v1.2
[1.1.0]: https://github.com/mahan-mgn/MusicBazi/compare/v1.0...v1.1
[1.0.0]: https://github.com/mahan-mgn/MusicBazi/releases/tag/v1.0
