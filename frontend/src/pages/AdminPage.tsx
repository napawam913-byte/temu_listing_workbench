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
const AI_STAGE_CONFIGS = [
  {
    title: '标题生成',
    apiKeyKey: 'OPENAI_TITLE_API_KEY',
    baseUrlKey: 'OPENAI_TITLE_BASE_URL',
    modelKey: 'OPENAI_TITLE_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '中文标题、英文标题、变种值英文翻译',
  },
  {
    title: '智能推荐',
    apiKeyKey: 'OPENAI_RECOMMENDATION_API_KEY',
    baseUrlKey: 'OPENAI_RECOMMENDATION_BASE_URL',
    modelKey: 'OPENAI_RECOMMENDATION_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '商品标题、类目、图片分析和推荐关键词',
  },
  {
    title: '产品属性填写',
    apiKeyKey: 'OPENAI_PRODUCT_ATTRIBUTE_API_KEY',
    baseUrlKey: 'OPENAI_PRODUCT_ATTRIBUTE_BASE_URL',
    modelKey: 'OPENAI_PRODUCT_ATTRIBUTE_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '导出时根据类目属性库和商品信息填写产品属性',
  },
  {
    title: '图片理解',
    apiKeyKey: 'OPENAI_VISUAL_ANALYSIS_API_KEY',
    baseUrlKey: 'OPENAI_VISUAL_ANALYSIS_BASE_URL',
    modelKey: 'OPENAI_VISUAL_ANALYSIS_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '生图前分析主体、材质、结构、风险和画风',
  },
  {
    title: '提示词规划',
    apiKeyKey: 'OPENAI_VISUAL_PROMPT_API_KEY',
    baseUrlKey: 'OPENAI_VISUAL_PROMPT_BASE_URL',
    modelKey: 'OPENAI_VISUAL_PROMPT_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '把分析结果转成九宫格或四宫格母图提示词',
  },
  {
    title: '图片生成',
    apiKeyKey: 'OPENAI_IMAGE_API_KEY',
    baseUrlKey: 'OPENAI_IMAGE_BASE_URL',
    modelKey: 'OPENAI_IMAGE_MODEL',
    description: '实际生成母图、单图精修和 SKU 适配图',
  },
];

const AI_STAGE_SETTING_KEYS = new Set(
  AI_STAGE_CONFIGS.flatMap((stage) => [stage.apiKeyKey, stage.baseUrlKey, stage.modelKey]),
);

function categoryLabel(category: string) {
  if (category === 'ai') return 'AI 配置';
  if (category === 'visual') return '生图配置';
  if (category === '1688') return '1688 API';
  if (category === 'oss') return '阿里云 OSS';
  return category;
}

