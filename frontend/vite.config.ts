import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // Dev: proxy /api to local FastAPI (uvicorn on 8000)
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/legacy": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
