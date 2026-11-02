import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  base: "/",
  server: { host: "0.0.0.0", port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { target: "es2019", sourcemap: false },
  test: { environment: "jsdom" },
});
