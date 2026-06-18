import { SelectProductPage } from './pages/SelectProductPage';
import { Button, Card, Form, Input, Layout, Space, Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import { fetchCurrentUser, loginUser, logoutUser, registerUser } from './api/backendApi';
import type { CurrentUser } from './api/backendApi';

export default function App() {
  const [form] = Form.useForm<{ username: string; password: string; displayName?: string }>();
  const [currentUser, setCurrentUser] = useState<CurrentUser>();
  const [checkingSession, setCheckingSession] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');

  useEffect(() => {
    let active = true;
    fetchCurrentUser()
      .then((user) => {
        if (active) setCurrentUser(user);
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setCheckingSession(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const submitAuth = async (values: { username: string; password: string; displayName?: string }) => {
    setSubmitting(true);
    try {
      const response =
        authMode === 'login'
          ? await loginUser(values.username, values.password)
          : await registerUser(values.username, values.password, values.displayName);
      setCurrentUser(response.user);
      message.success(authMode === 'login' ? '登录成功' : '账号已创建');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '登录失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleLogout = async () => {
    await logoutUser();
    setCurrentUser(undefined);
    form.setFieldsValue({ password: '' });
    message.success('已退出登录');
  };

  if (checkingSession) {
    return (
      <Layout className="auth-layout">
        <Card className="auth-card">
          <Typography.Text type="secondary">正在恢复登录状态...</Typography.Text>
        </Card>
      </Layout>
    );
  }

  if (!currentUser) {
    return (
      <Layout className="auth-layout">
        <Card className="auth-card">
          <Space direction="vertical" size={18} className="auth-card-content">
            <div>
              <Typography.Title level={3}>Temu 选品上架工作台</Typography.Title>
            </div>
            <div className="auth-mode-switch">
              <Button type={authMode === 'login' ? 'primary' : 'default'} onClick={() => setAuthMode('login')}>
                登录
              </Button>
              <Button type={authMode === 'register' ? 'primary' : 'default'} onClick={() => setAuthMode('register')}>
                注册
              </Button>
            </div>
            <Form form={form} layout="vertical" onFinish={submitAuth}>
              <Form.Item label="用户名" name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                <Input autoComplete="username" placeholder="admin" />
              </Form.Item>
              {authMode === 'register' ? (
                <Form.Item label="显示名称" name="displayName">
                  <Input placeholder="店铺或成员名称" />
                </Form.Item>
              ) : null}
              <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
                <Input.Password autoComplete={authMode === 'login' ? 'current-password' : 'new-password'} />
              </Form.Item>
              <Button block htmlType="submit" loading={submitting} type="primary">
                {authMode === 'login' ? '登录工作台' : '创建账号并进入'}
              </Button>
            </Form>
          </Space>
        </Card>
      </Layout>
    );
  }

  return <SelectProductPage key={currentUser.id} currentUser={currentUser} onLogout={handleLogout} />;
}
