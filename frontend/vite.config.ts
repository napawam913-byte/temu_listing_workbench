import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalizedId = id.replace(/\\/g, '/');
          if (normalizedId.indexOf('/node_modules/') === -1) return undefined;
          if (
            normalizedId.indexOf('/node_modules/react/') !== -1 ||
            normalizedId.indexOf('/node_modules/react-dom/') !== -1 ||
            normalizedId.indexOf('/node_modules/scheduler/') !== -1
          ) {
            return 'vendor-react';
          }
          if (
            normalizedId.indexOf('/node_modules/antd/') !== -1 ||
            normalizedId.indexOf('/node_modules/@ant-design/') !== -1 ||
            normalizedId.indexOf('/node_modules/@ant-design/icons') !== -1 ||
            normalizedId.indexOf('/node_modules/rc-') !== -1 ||
            normalizedId.indexOf('/node_modules/@rc-component/') !== -1
          ) {
            return 'vendor-antd';
          }
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
  },
});
