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
    port: 5174,
    proxy: {
      // 백엔드 경로 전체를 FastAPI로 위임 → same-origin 효과 (쿠키/JWT 자동 첨부)
      // /insights 는 v5 라우트와 충돌하므로 제외 (백엔드 /insights 페이지는 사용 안 함)
      '/api': { target: 'http://localhost:51749', changeOrigin: false },
      '/auth': { target: 'http://localhost:51749', changeOrigin: false },
      '/static': { target: 'http://localhost:51749', changeOrigin: false },
      '/pm-static': { target: 'http://localhost:51749', changeOrigin: false },
      '/login': { target: 'http://localhost:51749', changeOrigin: false },
      '/logout': { target: 'http://localhost:51749', changeOrigin: false },
      '/upload': { target: 'http://localhost:51749', changeOrigin: false },
      '/chat': { target: 'http://localhost:51749', changeOrigin: false },
      '/admin': { target: 'http://localhost:51749', changeOrigin: false },
      '/fund': { target: 'http://localhost:51749', changeOrigin: false },
      '/guide': { target: 'http://localhost:51749', changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
