import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// /api is forwarded to the Python backend (heatbeat_api). Start both with ./scripts/dev.sh.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const apiTarget: string = (globalThis as any).process?.env?.HEATBEAT_API ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': { target: apiTarget, changeOrigin: true } } },
  preview: { proxy: { '/api': { target: apiTarget, changeOrigin: true } } },
});
