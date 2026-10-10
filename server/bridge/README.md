# Music Bazi InnerTubeX Bridge

Isolated local JVM microservice bridging YouTube audio stream extraction requests
from Music Bazi to the InnerTubeX Kotlin Multiplatform library over local HTTP.

## Architecture Boundary
- Runs as an independent process on `127.0.0.1:8765`.
- Python FastAPI interacts strictly via JSON over HTTP (`GET /health`, `POST /resolve`).
- Does not expose private session tokens, cookies, or signed URLs.

## Dependency Notice & Licensing
- This component depends on `com.github.MetrolistGroup.innertubex:innertubex-desktop:v0.7.4`,
  licensed under the GNU General Public License v3.0 (GPL-3.0).
- The InnerTubeX bridge is an isolated JVM component using the InnerTubeX dependency.
- No InnerTubeX source code was copied into Music Bazi's Python/TypeScript/Android application code.
- BitChord (https://github.com/kushagrasinghx/BitChord) was consulted strictly as an architectural reference;
  no BitChord source code was copied and it is not a runtime dependency.
- Final distribution/license compatibility should receive a dedicated license review before public binary distribution.
