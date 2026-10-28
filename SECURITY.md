# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Use GitHub's private reporting channel:
[Report a vulnerability](https://github.com/mahan-mgn/MusicBazi/security/advisories/new)

Include what you can:

- What the issue is and where it lives (file, endpoint, or component)
- Steps to reproduce against a local instance
- The impact you believe it has
- Whether you have already told anyone else

You can expect an acknowledgement within about a week. This is a
single-maintainer project, so please allow reasonable time before disclosing
publicly.

## Supported versions

Only the latest tagged release on `main` receives fixes. Older tags are kept for
reference, not patched.

## Scope notes

Music Bazi is a **self-hosted** application that proxies third-party audio. A few
things are worth knowing before you report:

- **The Guest account is open by design.** With no accounts configured, anyone who
  can reach the server sees the shared `guest` library. If you expose the app
  beyond your LAN, enable accounts or put it behind a reverse proxy with
  authentication. `README.md` → *Accounts & Sign-in* explains the trade-off.
- **Signed upstream URLs are handled as secrets.** Stream URLs from
  `googlevideo.com` are kept in memory only and never logged or persisted. If you
  find one leaking into logs, an error message, or the database, that *is* a valid
  report.
- **The app fetches from the open internet.** Catalog metadata, lyrics, and cover
  art come from third-party APIs. SSRF-style reports about those outbound calls
  are welcome, but note that outbound requests are intentional.
- **Do not report third-party services.** A weakness in YouTube, Deezer, or a
  catalog API is not a Music Bazi vulnerability — report it to them.

## For contributors

- Never commit `.env` files, cookies, tokens, or `secrets/*`. They are gitignored;
  keep it that way.
- Never log a stream URL, an auth token, or a media token.
- The repository has tests that assert these properties. If you change streaming
  or logging code, run them.
