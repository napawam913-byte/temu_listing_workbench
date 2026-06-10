import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  createAdminUser,
  fetchAdminSettings,
  fetchAdminUsers,
  resetAdminUserPassword,
  updateAdminSettings,
  updateAdminUser,
} from '../api/backendApi';
import type { AdminSetting, AdminSettingsUpdateItem, AdminUser } from '../api/backendApi';

type UserCreateForm = {
  username: string;
  password: string;
  displayName?: string;
  role: 'admin' | 'user';
  status: 'active' | 'disabled';
};

type PasswordResetState = {
  user?: AdminUser;
  password: string;
};

const SETTING_CATEGORY_ORDER = ['ai', 'visual', '1688', 'oss'];

function categoryLabel(category: string) {
  if (category === 'ai') return 'AI 配置';
  if (category === 'visual') return '生图配置';
  if (category === '1688') return '1688 API';
  if (category === 'oss') return '阿里云 OSS';
  return category;
}

function categoryDescription(category: string) {
  if (category === 'ai') return '管理 LaoZhang / OpenAI 兼容接口、文本模型和基础生图模型。';
  if (category === 'visual') return '管理母图任务、九宫格切图、图生图参考和 OSS 上传默认策略。';
  if (category === '1688') return '管理 1688 搜图 API 服务，用于后续同款或相关货源检索。';
  if (category === 'oss') return '管理阿里云 OSS 图片存储，用于导出模板中的公网图片链接。';
  return '系统运行配置。';
}

function sourceLabel(source: string) {
  if (source === 'database') return '后台配置';
  if (source === 'env') return '环境变量';
  if (source === 'default') return '默认值';
  return source;
}