function categoryDescription(category: string) {
  if (category === 'ai') return '管理 FluAPI / OpenAI 兼容接口、文本模型和基础生图模型。';
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

function settingValue(setting?: AdminSetting) {
  return setting?.value || setting?.maskedValue || '';
}

function secretSettingDisplay(setting?: AdminSetting, fallbackSetting?: AdminSetting) {
  return setting?.maskedValue || fallbackSetting?.maskedValue || '';
}

export function AdminPage() {
  const [form] = Form.useForm<UserCreateForm>();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [settings, setSettings] = useState<AdminSetting[]>([]);
  const [settingDrafts, setSettingDrafts] = useState<Record<string, string>>({});
  const [secretEditingKeys, setSecretEditingKeys] = useState<Record<string, boolean>>({});
  const [editingAiStageKey, setEditingAiStageKey] = useState<string | null>(null);
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
      setSecretEditingKeys({});
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
    const knownSettingKeys = new Set<string>();
    settings.forEach((setting) => {
      knownSettingKeys.add(setting.key);
      const value = settingDrafts[setting.key] ?? '';
      if (setting.isSecret && !value) return;
      if (!setting.isSecret && value === (setting.value || '')) return;
      items.push({ key: setting.key, value });
    });

    AI_STAGE_CONFIGS.forEach((stage) => {
      [stage.apiKeyKey, stage.baseUrlKey, stage.modelKey].forEach((key) => {
        if (knownSettingKeys.has(key)) return;
        const value = settingDrafts[key] ?? '';
        if (!value) return;
        items.push({ key, value });
      });
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
      setSecretEditingKeys({});
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

  const settingsByKey = useMemo(() => new Map(settings.map((setting) => [setting.key, setting])), [settings]);

  const editingAiStage = useMemo(
    () => AI_STAGE_CONFIGS.find((stage) => stage.modelKey === editingAiStageKey) || null,
    [editingAiStageKey],
  );

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

  const editingStageApiKeySetting = editingAiStage ? settingsByKey.get(editingAiStage.apiKeyKey) : undefined;
  const editingStageBaseUrlSetting = editingAiStage ? settingsByKey.get(editingAiStage.baseUrlKey) : undefined;
  const editingStageModelSetting = editingAiStage ? settingsByKey.get(editingAiStage.modelKey) : undefined;
  const editingStageFallbackModelSetting =
    editingAiStage && editingAiStage.modelFallbackKey ? settingsByKey.get(editingAiStage.modelFallbackKey) : undefined;
  const commonApiKeySetting = settingsByKey.get('OPENAI_API_KEY');
  const commonBaseUrlSetting = settingsByKey.get('OPENAI_BASE_URL');
  const editingStageApiKeyEditing = editingAiStage ? Boolean(secretEditingKeys[editingAiStage.apiKeyKey]) : false;
  const editingStageApiKeyDraft = editingAiStage ? settingDrafts[editingAiStage.apiKeyKey] ?? '' : '';
  const editingStageApiKeyDisplay = secretSettingDisplay(editingStageApiKeySetting, commonApiKeySetting);
  const editingStageBaseUrlDraft = editingAiStage ? settingDrafts[editingAiStage.baseUrlKey] ?? '' : '';
  const editingStageModelDraft = editingAiStage ? settingDrafts[editingAiStage.modelKey] ?? '' : '';

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
                        {category === 'ai' ? (
                          <div className="admin-model-stage-grid">
                            {AI_STAGE_CONFIGS.map((stage) => {
                              const settingMap = new Map(groupSettings.map((setting) => [setting.key, setting]));
                              const apiKeySetting = settingMap.get(stage.apiKeyKey);
                              const baseUrlSetting = settingMap.get(stage.baseUrlKey);
                              const modelSetting = settingMap.get(stage.modelKey);
                              const fallbackSetting = stage.modelFallbackKey
                                ? settingMap.get(stage.modelFallbackKey)
                                : undefined;
                              const modelDraft = settingDrafts[stage.modelKey] ?? '';
                              const modelValue = modelDraft || settingValue(modelSetting) || settingValue(fallbackSetting) || '未配置';
                              const apiKeyInherited = !apiKeySetting?.configured && !settingDrafts[stage.apiKeyKey];
                              const baseUrlInherited = !baseUrlSetting?.configured && !settingDrafts[stage.baseUrlKey];
                              return (
                                <div className="admin-model-stage-card" key={stage.modelKey}>
                                  <div className="admin-model-stage-title">
                                    <Typography.Text strong>{stage.title}</Typography.Text>
                                    <Typography.Text type="secondary">{stage.description}</Typography.Text>
                                  </div>
                                  <div className="admin-model-stage-summary">
                                    <div className="admin-model-stage-model">
                                      <span>当前模型</span>
                                      <Tag color={modelSetting?.configured || modelDraft ? 'blue' : 'default'}>{modelValue}</Tag>
                                    </div>
                                    <Button size="small" onClick={() => setEditingAiStageKey(stage.modelKey)}>
                                      编辑接口
                                    </Button>
                                  </div>
                                  <Space size={6} wrap>
                                    <Tag color={apiKeyInherited ? 'gold' : 'green'}>
                                      {apiKeyInherited ? 'Key 继承通用' : 'Key 独立配置'}
                                    </Tag>
                                    <Tag color={baseUrlInherited ? 'gold' : 'green'}>
                                      {baseUrlInherited ? 'URL 继承通用' : 'URL 独立配置'}
                                    </Tag>
                                    <Tag color={modelSetting?.configured ? 'blue' : 'default'}>{modelValue}</Tag>
                                  </Space>
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                        {(category === 'ai'
                          ? groupSettings.filter((setting) => !AI_STAGE_SETTING_KEYS.has(setting.key))
                          : groupSettings
                        ).map((setting) => {
                          const settingSecretEditing = Boolean(secretEditingKeys[setting.key]);
                          const settingSecretDraft = settingDrafts[setting.key] ?? '';
                          const settingSecretDisplay = setting.maskedValue || '';
                          return (
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
                                placeholder={settingSecretEditing ? '输入新的密钥，留空不修改' : '未配置密钥'}
                                value={settingSecretEditing ? settingSecretDraft : settingSecretDraft || settingSecretDisplay}
                                onFocus={() =>
                                  setSecretEditingKeys((current) => ({
                                    ...current,
                                    [setting.key]: true,
                                  }))
                                }
                                onBlur={() => {
                                  if (settingDrafts[setting.key]) return;
                                  setSecretEditingKeys((current) => {
                                    const next = { ...current };
                                    delete next[setting.key];
                                    return next;
                                  });
                                }}
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
                          );
                        })}
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
        title={editingAiStage ? `${editingAiStage.title}接口配置` : '接口配置'}
        open={Boolean(editingAiStage)}
        okText="保存配置"
        cancelText="关闭"
        confirmLoading={savingSettings}
        onOk={async () => {
          await saveSettings();
          setEditingAiStageKey(null);
        }}
        onCancel={() => setEditingAiStageKey(null)}
      >
        {editingAiStage ? (
          <div className="admin-stage-config-modal">
            <div className="admin-stage-config-head">
              <Typography.Text type="secondary">{editingAiStage.description}</Typography.Text>
              <Space size={6} wrap>
                <Tag color={editingStageApiKeySetting?.configured ? 'green' : 'gold'}>
                  {editingStageApiKeySetting?.configured ? 'Key 独立配置' : 'Key 继承通用'}
                </Tag>
                <Tag color={editingStageBaseUrlSetting?.configured ? 'green' : 'gold'}>
                  {editingStageBaseUrlSetting?.configured ? 'URL 独立配置' : 'URL 继承通用'}
                </Tag>
              </Space>
            </div>
            <label className="admin-stage-config-field">
              <span>模型名称</span>
              <Input
                placeholder={settingValue(editingStageFallbackModelSetting) || 'gpt-5.5'}
                value={editingStageModelDraft}
                onChange={(event) =>
                  setSettingDrafts((current) => ({
                    ...current,
                    [editingAiStage.modelKey]: event.target.value,
                  }))
                }
              />
            </label>
            <label className="admin-stage-config-field">
              <span>API Key</span>
              <Input.Password
                placeholder={editingStageApiKeyEditing ? '输入新的 API Key，留空不修改' : '未配置 API Key'}
                value={
                  editingStageApiKeyEditing
                    ? editingStageApiKeyDraft
                    : editingStageApiKeyDraft || editingStageApiKeyDisplay
                }
                onFocus={() =>
                  setSecretEditingKeys((current) => ({
                    ...current,
                    [editingAiStage.apiKeyKey]: true,
                  }))
                }
                onBlur={() => {
                  if (settingDrafts[editingAiStage.apiKeyKey]) return;
                  setSecretEditingKeys((current) => {
                    const next = { ...current };
                    delete next[editingAiStage.apiKeyKey];
                    return next;
                  });
                }}
                onChange={(event) =>
                  setSettingDrafts((current) => ({
                    ...current,
                    [editingAiStage.apiKeyKey]: event.target.value,
                  }))
                }
              />
            </label>
            <label className="admin-stage-config-field">
              <span>Base URL</span>
              <Input
                placeholder={
                  settingValue(commonBaseUrlSetting)
                    ? `留空继承通用 Base URL：${settingValue(commonBaseUrlSetting)}`
                    : '留空继承通用 Base URL'
                }
                value={editingStageBaseUrlDraft}
                onChange={(event) =>
                  setSettingDrafts((current) => ({
                    ...current,
                    [editingAiStage.baseUrlKey]: event.target.value,
                  }))
                }
              />
            </label>
          </div>
        ) : null}
      </Modal>

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
