import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { TanStackRouterVite } from '@tanstack/router-plugin/vite'
import path from 'node:path'

// PM v5 프론트엔드 — FastAPI :51749 백엔드 + Vite :5173 개발 서버
// 운영: FastAPI가 dist/ 정적 서빙 (base '/pm-v2/')
export default defineConfig({
  base: '/pm-v2/',
  plugins: [
    // router-plugin은 react 보다 먼저 등록해야 routeTree.gen.ts 생성됨
    TanStackRouterVite({
      routesDirectory: './src/routes',
      generatedRouteTree: './src/routeTree.gen.ts',
      autoCodeSplitting: true,
    }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 모든 /api/* 요청을 FastAPI로 위임 → same-origin 효과 (쿠키/JWT 자동 첨부)
      '/api': {
        target: 'http://localhost:51749',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
