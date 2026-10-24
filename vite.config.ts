/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// BASE_PATH is set by the GitHub Pages workflow (e.g. "/eu-intel/"); "/" for local dev.
export default defineConfig({
  base: process.env.BASE_PATH || '/',
  plugins: [
    react(),
    // The dev server injects the CSS as <style> elements; the built site loads it from files, under the CSP of
    // index.html (style-src 'self'). Only the dev server's page allows inline styles.
    {
      name: 'dev-server-inline-styles',
      apply: 'serve',
      transformIndexHtml: (html) => html.replace("style-src 'self';", "style-src 'self' 'unsafe-inline';"),
    },
  ],
  build: { target: 'es2022', sourcemap: false, chunkSizeWarningLimit: 400 },
  // the data tests read the whole built site; give them room on a loaded runner
  test: { environment: 'node', include: ['src/**/*.test.ts'], testTimeout: 30_000 },
});
