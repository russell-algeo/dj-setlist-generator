import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  // Next preserves JSX for its own compiler; component tests need to lower it.
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
      "server-only": path.resolve(__dirname, "test/server-only.ts"),
    },
  },
  test: {
    environment: "node",
  },
});
