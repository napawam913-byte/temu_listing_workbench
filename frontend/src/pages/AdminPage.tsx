import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import {
  createAdminUser,
  fetchAdminApiChannels,
  fetchAdminApiUsage,
  fetchAdminSettings,
  fetchAdminUsers,
  resetAdminUserPassword,
  updateAdminApiChannels,
  updateAdminSettings,
  updateAdminUser,
} from '../api/backendApi';
import type {
  AdminApiChannel,
  AdminApiChannelUpdateItem,
  AdminApiUsageItem,
  AdminApiUsageSummary,
  AdminSetting,
  AdminSettingsUpdateItem,
  AdminUser,
} from '../api/backendApi';

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

type ApiChannelDraft = {
  name: string;
  enabled: boolean;
  baseUrl: string;
  textModel: string;
  imageModel: string;
  apiKey: string;
  clearApiKey?: boolean;
};

const EMPTY_API_USAGE: AdminApiUsageSummary = {
  items: [],
  totalCalls: 0,
  exactCalls: 0,
  inferredCalls: 0,
};

const API_USAGE_COLORS = [
  { solid: '#2563eb', soft: '#dbeafe' },
  { solid: '#f97316', soft: '#ffedd5' },
  { solid: '#14b8a6', soft: '#ccfbf1' },
  { solid: '#8b5cf6', soft: '#ede9fe' },
  { solid: '#e11d48', soft: '#ffe4e6' },
  { solid: '#0ea5e9', soft: '#e0f2fe' },
  { solid: '#84cc16', soft: '#ecfccb' },
];
const API_USAGE_DONUT_SIZE = 196;
const API_USAGE_DONUT_CENTER = API_USAGE_DONUT_SIZE / 2;
const API_USAGE_DONUT_RADIUS = 74;
const API_USAGE_DONUT_STROKE = 18;
const API_USAGE_DONUT_CIRCUMFERENCE = 2 * Math.PI * API_USAGE_DONUT_RADIUS;
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
    title: '标题拆分',
    apiKeyKey: 'OPENAI_TITLE_SPLIT_API_KEY',
    baseUrlKey: 'OPENAI_TITLE_SPLIT_BASE_URL',
    modelKey: 'OPENAI_TITLE_SPLIT_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '把商品标题拆成 1688 采购搜索关键词',
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

function apiStageLabel(stage: string) {
  if (stage === 'visual-analysis') return '图片理解';
  if (stage === 'visual-prompt') return '提示词规划';
  if (stage === 'visual-image') return '图片生成';
  if (stage === 'recommendation') return '智能推荐';
  if (stage === 'title') return '标题生成';
  if (stage === 'title-split') return '标题拆分';
  if (stage === 'product-attribute') return '产品属性';
  return stage || '未知阶段';
}

function apiTypeLabel(apiType: string) {
  if (apiType === 'chat') return '文本/视觉理解';
  if (apiType === 'image') return '生图';
  return apiType || '未知类型';
}

function apiUsageSourceLabel(source: string, isInferred: boolean) {
  if (source === 'runtime-log') return '日志';
  if (source === 'inferred-cache') return '缓存推断';
  if (source === 'inferred-visual-task') return '任务推断';
  return isInferred ? '推断' : source || '日志';
}

function buildApiUsageDonutSegments(items: AdminApiUsageItem[], total: number) {
  if (!total) return [];
  let cursor = 0;
  const gap = items.length > 1 ? 5 : 0;
  return items.map((item, index) => {
    const rawLength = (item.callCount / total) * API_USAGE_DONUT_CIRCUMFERENCE;
    const dashLength =
      items.length > 1 && rawLength <= gap * 1.2
        ? Math.max(rawLength * 0.65, 1.4)
        : Math.max(rawLength - gap, 1.4);
    const dashOffset = -(cursor + (items.length > 1 ? gap / 2 : 0));
    const color = API_USAGE_COLORS[index % API_USAGE_COLORS.length].solid;
    const soft = API_USAGE_COLORS[index % API_USAGE_COLORS.length].soft;
    cursor += rawLength;
    return {
      model: item.model,
      callCount: item.callCount,
      color,
      soft,
      dashLength,
      dashOffset,
      percent: apiUsagePercent(item.callCount, total),
    };
  });
}

