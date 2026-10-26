/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],

  // Clear the terminal on each dev server start
  clearScreen: false,

  // Tauri expects a fixed port for the dev server
  server: {
    port: 1420,
    strictPort: true,
  },

  // Use relative paths so the built assets load from file:// or custom scheme
  base: './',

  build: {
    outDir: 'dist',
    // Tauri targets modern engines
    target: ['es2021', 'chrome100', 'safari15'],
    // Don't inline assets since WebKitGTK may handle them differently
    assetsInlineLimit: 0,
  },

  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
