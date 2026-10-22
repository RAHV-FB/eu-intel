/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// BASE_PATH is set by the GitHub Pages workflow (e.g. "/eu-intel/"); "/" for local dev.
export default defineConfig({
  base: process.env.BASE_PATH || '/',
  plugins: [react()],
  build: { target: 'es2022', sourcemap: false, chunkSizeWarningLimit: 400 },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
});
