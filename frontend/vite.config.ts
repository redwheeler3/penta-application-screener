import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const emailPreviewDirectory = fileURLToPath(
  new URL("../backend/app/services/transactional_email", import.meta.url),
);
const emailPreviewSources = new Set([
  fileURLToPath(new URL("../backend/app/api/dev_previews.py", import.meta.url)),
]);

export default defineConfig({
  plugins: [
    react(),
    {
      name: "email-preview-hmr",
      configureServer(server) {
        server.watcher.add([...emailPreviewSources, emailPreviewDirectory]);
        server.watcher.on("change", (changedPath) => {
          const resolvedPath = path.resolve(changedPath);
          if (
            emailPreviewSources.has(resolvedPath)
            || resolvedPath.startsWith(`${emailPreviewDirectory}${path.sep}`)
          ) {
            server.ws.send({ type: "custom", event: "email-previews:changed" });
          }
        });
      },
    },
  ],
  server: {
    host: "localhost",
    port: 5173,
  },
});

