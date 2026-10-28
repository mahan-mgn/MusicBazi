# Contributing to Music Bazi

Thanks for taking the time to contribute. This document covers the practical
bits: how to get the project running, what the test gates are, and how commits
and pull requests are expected to look.

Persian and English are both fine — issues, commit bodies, and PR descriptions
do not need to be in English.

---

## Project layout

| Path | What lives there |
|---|---|
| `src/` | React 19 + Vite + TypeScript frontend (PWA) |
| `server/app/` | FastAPI backend: catalog, resolver, streaming, downloads, lyrics, bot |
| `server/tests/` | pytest suite (runs from inside `server/`) |
| `server/bridge/` | Kotlin/JVM InnerTubeX microservice (`127.0.0.1:8765`) |
| `android/` | Capacitor Android shell + native Kotlin audio engine |
| `deploy/`, `Dockerfile*` | Deployment entry points |
| `docs/` | Longer-form documentation (mostly Persian) |

---

## Getting set up

The [README](README.md#quick-start) has the full Docker and local-development
paths. The short version:

```bash
npm ci                 # frontend deps
cd server
python -m venv .venv
.venv/Scripts/activate           # Windows
# source .venv/bin/activate      # Linux/macOS
pip install -r requirements-dev.txt
```

`requirements-dev.txt` pulls in the runtime requirements plus `pytest` and
`pytest-asyncio`. Use it rather than `requirements.txt` — the async tests do not
run without the plugin, and that mismatch is exactly what used to keep CI red.

---

## Tests

Run both gates before opening a pull request. They are the same ones CI runs.

```bash
# Frontend: type check, unit + DOM tests, production bundle
npx tsc -b
npm run test
npm run build
```

```bash
# Backend (from the server/ directory)
python -m pytest
```

Some backend tests shell out to `ffmpeg`; install it locally or they will skip
or fail. CI installs it with `apt-get install ffmpeg`.

**Please add a test with the change, not after.** A pull request that alters
resolver scoring, the streaming path, archive layout, or auth should come with
tests that would fail without the change.

---

## Commits

The repository follows [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(lyrics): add a per-song lyric source picker
fix(stream): drop the resolved URL cache entry on 403
docs(readme): document the Termux server path
chore(repo): ignore local pytest scratch directories
```

- Scope is optional but useful — it is usually the module or area, not the file.
- The body should explain **why**, not restate the diff. Persian is fine.
- Keep commits focused. If a change spans frontend and backend for one feature,
  one commit is correct; unrelated fixes belong in separate commits.

---

## Pull requests

- Branch off `main` and keep the pull request scoped to one change.
- Fill in the pull request template — the checklist is short on purpose.
- CI must be green before merge. If a check fails for a reason unrelated to your
  change, say so in the description rather than disabling the check.
- Screenshots help a great deal for UI changes.

---

## Things to be careful about

- **Never commit `.env` files, cookies, or API keys.** `.env`, `server/.env`, and
  `secrets/*` are gitignored — keep it that way. If you think you leaked a key,
  rotate it; removing the file in a later commit does not remove it from history.
- **Streaming URLs are secrets.** Signed `googlevideo.com` URLs must never be
  logged, stored in the database, or returned in error messages. There are tests
  guarding this (`test_hls_proxy.py`, `test_stream_shadow.py`) — keep them green.
- **The Docker server needs a rebuild.** Editing `server/app/*.py` does nothing to
  a running container until `docker compose build server`. The live SQLite
  database also lives inside the container volume, not in `server/data/`.
- **Offline-first is a requirement, not a nicety.** The project is built to keep
  working on a home LAN when international connectivity drops. Changes that
  assume a reachable upstream will be questioned.

---

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