function apiUsagePercent(count: number, total: number) {
  if (!total) return 0;
  return Math.round((count / total) * 1000) / 10;
}

function apiChannelDraftsFromChannels(channels: AdminApiChannel[]) {
  return Object.fromEntries(
    channels.map((channel) => [
      channel.id,
      {
        name: channel.name,
        enabled: channel.enabled,
        baseUrl: channel.baseUrl,
        textModel: channel.textModel,
        imageModel: channel.imageModel,
        apiKey: '',
        clearApiKey: false,
      },
    ]),
  );
}

export function AdminPage() {
  const [form] = Form.useForm<UserCreateForm>();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [settings, setSettings] = useState<AdminSetting[]>([]);
  const [apiUsage, setApiUsage] = useState<AdminApiUsageSummary>(EMPTY_API_USAGE);
  const [apiChannels, setApiChannels] = useState<AdminApiChannel[]>([]);
  const [apiChannelDrafts, setApiChannelDrafts] = useState<Record<string, ApiChannelDraft>>({});
  const [settingDrafts, setSettingDrafts] = useState<Record<string, string>>({});
  const [secretEditingKeys, setSecretEditingKeys] = useState<Record<string, boolean>>({});
  const [editingAiStageKey, setEditingAiStageKey] = useState<string | null>(null);
  const [highlightedModel, setHighlightedModel] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [creatingUser, setCreatingUser] = useState(false);
  const [passwordReset, setPasswordReset] = useState<PasswordResetState>({ password: '' });

  const loadAdminData = useCallback(async () => {
    setLoading(true);
    try {
      const [nextUsers, nextSettings, nextApiUsage, nextApiChannels] = await Promise.all([
        fetchAdminUsers(),
        fetchAdminSettings(),
        fetchAdminApiUsage(),
        fetchAdminApiChannels(),
      ]);
      setUsers(nextUsers);
      setSettings(nextSettings);
      setApiUsage(nextApiUsage);
      setApiChannels(nextApiChannels.channels);
      setApiChannelDrafts(apiChannelDraftsFromChannels(nextApiChannels.channels));
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

  const refreshApiUsage = async () => {
    setLoading(true);
    try {
      setApiUsage(await fetchAdminApiUsage());
      message.success('API 调用统计已刷新');
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'API 调用统计读取失败');
    } finally {
      setLoading(false);
    }
  };

  const syncApiChannelBundle = (bundle: { channels: AdminApiChannel[] }) => {
    setApiChannels(bundle.channels);
    setApiChannelDrafts(apiChannelDraftsFromChannels(bundle.channels));
  };

  const saveApiChannels = async (options?: { silent?: boolean }) => {
    setSavingSettings(true);
    try {
      const items: AdminApiChannelUpdateItem[] = apiChannels.map((channel) => {
        const draft = apiChannelDrafts[channel.id];
        return {
          id: channel.id,
          name: draft?.name,
          enabled: draft?.enabled,
          apiKey: draft?.apiKey?.trim() || undefined,
          clearApiKey: Boolean(draft?.clearApiKey),
          baseUrl: draft?.baseUrl,
          textModel: draft?.textModel,
          imageModel: draft?.imageModel,
        };
      });
      const bundle = await updateAdminApiChannels(items);
      syncApiChannelBundle(bundle);
      if (!options?.silent) {
        message.success('API 渠道已保存');
      }
      return bundle;
    } catch (error) {
      if (!options?.silent) {
        message.error(error instanceof Error ? error.message : 'API 渠道保存失败');
      }
      throw error;
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
  const apiUsageByModel = useMemo(() => {
    const modelMap = new Map<string, AdminApiUsageItem>();
    apiUsage.items.forEach((item) => {
      const current = modelMap.get(item.model);
      if (!current) {
        modelMap.set(item.model, { ...item });
        return;
      }
      current.callCount += item.callCount;
      current.successCount += item.successCount;
      current.failedCount += item.failedCount;
      if (item.lastCalledAt && (!current.lastCalledAt || item.lastCalledAt > current.lastCalledAt)) {
        current.lastCalledAt = item.lastCalledAt;
      }
    });
    return Array.from(modelMap.values()).sort((left, right) => right.callCount - left.callCount);
  }, [apiUsage.items]);

  const apiUsageDonutSegments = useMemo(
    () => buildApiUsageDonutSegments(apiUsageByModel, apiUsage.totalCalls),
    [apiUsageByModel, apiUsage.totalCalls],
  );
  const apiUsageColorByModel = useMemo(
    () =>
      new Map(
        apiUsageByModel.map((item, index) => [
          item.model,
          API_USAGE_COLORS[index % API_USAGE_COLORS.length],
        ]),
    ),
    [apiUsageByModel],
  );
  const highlightedApiUsageItem = useMemo(
    () => (highlightedModel ? apiUsageByModel.find((item) => item.model === highlightedModel) || null : null),
    [apiUsageByModel, highlightedModel],
  );

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

  const apiUsageColumns: ColumnsType<AdminApiUsageItem> = [
    {
      title: '模型',
      dataIndex: 'model',
      render: (model: string, item) => (
        <Space direction="vertical" size={0}>
          <Typography.Text className="admin-api-usage-model-name" strong>
            <i style={{ background: apiUsageColorByModel.get(model)?.solid || '#64748b' }} />
            {model}
          </Typography.Text>
          <Typography.Text type="secondary">{item.provider}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '阶段',
      dataIndex: 'stage',
      width: 150,
      render: (stage: string) => <Tag color="blue">{apiStageLabel(stage)}</Tag>,
    },
    {
      title: '类型',
      dataIndex: 'apiType',
      width: 140,
      render: (apiType: string) => apiTypeLabel(apiType),
    },
    {
      title: '调用次数',
      dataIndex: 'callCount',
      width: 110,
      sorter: (left, right) => left.callCount - right.callCount,
      defaultSortOrder: 'descend',
      render: (count: number) => <Typography.Text strong>{count}</Typography.Text>,
    },
    {
      title: '成功/失败',
      key: 'statusCount',
      width: 120,
      render: (_, item) => `${item.successCount || 0}/${item.failedCount || 0}`,
    },
    {
      title: '来源',
      dataIndex: 'source',
      width: 120,
      render: (source: string, item) => (
        <Tag color={item.isInferred ? 'gold' : 'green'}>{apiUsageSourceLabel(source, item.isInferred)}</Tag>
      ),
    },
    {
      title: '最近调用',
      dataIndex: 'lastCalledAt',
      width: 180,
      render: (value?: string | null) => value || '暂无',
    },
  ];

  const editingStageApiKeySetting = editingAiStage ? settingsByKey.get(editingAiStage.apiKeyKey) : undefined;
  const editingStageBaseUrlSetting = editingAiStage ? settingsByKey.get(editingAiStage.baseUrlKey) : undefined;
  const editingStageModelSetting = editingAiStage ? settingsByKey.get(editingAiStage.modelKey) : undefined;
  const editingStageFallbackModelSetting =
    editingAiStage && editingAiStage.modelFallbackKey ? settingsByKey.get(editingAiStage.modelFallbackKey) : undefined;
  const commonApiKeySetting = settingsByKey.get('OPENAI_API_KEY');
  const commonBaseUrlSetting = settingsByKey.get('OPENAI_BASE_URL');
  const settingDraftValue = (key: string, setting?: AdminSetting) =>
    Object.prototype.hasOwnProperty.call(settingDrafts, key) ? settingDrafts[key] || '' : settingValue(setting);
  const editingStageApiKeyEditing = editingAiStage ? Boolean(secretEditingKeys[editingAiStage.apiKeyKey]) : false;
  const editingStageApiKeyDraft = editingAiStage ? settingDrafts[editingAiStage.apiKeyKey] ?? '' : '';
  const editingStageApiKeyDisplay = secretSettingDisplay(editingStageApiKeySetting, commonApiKeySetting);
  const editingStageBaseUrlDraft = editingAiStage ? settingDrafts[editingAiStage.baseUrlKey] ?? '' : '';
  const editingStageModelDraft = editingAiStage ? settingDrafts[editingAiStage.modelKey] ?? '' : '';
  const editingStageFallbackModelValue =
    editingAiStage && editingAiStage.modelFallbackKey
      ? settingDraftValue(editingAiStage.modelFallbackKey, editingStageFallbackModelSetting)
      : '';
  const commonBaseUrlValue = settingDraftValue('OPENAI_BASE_URL', commonBaseUrlSetting);

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
            key: 'api-usage',
            label: 'API 调用统计',
            children: (
              <div className="admin-api-usage">
                <Card
                  className="admin-api-usage-card"
                  title="模型调用总览"
                  extra={
                    <Button loading={loading} onClick={refreshApiUsage}>
                      刷新统计
                    </Button>
                  }
                  loading={loading}
                >
                  <div className="admin-api-usage-summary">
                    <div className="admin-api-usage-chart-panel">
                      <div
                        className="admin-api-usage-donut"
                        aria-label={`API 调用总数 ${apiUsage.totalCalls}`}
                      >
                        <svg
                          aria-hidden="true"
                          className="admin-api-usage-donut-svg"
                          viewBox={`0 0 ${API_USAGE_DONUT_SIZE} ${API_USAGE_DONUT_SIZE}`}
                        >
                          <circle
                            className="admin-api-usage-donut-track"
                            cx={API_USAGE_DONUT_CENTER}
                            cy={API_USAGE_DONUT_CENTER}
                            r={API_USAGE_DONUT_RADIUS}
                            strokeWidth={API_USAGE_DONUT_STROKE}
                          />
                          {apiUsageDonutSegments.map((segment, index) => {
                            const active = highlightedModel === segment.model;
                            const muted = Boolean(highlightedModel && !active);
                            return (
                              <circle
                                className={`admin-api-usage-donut-segment${active ? ' admin-api-usage-donut-segment-active' : ''}${muted ? ' admin-api-usage-donut-segment-muted' : ''}`}
                                cx={API_USAGE_DONUT_CENTER}
                                cy={API_USAGE_DONUT_CENTER}
                                key={segment.model}
                                onClick={() => setHighlightedModel(segment.model)}
                                onMouseEnter={() => setHighlightedModel(segment.model)}
                                onMouseLeave={() => setHighlightedModel(null)}
                                r={API_USAGE_DONUT_RADIUS}
                                stroke={segment.color}
                                strokeWidth={API_USAGE_DONUT_STROKE}
                                style={
                                  {
                                    '--api-donut-circumference': `${API_USAGE_DONUT_CIRCUMFERENCE}px`,
                                    '--api-donut-delay': `${index * 70}ms`,
                                    '--api-donut-length': `${segment.dashLength}px`,
                                    '--api-donut-offset': `${segment.dashOffset}px`,
                                  } as CSSProperties & Record<string, string>
                                }
                              />
                            );
                          })}
                        </svg>
                        <div className="admin-api-usage-donut-center">
                          <span>{highlightedApiUsageItem ? highlightedApiUsageItem.callCount : apiUsage.totalCalls}</span>
                          <small>
                            {highlightedApiUsageItem
                              ? `${apiUsagePercent(highlightedApiUsageItem.callCount, apiUsage.totalCalls)}% ${highlightedApiUsageItem.model}`
                              : '总调用'}
                          </small>
                        </div>
                      </div>
                      <div className="admin-api-usage-metrics">
                        <div>
                          <span>精确日志</span>
                          <strong>{apiUsage.exactCalls}</strong>
                        </div>
                        <div>
                          <span>历史推断</span>
                          <strong>{apiUsage.inferredCalls}</strong>
                        </div>
                      </div>
                    </div>
                    <div className="admin-api-usage-legend">
                      {apiUsageByModel.length ? (
                        apiUsageByModel.map((item, index) => {
                          const color = API_USAGE_COLORS[index % API_USAGE_COLORS.length];
                          const percent = apiUsagePercent(item.callCount, apiUsage.totalCalls);
                          const active = highlightedModel === item.model;
                          return (
                            <button
                              aria-pressed={active}
                              className={`admin-api-usage-legend-item${active ? ' admin-api-usage-legend-item-active' : ''}`}
                              key={item.model}
                              onBlur={() => setHighlightedModel(null)}
                              onClick={() => setHighlightedModel(item.model)}
                              onFocus={() => setHighlightedModel(item.model)}
                              onMouseEnter={() => setHighlightedModel(item.model)}
                              onMouseLeave={() => setHighlightedModel(null)}
                              style={
                                {
                                  '--api-model-color': color.solid,
                                  '--api-model-soft': color.soft,
                                  '--api-model-percent': `${percent}%`,
                                } as CSSProperties & Record<string, string>
                              }
                              type="button"
                            >
                              <i />
                              <span>
                                <b>{item.model}</b>
                                <small>{percent}%</small>
                              </span>
                              <strong>{item.callCount}</strong>
                            </button>
                          );
                        })
                      ) : (
                        <Empty description="暂无 API 调用数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                      )}
                    </div>
                  </div>
                </Card>

                <Card title="模型调用明细" className="admin-table-card" loading={loading}>
                  <Table<AdminApiUsageItem>
                    rowKey="id"
                    columns={apiUsageColumns}
                    dataSource={apiUsage.items}
                    locale={{ emptyText: '暂无 API 调用数据' }}
                    onRow={(record) => ({
                      onMouseEnter: () => setHighlightedModel(record.model),
                      onMouseLeave: () => setHighlightedModel(null),
                    })}
                    pagination={{ pageSize: 10, showSizeChanger: false }}
                    rowClassName={(record) =>
                      highlightedModel === record.model ? 'admin-api-usage-row-highlighted' : ''
                    }
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
                  items={[
                    {
                      key: 'api-channels',
                      label: '渠道管理',
                      children: (
                        <div className="admin-api-channel-tab">
                  <section className="admin-api-channel-panel">
                    <div className="admin-api-section-head">
                      <div>
                        <Typography.Text strong>渠道管理</Typography.Text>
                        <Typography.Text type="secondary">管理第三方 API 渠道，接口不稳定时可切换已启用渠道。</Typography.Text>
                      </div>
                      <Button loading={savingSettings} onClick={() => void saveApiChannels()}>
                        保存渠道
                      </Button>
                    </div>
                    <div className="admin-api-channel-grid">
                      {apiChannels.map((channel) => {
                        const draft = apiChannelDrafts[channel.id] || {
                          name: channel.name,
                          enabled: channel.enabled,
                          baseUrl: channel.baseUrl,
                          textModel: channel.textModel,
                          imageModel: channel.imageModel,
                          apiKey: '',
                        };
                        return (
                          <div className="admin-api-channel-card" key={channel.id}>
                            <div className="admin-api-channel-title">
                              <Input
                                disabled={channel.isCommon}
                                value={draft.name}
                                onChange={(event) =>
                                  setApiChannelDrafts((current) => ({
                                    ...current,
                                    [channel.id]: {
                                      ...draft,
                                      name: event.target.value,
                                    },
                                  }))
                                }
                              />
                              <Switch
                                checked={draft.enabled}
                                disabled={channel.isCommon}
                                onChange={(enabled) =>
                                  setApiChannelDrafts((current) => ({
                                    ...current,
                                    [channel.id]: {
                                      ...draft,
                                      enabled,
                                    },
                                  }))
                                }
                              />
                            </div>
                            <Typography.Text type="secondary">{channel.description}</Typography.Text>
                            <Space size={6} wrap>
                              <Tag color={draft.enabled ? 'green' : 'default'}>{draft.enabled ? '启用' : '停用'}</Tag>
                              <Tag color={channel.apiKeyConfigured && !draft.clearApiKey ? 'green' : 'gold'}>
                                {channel.apiKeyConfigured && !draft.clearApiKey ? channel.maskedApiKey || 'Key 已配置' : 'Key 待配置'}
                              </Tag>
                            </Space>
                            <div className="admin-api-channel-fields">
                              <label>
                                <span>API Key</span>
                                <Input.Password
                                  placeholder={channel.apiKeyConfigured ? '输入新 Key 才会替换' : '输入 API Key'}
                                  value={draft.apiKey}
                                  onChange={(event) =>
                                    setApiChannelDrafts((current) => ({
                                      ...current,
                                      [channel.id]: {
                                        ...draft,
                                        apiKey: event.target.value,
                                        clearApiKey: false,
                                      },
                                    }))
                                  }
                                />
                              </label>
                              <label>
                                <span>Base URL</span>
                                <Input
                                  value={draft.baseUrl}
                                  onChange={(event) =>
                                    setApiChannelDrafts((current) => ({
                                      ...current,
                                      [channel.id]: {
                                        ...draft,
                                        baseUrl: event.target.value,
                                      },
                                    }))
                                  }
                                />
                              </label>
                              <label>
                                <span>文本模型</span>
                                <Input
                                  value={draft.textModel}
                                  onChange={(event) =>
                                    setApiChannelDrafts((current) => ({
                                      ...current,
                                      [channel.id]: {
                                        ...draft,
                                        textModel: event.target.value,
                                      },
                                    }))
                                  }
                                />
                              </label>
                              <label>
                                <span>生图模型</span>
                                <Input
                                  value={draft.imageModel}
                                  onChange={(event) =>
                                    setApiChannelDrafts((current) => ({
                                      ...current,
                                      [channel.id]: {
                                        ...draft,
                                        imageModel: event.target.value,
                                      },
                                    }))
                                  }
                                />
                              </label>
                            </div>
                            <Button
                              danger
                              disabled={!channel.apiKeyConfigured && !draft.apiKey}
                              size="small"
                              onClick={() =>
                                setApiChannelDrafts((current) => ({
                                  ...current,
                                  [channel.id]: {
                                    ...draft,
                                    apiKey: '',
                                    clearApiKey: true,
                                  },
                                }))
                              }
                            >
                              清除 Key
                            </Button>
                          </div>
                        );
                      })}
                    </div>
                          </section>
                        </div>
                      ),
                    },
                    ...settingGroups.map(([category, groupSettings]) => ({
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
                              const hasModelFallback = Boolean(stage.modelFallbackKey);
                              const storedStageModelValue = settingValue(modelSetting);
                              const modelDraft = settingDraftValue(stage.modelKey, modelSetting);
                              const fallbackModelValue = stage.modelFallbackKey
                                ? settingDraftValue(stage.modelFallbackKey, fallbackSetting)
                                : '';
                              const hasStoredStageModel =
                                Boolean(storedStageModelValue) && modelSetting?.source !== 'default';
                              const hasEditedStageModel =
                                Object.prototype.hasOwnProperty.call(settingDrafts, stage.modelKey) &&
                                modelDraft !== storedStageModelValue;
                              const hasStageModel = hasModelFallback
                                ? Boolean(modelDraft) && (hasStoredStageModel || hasEditedStageModel)
                                : Boolean(modelDraft);
                              const modelValue = (hasStageModel ? modelDraft : fallbackModelValue) || '未配置';
                              const modelTagColor = hasStageModel ? 'blue' : fallbackModelValue ? 'gold' : 'default';
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
                                      <Tag color={modelTagColor}>{modelValue}</Tag>
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
                                    <Tag color={modelTagColor}>
                                      {hasStageModel ? modelValue : `模型继承 ${modelValue}`}
                                    </Tag>
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
                  }))]}
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
                placeholder={editingStageFallbackModelValue || 'gpt-5.5'}
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
                  commonBaseUrlValue
                    ? `留空继承通用 Base URL：${commonBaseUrlValue}`
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
