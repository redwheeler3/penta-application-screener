import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const emailPreviewSources = new Set([
  fileURLToPath(new URL("../backend/app/api/dev_previews.py", import.meta.url)),
  fileURLToPath(new URL("../backend/app/services/auth_email.py", import.meta.url)),
]);

export default defineConfig({
  plugins: [
    react(),
    {
      name: "email-preview-hmr",
      configureServer(server) {
        server.watcher.add([...emailPreviewSources]);
        server.watcher.on("change", (changedPath) => {
          if (emailPreviewSources.has(path.resolve(changedPath))) {
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

