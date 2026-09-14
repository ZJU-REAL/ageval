import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

/** Exact aliases so files under apps/shared resolve this SPA's node_modules. */
function sharedPackageAliases(appRoot: string) {
  const nm = path.resolve(appRoot, "node_modules");
  const names = [
    "react",
    "react-dom",
    "react/jsx-runtime",
    "react/jsx-dev-runtime",
    "react-router-dom",
    "lucide-react",
    "clsx",
    "tailwind-merge",
    "class-variance-authority",
    "liquid-gooey",
    "react-markdown",
    "remark-gfm",
    "shiki",
    "@radix-ui/react-dropdown-menu",
    "@radix-ui/react-select",
    "@radix-ui/react-slot",
    "@radix-ui/react-tooltip",
  ];
  return names.map((name) => ({
    find: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`),
    replacement: path.resolve(nm, name),
  }));
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, rootDir, "");
  const registryTarget =
    env.VITE_REGISTRY_PROXY_TARGET || env.VITE_REGISTRY_URL || "http://127.0.0.1:8080";

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: [
        {
          find: "@ageval/shared",
          replacement: path.resolve(rootDir, "../shared"),
        },
        { find: /^@\//, replacement: `${path.resolve(rootDir, "./src")}/` },
        ...sharedPackageAliases(rootDir),
      ],
      dedupe: ["react", "react-dom"],
    },
    server: {
      fs: {
        allow: [rootDir, path.resolve(rootDir, "../shared")],
      },
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
