import { defineConfig } from "vite"
import solid from "vite-plugin-solid"

// The dev server proxies the gateway's routes, so `bun run dev` works against a
// running gateway (RAIJU_GATEWAY, default http://127.0.0.1:8080).
const gateway = process.env.RAIJU_GATEWAY ?? "http://127.0.0.1:8080"

export default defineConfig({
  plugins: [solid()],
  build: {
    target: "es2022",
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets",
    // one stylesheet and one script keep the embedded table small
    cssCodeSplit: false,
    sourcemap: false,
    chunkSizeWarningLimit: 600,
  },
  server: {
    proxy: {
      "/api": gateway,
      "/health": gateway,
      "/metrics": gateway,
      "/v1": gateway,
      "/ws": { target: gateway, ws: true },
    },
  },
})
