import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// Em dev, o Vite faz proxy da API para o plugin rodando no QGIS: rode `pnpm dev` com
// FEIXE_API=http://127.0.0.1:<porta> (a porta aparece no painel de mensagens do QGIS, aba "Feixe").
const apiAlvo = process.env.FEIXE_API ?? 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  build: { outDir: path.resolve(__dirname, '../feixe/web/dist'), emptyOutDir: true, sourcemap: false },
  server: { proxy: { '/api': { target: apiAlvo, changeOrigin: false } } },
})
