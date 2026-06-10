import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#2563eb',
          colorInfo: '#2563eb',
          colorSuccess: '#16a34a',
          colorWarning: '#f59e0b',
          colorError: '#ef4444',
          colorText: '#0f172a',
          colorTextSecondary: '#64748b',
          colorBgLayout: '#f3f6fb',
          colorBgContainer: '#ffffff',
          colorBorder: '#d8e0ec',
          colorBorderSecondary: '#e6ebf2',
          borderRadius: 8,
          controlHeight: 34,
          fontFamily:
            'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
        components: {
          Button: {
            borderRadius: 8,
            controlHeight: 34,
            fontWeight: 600,
            primaryShadow: '0 8px 18px rgba(37, 99, 235, 0.18)',
          },
          Card: {
            borderRadiusLG: 10,
            paddingLG: 18,
          },
          Drawer: {
            colorBgElevated: '#f6f8fb',
            paddingLG: 18,
          },
          Input: {
            borderRadius: 8,
            activeShadow: '0 0 0 3px rgba(37, 99, 235, 0.12)',
          },
          Select: {
            borderRadius: 8,
          },
          Table: {
            borderColor: '#e6ebf2',
            headerBg: '#f7f9fc',
            headerColor: '#475569',
            rowHoverBg: '#f8fbff',
          },
          Tabs: {
            inkBarColor: '#2563eb',
            itemActiveColor: '#1d4ed8',
            itemSelectedColor: '#1d4ed8',
          },
          Tag: {
            borderRadiusSM: 6,
          },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
);
