import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// BACKEND_PORT: el 8000 puede estar ocupado por otro servicio local.
const backend = `localhost:${process.env.BACKEND_PORT || 8000}`

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: `http://${backend}`,
        changeOrigin: true,
      },
      '/ws': {
        target: `ws://${backend}`,
        ws: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
  },
})
