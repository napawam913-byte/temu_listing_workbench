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
          colorPrimary: '#1677ff',
          colorInfo: '#1677ff',
          colorSuccess: '#52c41a',
          colorWarning: '#faad14',
          colorError: '#ff4d4f',
          colorText: '#1f2937',
          colorTextSecondary: '#6b7280',
          colorBgLayout: '#f5f7fa',
          colorBgContainer: '#ffffff',
          colorBorder: '#d9d9d9',
          colorBorderSecondary: '#f0f0f0',
          borderRadius: 6,
          controlHeight: 32,
          fontFamily:
            'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
        components: {
          Button: {
            borderRadius: 6,
            controlHeight: 32,
            fontWeight: 500,
            primaryShadow: 'none',
          },
          Card: {
            borderRadiusLG: 8,
            paddingLG: 16,
          },
          Drawer: {
            colorBgElevated: '#f5f7fa',
            paddingLG: 16,
          },
          Input: {
            borderRadius: 6,
            activeShadow: '0 0 0 2px rgba(22, 119, 255, 0.12)',
          },
          Select: {
            borderRadius: 6,
          },
          Table: {
            borderColor: '#f0f0f0',
            headerBg: '#fafafa',
            headerColor: '#4b5563',
            rowHoverBg: '#fafafa',
          },
          Tabs: {
            inkBarColor: '#1677ff',
            itemActiveColor: '#1677ff',
            itemSelectedColor: '#1677ff',
          },
          Tag: {
            borderRadiusSM: 4,
          },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
);
