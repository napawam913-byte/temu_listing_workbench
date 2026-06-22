import { lazy, Suspense, useEffect, useState } from 'react';
import { fetchCurrentUser, loginUser, logoutUser, registerUser } from './api/backendApi';
import type { CurrentUser } from './api/backendApi';

const WorkbenchApp = lazy(() => import('./WorkbenchApp'));

type AuthValues = {
  username: string;
  password: string;
  displayName?: string;
};

export default function App() {
  const [currentUser, setCurrentUser] = useState<CurrentUser>();
  const [checkingSession, setCheckingSession] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authError, setAuthError] = useState('');
  const [notice, setNotice] = useState('');

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

  const submitAuth = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const values: AuthValues = {
      username: String(formData.get('username') || '').trim(),
      password: String(formData.get('password') || ''),
      displayName: String(formData.get('displayName') || '').trim(),
    };
    if (!values.username || !values.password) {
      setAuthError('请输入用户名和密码');
      return;
    }

    setSubmitting(true);
    setAuthError('');
    setNotice('');
    try {
      const response =
        authMode === 'login'
          ? await loginUser(values.username, values.password)
          : await registerUser(values.username, values.password, values.displayName);
      setCurrentUser(response.user);
      setNotice(authMode === 'login' ? '登录成功' : '账号已创建');
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '登录失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleLogout = async () => {
    await logoutUser();
    setCurrentUser(undefined);
    setNotice('已退出登录');
  };

  if (checkingSession) {
    return (
      <main className="auth-layout">
        <section className="auth-card auth-card-loading">
          <p className="auth-muted">正在恢复登录状态...</p>
        </section>
      </main>
    );
  }

  if (!currentUser) {
    return (
      <main className="auth-layout">
        <section className="auth-card">
          <div className="auth-card-content">
            <div className="auth-heading">
              <h1>Temu 选品上架工作台</h1>
            </div>
            <div className="auth-mode-switch" role="tablist" aria-label="登录方式">
              <button
                className={authMode === 'login' ? 'auth-mode-active' : ''}
                type="button"
                onClick={() => setAuthMode('login')}
              >
                登录
              </button>
              <button
                className={authMode === 'register' ? 'auth-mode-active' : ''}
                type="button"
                onClick={() => setAuthMode('register')}
              >
                注册
              </button>
            </div>
            <form className="auth-form" onSubmit={submitAuth}>
              <label>
                用户名
                <input autoComplete="username" name="username" placeholder="admin" />
              </label>
              {authMode === 'register' ? (
                <label>
                  显示名称
                  <input name="displayName" placeholder="店铺或成员名称" />
                </label>
              ) : null}
              <label>
                密码
                <input
                  autoComplete={authMode === 'login' ? 'current-password' : 'new-password'}
                  name="password"
                  type="password"
                />
              </label>
              {authError ? <p className="auth-error">{authError}</p> : null}
              {notice ? <p className="auth-notice">{notice}</p> : null}
              <button className="auth-submit" disabled={submitting} type="submit">
                {submitting ? '处理中...' : authMode === 'login' ? '登录工作台' : '创建账号并进入'}
              </button>
            </form>
          </div>
        </section>
      </main>
    );
  }

  return (
    <Suspense
      fallback={
        <main className="auth-layout">
          <section className="auth-card auth-card-loading">
            <p className="auth-muted">正在加载工作台...</p>
          </section>
        </main>
      }
    >
      <WorkbenchApp key={currentUser.id} currentUser={currentUser} onLogout={handleLogout} />
    </Suspense>
  );
}