export function AdminPage() {
  const [form] = Form.useForm<UserCreateForm>();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [settings, setSettings] = useState<AdminSetting[]>([]);
  const [settingDrafts, setSettingDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [creatingUser, setCreatingUser] = useState(false);
  const [passwordReset, setPasswordReset] = useState<PasswordResetState>({ password: '' });

  const loadAdminData = useCallback(async () => {
    setLoading(true);
    try {
      const [nextUsers, nextSettings] = await Promise.all([fetchAdminUsers(), fetchAdminSettings()]);
      setUsers(nextUsers);
      setSettings(nextSettings);
      setSettingDrafts(
        Object.fromEntries(nextSettings.map((setting) => [setting.key, setting.isSecret ? '' : setting.value || ''])),
      );
    } catch (error) {
      message.error(error instanceof Error ? error.message : '管理员数据读取失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAdminData();
  }, [loadAdminData]);

  const createUser = async (values: UserCreateForm) => {
    setCreatingUser(true);
    try {
      const user = await createAdminUser(values);
      setUsers((current) => [user, ...current]);
      form.resetFields();
      message.success('用户已创建');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建用户失败');
    } finally {
      setCreatingUser(false);
    }
  };

  const patchUser = async (user: AdminUser, payload: Partial<Pick<AdminUser, 'displayName' | 'role' | 'status'>>) => {
    try {
      const nextUser = await updateAdminUser(user.id, payload);
      setUsers((current) => current.map((item) => (item.id === user.id ? nextUser : item)));
      message.success('用户已更新');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '用户更新失败');
    }
  };

  const resetPassword = async () => {
    if (!passwordReset.user) return;
    if (passwordReset.password.length < 6) {
      message.warning('密码至少 6 位');
      return;
    }
    try {
      const nextUser = await resetAdminUserPassword(passwordReset.user.id, passwordReset.password);
      setUsers((current) => current.map((item) => (item.id === nextUser.id ? nextUser : item)));
      setPasswordReset({ password: '' });
      message.success('密码已重置');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '密码重置失败');
    }
  };

  const saveSettings = async () => {
    const items: AdminSettingsUpdateItem[] = [];
    settings.forEach((setting) => {
      const value = settingDrafts[setting.key] ?? '';
      if (setting.isSecret && !value) return;
      if (!setting.isSecret && value === (setting.value || '')) return;
      items.push({ key: setting.key, value });
    });

    if (items.length === 0) {
      message.info('没有需要保存的配置');
      return;
    }

    setSavingSettings(true);
    try {
      const nextSettings = await updateAdminSettings(items);
      setSettings(nextSettings);
      setSettingDrafts(
        Object.fromEntries(nextSettings.map((setting) => [setting.key, setting.isSecret ? '' : setting.value || ''])),
      );
      message.success('配置已保存');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '配置保存失败');
    } finally {
      setSavingSettings(false);
    }
  };

  const settingGroups = useMemo(() => {
    const groups = new Map<string, AdminSetting[]>();
    settings.forEach((setting) => {
      groups.set(setting.category, [...(groups.get(setting.category) || []), setting]);
    });
    return Array.from(groups.entries()).sort(
      ([left], [right]) =>
        (SETTING_CATEGORY_ORDER.indexOf(left) === -1 ? 99 : SETTING_CATEGORY_ORDER.indexOf(left)) -
        (SETTING_CATEGORY_ORDER.indexOf(right) === -1 ? 99 : SETTING_CATEGORY_ORDER.indexOf(right)),
    );
  }, [settings]);

  const userColumns: ColumnsType<AdminUser> = [
    {
      title: '用户',
      dataIndex: 'username',
      render: (_, user) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{user.displayName || user.username}</Typography.Text>
          <Typography.Text type="secondary">{user.username}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      width: 160,
      render: (_, user) => (
        <Select
          value={user.role}
          style={{ width: 120 }}
          options={[
            { value: 'admin', label: '管理员' },
            { value: 'user', label: '成员' },
          ]}
          onChange={(role) => void patchUser(user, { role })}
        />
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 160,
      render: (_, user) => (
        <Select
          value={user.status}
          style={{ width: 120 }}
          options={[
            { value: 'active', label: '启用' },
            { value: 'disabled', label: '停用' },
          ]}
          onChange={(status) => void patchUser(user, { status })}
        />
      ),
    },
    {
      title: '会话',
      dataIndex: 'activeSessionCount',
      width: 90,
      render: (count: number) => <Tag color={count > 0 ? 'blue' : 'default'}>{count || 0}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'createdAt',
      width: 180,
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, user) => (
        <Button size="small" onClick={() => setPasswordReset({ user, password: '' })}>
          重置密码
        </Button>
      ),
    },
  ];

  return (
    <div className="admin-page">
      <Tabs
        className="admin-tabs"
        items={[
          {
            key: 'users',
            label: '人员管理',
            children: (
              <div className="admin-grid">
                <Card title="新增用户" className="admin-create-card">
                  <Form
                    form={form}
                    layout="vertical"
                    initialValues={{ role: 'user', status: 'active' }}
                    onFinish={createUser}
                  >
                    <Form.Item label="用户名" name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                      <Input placeholder="例如 member01" />
                    </Form.Item>
                    <Form.Item label="显示名称" name="displayName">
                      <Input placeholder="例如 运营 A" />
                    </Form.Item>
                    <Form.Item label="初始密码" name="password" rules={[{ required: true, min: 6, message: '至少 6 位' }]}>
                      <Input.Password />
                    </Form.Item>
                    <Form.Item label="角色" name="role">
                      <Select
                        options={[
                          { value: 'user', label: '成员' },
                          { value: 'admin', label: '管理员' },
                        ]}
                      />
                    </Form.Item>
                    <Form.Item label="状态" name="status">
                      <Select
                        options={[
                          { value: 'active', label: '启用' },
                          { value: 'disabled', label: '停用' },
                        ]}
                      />
                    </Form.Item>
                    <Button block type="primary" htmlType="submit" loading={creatingUser}>
                      创建用户
                    </Button>
                  </Form>
                </Card>

                <Card title="用户列表" className="admin-table-card" loading={loading}>
                  <Table<AdminUser>
                    rowKey="id"
                    columns={userColumns}
                    dataSource={users}
                    pagination={false}
                    size="middle"
                  />
                </Card>
              </div>
            ),
          },
          {
            key: 'settings',
            label: 'API 配置',
            children: (
              <Card
                className="admin-settings-card"
                title="运行配置"
                extra={
                  <Button type="primary" loading={savingSettings} onClick={saveSettings}>
                    保存配置
                  </Button>
                }
                loading={loading}
              >
                <Tabs
                  tabPosition="left"
                  items={settingGroups.map(([category, groupSettings]) => ({
                    key: category,
                    label: categoryLabel(category),
                    children: (
                      <div className="admin-settings-list">
                        <div className="admin-setting-group-head">
                          <Typography.Text strong>{categoryLabel(category)}</Typography.Text>
                          <Typography.Text type="secondary">{categoryDescription(category)}</Typography.Text>
                        </div>
                        {groupSettings.map((setting) => (
                          <div className="admin-setting-row" key={setting.key}>
                            <div className="admin-setting-meta">
                              <Typography.Text strong>{setting.label}</Typography.Text>
                              <Typography.Text type="secondary">{setting.description}</Typography.Text>
                              <Space size={6} wrap>
                                <Tag>{setting.key}</Tag>
                                <Tag color={setting.configured ? 'green' : 'default'}>
                                  {setting.configured ? '已配置' : '未配置'}
                                </Tag>
                                <Tag color="blue">{sourceLabel(setting.source)}</Tag>
                                {setting.maskedValue ? <Tag color="gold">{setting.maskedValue}</Tag> : null}
                              </Space>
                            </div>
                            {setting.isSecret ? (
                              <Input.Password
                                placeholder="留空表示不修改密钥"
                                value={settingDrafts[setting.key] ?? ''}
                                onChange={(event) =>
                                  setSettingDrafts((current) => ({
                                    ...current,
                                    [setting.key]: event.target.value,
                                  }))
                                }
                              />
                            ) : (
                              <Input
                                placeholder="请输入配置值"
                                value={settingDrafts[setting.key] ?? ''}
                                onChange={(event) =>
                                  setSettingDrafts((current) => ({
                                    ...current,
                                    [setting.key]: event.target.value,
                                  }))
                                }
                              />
                            )}
                          </div>
                        ))}
                      </div>
                    ),
                  }))}
                />
              </Card>
            ),
          },
        ]}
      />

      <Modal
        title={`重置密码：${passwordReset.user?.username || ''}`}
        open={Boolean(passwordReset.user)}
        okText="确认重置"
        cancelText="取消"
        onOk={resetPassword}
        onCancel={() => setPasswordReset({ password: '' })}
      >
        <Input.Password
          placeholder="输入新密码，至少 6 位"
          value={passwordReset.password}
          onChange={(event) => setPasswordReset((current) => ({ ...current, password: event.target.value }))}
        />
      </Modal>
    </div>
  );
}
