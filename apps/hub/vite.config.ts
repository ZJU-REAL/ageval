import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, rootDir, "");
  const registryTarget =
    env.VITE_REGISTRY_PROXY_TARGET || env.VITE_REGISTRY_URL || "http://127.0.0.1:8080";

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": path.resolve(rootDir, "./src"),
        "@ageval/shared": path.resolve(rootDir, "../shared"),
      },
    },
    server: {
      port: 5174,
      proxy: {
        // Dev: same-origin /v1 → Registry (avoids CORS during local work).
        "/v1": {
          target: registryTarget,
          changeOrigin: true,
        },
        "/health": {
          target: registryTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
    },
  };
});
