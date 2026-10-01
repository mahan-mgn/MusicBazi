import { defineRailway, project, service } from "railway/iac";

// Last resort for a per-service CaC repo. Prefer one .railway file for the
// project and drop this if you later combine services into that file.
export const partial = "MusicBazi";

export default defineRailway(() => {
  const MusicBazi = service("MusicBazi", {
    start: "/entrypoint.sh",
    healthcheck: "/api/health",
    healthcheckTimeout: 300,
    replicas: 1,
    // dockerfilePath from CaC: "Dockerfile.railway"
    // builder from CaC: "DOCKERFILE"
  });
  return project("musicbazi", {
    resources: [MusicBazi],
  });
});
