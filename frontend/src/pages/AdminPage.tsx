import { LockOutlined } from '@ant-design/icons';
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties, Key } from 'react';
import {
  createAdminUser,
  deleteAdminUsers,
  deleteAiGatewayChannel,
  deleteAiGatewayCredential,
  dryRunAiGatewayRoute,
  fetchAiGatewayBundle,
  fetchAdminPromptConfigs,
  fetchAdminApiUsage,
  fetchAdminSettings,
  fetchAdminUserUsageLimit,
  fetchAdminUsers,
  restoreAdminPromptConfig,
  resetAdminUserPassword,
  resetAiGatewayCircuit,
  saveAiGatewayChannel,
  saveAiGatewayCredential,
  saveAiGatewayRoute,
  setAiGatewayCircuit,
  updateAdminSettings,
  updateAdminPromptConfig,
  updateAdminUserUsageLimit,
  updateAdminUser,
} from '../api/backendApi';
import type {
  AdminApiUsageGroup,
  AdminApiUsageFilters,
  AdminApiUsageItem,
  AdminApiUsageKeyStat,
  AdminApiUsageLog,
  AdminApiUsageSummary,
  AdminPromptConfig,
  AdminSetting,
  AdminSettingsUpdateItem,
  AdminUser,
  AdminUserUsageLimit,
  AiGatewayBundle,
  AiGatewayChannel,
  AiGatewayChannelPayload,
  AiGatewayCircuit,
  AiGatewayCredential,
  AiGatewayCredentialPayload,
  AiGatewayDryRun,
  AiGatewayRoute,
} from '../api/backendApi';

type UserCreateForm = {
  username: string;
  password: string;
  displayName?: string;
  role: 'admin' | 'user';
  status: 'active' | 'disabled';
  managerId?: string;
};

type AdminUserRow = AdminUser & {
  children?: AdminUserRow[];
  memberCount?: number;
  rowKind?: 'admin' | 'member' | 'unassigned';
};

type PasswordResetState = {
  user?: AdminUser;
  password: string;
};

type UsageLimitState = {
  user?: AdminUser;
  limit?: AdminUserUsageLimit;
  monthlyApiCallLimit: number;
  loading: boolean;
  saving: boolean;
};

type AiGatewayEditorState = {
  channel?: Partial<AiGatewayChannelPayload>;
  credential?: Partial<AiGatewayCredentialPayload>;
  route?: AiGatewayRoute;
  dryRun?: AiGatewayDryRun;
  keyManagerChannel?: AiGatewayChannel;
};

const EMPTY_API_USAGE: AdminApiUsageSummary = {
  items: [],
  totalCalls: 0,
  exactCalls: 0,
  inferredCalls: 0,
  byUser: [],
  byTeam: [],
  byChannel: [],
  byCredential: [],
  keyStats: [],
  recentLogs: [],
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
const SETTING_CATEGORY_ORDER = ['database', 'visual', '1688', 'oss'];
const DATABASE_POOL_PRESETS = {
  small_team: {
    label: '小队模式',
    description: '适合开发测试和小团队上线：min=2，max=10，timeout=3s',
    values: {
      DB_POOL_MODE: 'small_team',
      DB_POOL_MIN_SIZE: '2',
      DB_POOL_MAX_SIZE: '10',
      POSTGRES_CONNECT_TIMEOUT_SECONDS: '3',
    },
  },
  high_concurrency: {
    label: '高并发模式',
    description: '适合多人同时使用和任务较多：min=5，max=20，timeout=3s',
    values: {
      DB_POOL_MODE: 'high_concurrency',
      DB_POOL_MIN_SIZE: '5',
      DB_POOL_MAX_SIZE: '20',
      POSTGRES_CONNECT_TIMEOUT_SECONDS: '3',
    },
  },
} as const;
type DatabasePoolPresetKey = keyof typeof DATABASE_POOL_PRESETS;

function categoryLabel(category: string) {
  if (category === 'database') return '数据库连接池';
  if (category === 'visual') return '生图配置';
  if (category === '1688') return '1688 API';
  if (category === 'oss') return '?? OSS';
  return category;
}

function sourceLabel(source: string) {
  if (source === 'database') return '后台配置';
  if (source === 'env') return '环境变量';
  if (source === 'default') return '??';
  return source;
}

function settingValue(setting?: AdminSetting) {
  return setting?.value || setting?.maskedValue || '';
}

function apiStageLabel(stage: string) {
  const normalizedStage = stage.replace(/_/g, '-');
  if (normalizedStage === 'visual-analysis') return '图片理解';
  if (normalizedStage === 'visual-prompt') return '提示词规划';
  if (normalizedStage === 'visual-image') return '图片生成';
  if (normalizedStage === 'recommendation') return '智能推荐';
  if (normalizedStage === 'title') return '已停用标题生成';
  if (normalizedStage === 'title-split') return '标题拆分';
  if (normalizedStage === 'product-attribute') return '产品属性';
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

function adminUserInitial(user: AdminUser) {
  return (user.displayName || user.username || '?').trim().slice(0, 1).toUpperCase();
}

function compactAdminDate(value?: string) {
  if (!value) return '-';
  return value.slice(0, 10) || value;
}

function usageStatusColor(status?: string) {
  if (status === 'exceeded') return '#dc2626';
  if (status === 'warning') return '#f59e0b';
  if (status === 'ok') return '#16a34a';
  return '#2563eb';
}

function usagePercent(value?: number) {
  return Math.round(Math.max(0, Math.min(1, value || 0)) * 100);
}

function usageLimitLabel(limit?: number) {
  return limit && limit > 0 ? `${limit}` : '不限';
}

export function AdminPage() {
  const [form] = Form.useForm<UserCreateForm>();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [settings, setSettings] = useState<AdminSetting[]>([]);
  const [apiUsage, setApiUsage] = useState<AdminApiUsageSummary>(EMPTY_API_USAGE);
  const [apiUsageLoaded, setApiUsageLoaded] = useState(false);
  const [loadingApiUsageModels, setLoadingApiUsageModels] = useState(false);
  const [loadingApiUsageGroups, setLoadingApiUsageGroups] = useState(false);
  const [aiGateway, setAiGateway] = useState<AiGatewayBundle>({ channels: [], routes: [], circuits: [] });
  const [promptConfigs, setPromptConfigs] = useState<AdminPromptConfig[]>([]);
  const [promptDrafts, setPromptDrafts] = useState<Record<string, string>>({});
  const [savingPromptIds, setSavingPromptIds] = useState<Record<string, boolean>>({});
  const [activeApiConfigTab, setActiveApiConfigTab] = useState('prompt-configs');
  const [settingDrafts, setSettingDrafts] = useState<Record<string, string>>({});
  const [secretEditingKeys, setSecretEditingKeys] = useState<Record<string, boolean>>({});
  const [highlightedModel, setHighlightedModel] = useState<string | null>(null);
  const [apiUsageFilters, setApiUsageFilters] = useState<AdminApiUsageFilters>({ timeRange: 'all', status: '' });
  const [loading, setLoading] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [savingDatabasePoolPreset, setSavingDatabasePoolPreset] = useState<DatabasePoolPresetKey | null>(null);
  const [creatingUser, setCreatingUser] = useState(false);
  const [deletingUsers, setDeletingUsers] = useState(false);
  const [selectedUserRowKeys, setSelectedUserRowKeys] = useState<Key[]>([]);
  const [passwordReset, setPasswordReset] = useState<PasswordResetState>({ password: '' });
  const [expandedUserRowKeys, setExpandedUserRowKeys] = useState<Key[]>([]);
  const [usageLimitState, setUsageLimitState] = useState<UsageLimitState>({
    monthlyApiCallLimit: 0,
    loading: false,
    saving: false,
  });
  const [aiGatewayEditor, setAiGatewayEditor] = useState<AiGatewayEditorState>({});
  const [savingAiGateway, setSavingAiGateway] = useState(false);

  const loadAdminData = useCallback(async () => {
    setLoading(true);
    try {
      const [nextUsers, nextSettings, nextPromptConfigs, nextAiGateway] = await Promise.all([
        fetchAdminUsers(),
        fetchAdminSettings(),
        fetchAdminPromptConfigs(),
        fetchAiGatewayBundle().catch(() => ({ channels: [], routes: [], circuits: [] })),
      ]);
      setUsers(nextUsers);
      setSettings(nextSettings);
      setAiGateway(nextAiGateway);
      setPromptConfigs(nextPromptConfigs);
      setPromptDrafts({});
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

  const patchUser = async (
    user: AdminUser,
    payload: Partial<Pick<AdminUser, 'displayName' | 'role' | 'status' | 'managerId'>>,
  ) => {
    try {
      const nextUser = await updateAdminUser(user.id, payload);
      setUsers((current) => current.map((item) => (item.id === user.id ? nextUser : item)));
      message.success('用户已更新');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '用户更新失败');
    }
  };

  const batchDeleteSelectedUsers = () => {
    const userIds = selectedUserRowKeys.map(String).filter(Boolean);
    if (!userIds.length) {
      message.warning('请先选择要删除的成员');
      return;
    }
    const selectedUsers = users.filter((user) => userIds.includes(user.id));
    Modal.confirm({
      title: `确认删除 ${selectedUsers.length} 个成员？`,
      content: '删除后会清理这些成员的登录会话、团队关系、API 密钥配置和用量记录。当前登录管理员和最后一个管理员不会被允许删除。',
      okText: '删除',
      okButtonProps: { danger: true, loading: deletingUsers },
      cancelText: '取消',
      onOk: async () => {
        setDeletingUsers(true);
        try {
          const result = await deleteAdminUsers(userIds);
          const deletedIdSet = new Set(result.deletedIds);
          setUsers((current) => current.filter((user) => !deletedIdSet.has(user.id)));
          setSelectedUserRowKeys([]);
          message.success(`已删除 ${result.deletedCount} 个成员`);
        } catch (error) {
          message.error(error instanceof Error ? error.message : '成员删除失败');
          throw error;
        } finally {
          setDeletingUsers(false);
        }
      },
    });
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

  const openUsageLimit = async (user: AdminUser) => {
    setUsageLimitState({ user, monthlyApiCallLimit: 0, loading: true, saving: false });
    try {
      const limit = await fetchAdminUserUsageLimit(user.id);
      setUsageLimitState({
        user,
        limit,
        monthlyApiCallLimit: limit.monthlyApiCallLimit,
        loading: false,
        saving: false,
      });
    } catch (error) {
      setUsageLimitState({ monthlyApiCallLimit: 0, loading: false, saving: false });
      message.error(error instanceof Error ? error.message : '用量额度读取失败');
    }
  };

  const saveUsageLimit = async () => {
    const user = usageLimitState.user;
    if (!user) return;
    setUsageLimitState((current) => ({ ...current, saving: true }));
    try {
      const limit = await updateAdminUserUsageLimit(user.id, usageLimitState.monthlyApiCallLimit);
      setUsageLimitState({
        user,
        limit,
        monthlyApiCallLimit: limit.monthlyApiCallLimit,
        loading: false,
        saving: false,
      });
      const [models, groups] = await Promise.all([fetchAdminApiUsage('models'), fetchAdminApiUsage('groups')]);
      setApiUsage({
        ...EMPTY_API_USAGE,
        ...models,
        byUser: groups.byUser || [],
        byTeam: groups.byTeam || [],
        byChannel: groups.byChannel || [],
        byCredential: groups.byCredential || [],
      });
      setApiUsageLoaded(true);
      message.success('用量额度已保存');
    } catch (error) {
      setUsageLimitState((current) => ({ ...current, saving: false }));
      message.error(error instanceof Error ? error.message : '用量额度保存失败');
    }
  };

  const saveSettings = async (options?: { silent?: boolean; skipNoopMessage?: boolean }) => {
    const items: AdminSettingsUpdateItem[] = [];
    settings.forEach((setting) => {
      const value = settingDrafts[setting.key] ?? '';
      if (setting.isSecret && !value) return;
      if (!setting.isSecret && value === (setting.value || '')) return;
      items.push({ key: setting.key, value });
    });

    if (items.length === 0) {
      if (!options?.silent && !options?.skipNoopMessage) {
        message.info('没有需要保存的配置');
      }
      return false;
    }

    setSavingSettings(true);
    try {
      const nextSettings = await updateAdminSettings(items);
      setSettings(nextSettings);
      setSettingDrafts(
        Object.fromEntries(nextSettings.map((setting) => [setting.key, setting.isSecret ? '' : setting.value || ''])),
      );
      setSecretEditingKeys({});
      if (!options?.silent) {
        message.success('配置已保存');
      }
      return true;
    } catch (error) {
      if (!options?.silent) {
        message.error(error instanceof Error ? error.message : '配置保存失败');
      }
      throw error;
    } finally {
      setSavingSettings(false);
    }
  };

  const replacePromptConfig = (nextPrompt: AdminPromptConfig) => {
    setPromptConfigs((current) => current.map((prompt) => (prompt.id === nextPrompt.id ? nextPrompt : prompt)));
    setPromptDrafts((current) => {
      const next = { ...current };
      delete next[nextPrompt.id];
      return next;
    });
  };

  const savePromptConfig = async (prompt: AdminPromptConfig) => {
    const content = Object.prototype.hasOwnProperty.call(promptDrafts, prompt.id)
      ? promptDrafts[prompt.id]
      : prompt.content;
    setSavingPromptIds((current) => ({ ...current, [prompt.id]: true }));
    try {
      const nextPrompt = await updateAdminPromptConfig(prompt.id, content);
      replacePromptConfig(nextPrompt);
      message.success('提示词模板已保存到云数据库');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '提示词模板保存失败');
    } finally {
      setSavingPromptIds((current) => ({ ...current, [prompt.id]: false }));
    }
  };

  const restorePromptConfig = async (prompt: AdminPromptConfig) => {
    setSavingPromptIds((current) => ({ ...current, [prompt.id]: true }));
    try {
      const nextPrompt = await restoreAdminPromptConfig(prompt.id);
      replacePromptConfig(nextPrompt);
      message.success('已恢复默认提示词文件');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '恢复默认提示词失败');
    } finally {
      setSavingPromptIds((current) => ({ ...current, [prompt.id]: false }));
    }
  };

  const applyDatabasePoolPreset = async (presetKey: DatabasePoolPresetKey) => {
    const preset = DATABASE_POOL_PRESETS[presetKey];
    const items: AdminSettingsUpdateItem[] = Object.entries(preset.values).map(([key, value]) => ({ key, value }));
    setSavingDatabasePoolPreset(presetKey);
    try {
      const nextSettings = await updateAdminSettings(items);
      setSettings(nextSettings);
      setSettingDrafts(
        Object.fromEntries(nextSettings.map((setting) => [setting.key, setting.isSecret ? '' : setting.value || ''])),
      );
      message.success(`已应用 ${preset.label}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '数据库连接池模式保存失败');
    } finally {
      setSavingDatabasePoolPreset(null);
    }
  };

  const refreshApiUsage = async () => {
    setLoadingApiUsageModels(true);
    setLoadingApiUsageGroups(true);
    try {
      const [models, groups, filteredGroups] = await Promise.all([
        fetchAdminApiUsage('models'),
        fetchAdminApiUsage('groups'),
        fetchAdminApiUsage('groups', apiUsageFilters),
      ]);
      setApiUsage({
        ...EMPTY_API_USAGE,
        ...models,
        byUser: groups.byUser || [],
        byTeam: groups.byTeam || [],
        byChannel: groups.byChannel || [],
        byCredential: groups.byCredential || [],
        keyStats: filteredGroups.keyStats || [],
        recentLogs: filteredGroups.recentLogs || [],
      });
      setApiUsageLoaded(true);
      message.success('API 调用统计已刷新');
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'API 调用统计读取失败');
    } finally {
      setLoadingApiUsageModels(false);
      setLoadingApiUsageGroups(false);
    }
  };

  const loadApiUsageIfNeeded = async () => {
    if (apiUsageLoaded || loadingApiUsageModels || loadingApiUsageGroups) return;
    setLoadingApiUsageModels(true);
    try {
      const models = await fetchAdminApiUsage('models');
      setApiUsage((current) => ({ ...current, ...models }));
      setApiUsageLoaded(true);
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'API 调用统计读取失败');
    } finally {
      setLoadingApiUsageModels(false);
    }

    setLoadingApiUsageGroups(true);
    try {
      const [groups, filteredGroups] = await Promise.all([
        fetchAdminApiUsage('groups'),
        fetchAdminApiUsage('groups', apiUsageFilters),
      ]);
      setApiUsage((current) => ({
        ...current,
        byUser: groups.byUser || [],
        byTeam: groups.byTeam || [],
        byChannel: groups.byChannel || [],
        byCredential: groups.byCredential || [],
        keyStats: filteredGroups.keyStats || [],
        recentLogs: filteredGroups.recentLogs || [],
      }));
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'API 用量分组读取失败');
    } finally {
      setLoadingApiUsageGroups(false);
    }
  };


  const saveAllRuntimeConfig = async () => {
    setSavingSettings(true);
    try {
      await saveSettings({ silent: true, skipNoopMessage: true });
      message.success('全部运行配置已保存');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '全部运行配置保存失败');
    } finally {
      setSavingSettings(false);
    }
  };

  const refreshAiGateway = async (options?: { silent?: boolean }) => {
    try {
      const bundle = await fetchAiGatewayBundle();
      setAiGateway(bundle);
      if (!options?.silent) {
        message.success('API 中枢已刷新');
      }
      return bundle;
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'API 中枢读取失败');
      throw error;
    }
  };

  const saveAiGatewayChannelEditor = async () => {
    const draft = aiGatewayEditor.channel;
    if (!draft?.name) {
      message.warning('请填写渠道名称');
      return;
    }
    setSavingAiGateway(true);
    try {
      await saveAiGatewayChannel({
        providerType: 'openai_compatible',
        textModel: 'gpt-5.5',
        imageModel: 'gpt-image-2-1k',
        modelTemplates: {},
        capabilities: ['chat'],
        enabled: true,
        priority: 100,
        connectTimeoutSeconds: 10,
        readTimeoutSeconds: 60,
        ...draft,
      } as AiGatewayChannelPayload);
      setAiGatewayEditor({});
      await refreshAiGateway({ silent: true });
      message.success('渠道已保存');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '渠道保存失败');
    } finally {
      setSavingAiGateway(false);
    }
  };

  const saveAiGatewayCredentialEditor = async () => {
    const draft = aiGatewayEditor.credential;
    if (!draft?.channelId || !draft.name) {
      message.warning('请选择渠道并填写 Key 名称');
      return;
    }
    setSavingAiGateway(true);
    try {
      await saveAiGatewayCredential({
        enabled: true,
        priority: 100,
        weight: 1,
        maxConcurrency: 2,
        rpmLimit: 0,
        dailyLimit: 0,
        monthlyLimit: 0,
        ...draft,
      } as AiGatewayCredentialPayload);
      const bundle = await refreshAiGateway({ silent: true });
      const keyManagerChannel = aiGatewayEditor.keyManagerChannel
        ? bundle.channels.find((channel) => channel.id === aiGatewayEditor.keyManagerChannel?.id)
        : undefined;
      setAiGatewayEditor(keyManagerChannel ? { keyManagerChannel } : {});
      message.success('Key 已保存');
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Key 保存失败');
    } finally {
      setSavingAiGateway(false);
    }
  };

  const saveAiGatewayRouteEditor = async () => {
    const route = aiGatewayEditor.route;
    if (!route) return;
    setSavingAiGateway(true);
    try {
      await saveAiGatewayRoute(route.stage, {
        title: route.title,
        modelType: route.modelType,
        channelOrder: route.channelOrder,
        keySelectionPolicy: route.keySelectionPolicy,
        maxChannelAttempts: route.maxChannelAttempts,
        allowCrossChannelFallback: route.allowCrossChannelFallback,
        enabled: route.enabled,
      });
      setAiGatewayEditor({});
      await refreshAiGateway({ silent: true });
      message.success('路由策略已保存');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '路由策略保存失败');
    } finally {
      setSavingAiGateway(false);
    }
  };

  const runAiGatewayDryRun = async (stage: string) => {
    setSavingAiGateway(true);
    try {
      const dryRun = await dryRunAiGatewayRoute(stage);
      setAiGatewayEditor({ dryRun });
    } catch (error) {
      message.error(error instanceof Error ? error.message : '路由干跑失败');
    } finally {
      setSavingAiGateway(false);
    }
  };

  const openAiGatewayCircuit = async (scopeType: string, scopeId: string, label: string) => {
    Modal.confirm({
      title: `手动熔断 ${label}？`,
      content: '熔断后新的请求会跳过这个对象，直到你手动恢复或后续策略恢复。',
      okText: '确认熔断',
      cancelText: '取消',
      onOk: async () => {
        await setAiGatewayCircuit({
          scopeType,
          scopeId,
          state: 'open',
          errorMessage: '管理员手动熔断',
        });
        await refreshAiGateway({ silent: true });
      },
    });
  };

  const resetAiGatewayCircuitById = async (circuitId: string) => {
    try {
      await resetAiGatewayCircuit(circuitId);
      await refreshAiGateway({ silent: true });
      message.success('熔断状态已恢复');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '恢复失败');
    }
  };

  const settingGroups = useMemo(() => {
    const groups = new Map<string, AdminSetting[]>();
    settings.forEach((setting) => {
      if (setting.category === 'ai') return;
      groups.set(setting.category, [...(groups.get(setting.category) || []), setting]);
    });
    return Array.from(groups.entries()).sort(
      ([left], [right]) =>
        (SETTING_CATEGORY_ORDER.indexOf(left) === -1 ? 99 : SETTING_CATEGORY_ORDER.indexOf(left)) -
        (SETTING_CATEGORY_ORDER.indexOf(right) === -1 ? 99 : SETTING_CATEGORY_ORDER.indexOf(right)),
    );
  }, [settings]);

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
  const schedulerChannelState = (channelId: string) => aiGateway.scheduler?.channels?.[channelId];
  const schedulerCredentialState = (credentialId: string) => aiGateway.scheduler?.credentials?.[credentialId];
  const schedulerHealthPercent = (value?: number) => Math.round(Math.max(0, Math.min(1, value ?? 1)) * 100);
  const adminUserOptions = useMemo(
    () =>
      users
        .filter((user) => user.role === 'admin' && user.status === 'active')
        .map((user) => ({ value: user.id, label: user.displayName || user.username })),
    [users],
  );
  const apiChannelNameById = useMemo(
    () => new Map(aiGateway.channels.map((channel) => [channel.id, channel.name])),
    [aiGateway.channels],
  );
  const aiGatewayCredentialById = useMemo(() => {
    const entries = aiGateway.channels.flatMap((channel) =>
      (channel.credentials || []).map((credential) => [credential.id, { ...credential, channelName: channel.name }] as const),
    );
    return new Map(entries);
  }, [aiGateway.channels]);
  const userTableRows = useMemo<AdminUserRow[]>(() => {
    const admins = users.filter((user) => user.role === 'admin');
    const adminIds = new Set(admins.map((user) => user.id));
    const membersByAdmin = new Map<string, AdminUserRow[]>();
    const unassignedMembers: AdminUserRow[] = [];

    users
      .filter((user) => user.role !== 'admin')
      .forEach((user) => {
        const row: AdminUserRow = { ...user, rowKind: user.managerId ? 'member' : 'unassigned' };
        if (user.managerId && adminIds.has(user.managerId)) {
          membersByAdmin.set(user.managerId, [...(membersByAdmin.get(user.managerId) || []), row]);
          return;
        }
        unassignedMembers.push(row);
      });

    return [
      ...admins.map((admin) => {
        const children = membersByAdmin.get(admin.id) || [];
        return {
          ...admin,
          children: children.length ? children : undefined,
          memberCount: children.length,
          rowKind: 'admin' as const,
        };
      }),
      ...unassignedMembers,
    ];
  }, [users]);
  const expandableUserRowKeys = useMemo(
    () => userTableRows.filter((row) => row.children?.length).map((row) => row.id),
    [userTableRows],
  );
  const userTableSummary = useMemo(
    () => ({
      adminCount: users.filter((user) => user.role === 'admin').length,
      memberCount: users.filter((user) => user.role !== 'admin').length,
      unassignedCount: users.filter((user) => user.role !== 'admin' && !user.managerId).length,
    }),
    [users],
  );

  useEffect(() => {
    setExpandedUserRowKeys((current) => {
      const expandableSet = new Set(expandableUserRowKeys);
      const currentValid = current.filter((key) => expandableSet.has(String(key)));
      const currentSet = new Set(currentValid.map(String));
      const next = [...currentValid, ...expandableUserRowKeys.filter((key) => !currentSet.has(key))];
      const currentText = current.map(String).join('|');
      const nextText = next.map(String).join('|');
      return currentText === nextText ? current : next;
    });
  }, [expandableUserRowKeys]);

  const userColumns: ColumnsType<AdminUserRow> = [
    {
      title: '用户',
      dataIndex: 'username',
      width: 188,
      render: (_, user) => {
        const displayName = user.displayName || user.username;
        const fullName = user.displayName && user.displayName !== user.username ? `${user.displayName} / @${user.username}` : `@${user.username}`;
        return (
          <Tooltip title={fullName} placement="topLeft">
            <div className="admin-user-cell">
              <span className={`admin-user-avatar admin-user-avatar-${user.role}`}>{adminUserInitial(user)}</span>
              <div className="admin-user-meta">
                <Typography.Text className="admin-user-display" strong>
                  {displayName}
                </Typography.Text>
                <Typography.Text className="admin-user-username" type="secondary">
                  @{user.username}
                </Typography.Text>
              </div>
            </div>
          </Tooltip>
        );
      },
    },
    {
      title: '角色',
      dataIndex: 'role',
      width: 82,
      render: (_, user) => (
        <Select
          className="admin-user-select"
          value={user.role}
          options={[
            { value: 'admin', label: '管理员' },
            { value: 'user', label: '成员' },
          ]}
          onChange={(role) => void patchUser(user, { role })}
        />
      ),
    },
    {
      title: '??',
      dataIndex: 'status',
      width: 82,
      render: (_, user) => (
        <Select
          className="admin-user-select"
          value={user.status}
          options={[
            { value: 'active', label: '启用' },
            { value: 'disabled', label: '停用' },
          ]}
          onChange={(status) => void patchUser(user, { status })}
        />
      ),
    },
    {
      title: '归属管理员',
      dataIndex: 'managerId',
      width: 126,
      render: (_, user) =>
        user.role === 'admin' ? (
          <Space className="admin-user-manager-inline" size={6}>
            <Tag className="admin-user-manager-tag" color="blue">
              管理员团队
            </Tag>
            <Tag className="admin-user-member-count" color={user.memberCount ? 'processing' : 'default'}>
              {user.memberCount || 0} ?
            </Tag>
          </Space>
        ) : (
          <Select
            allowClear
            className="admin-user-manager-select"
            placeholder="未归属"
            value={user.managerId || undefined}
            options={adminUserOptions}
            onChange={(managerId) => void patchUser(user, { managerId: managerId || '' })}
          />
        ),
    },
    {
      title: '活跃登录',
      dataIndex: 'activeSessionCount',
      width: 76,
      align: 'center',
      render: (count: number) => (
        <Tag className="admin-session-tag" color={count > 0 ? 'blue' : 'default'}>
          {count || 0}
        </Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'createdAt',
      width: 104,
      render: (value: string) => (
        <Tooltip title={value}>
          <span className="admin-user-date">{compactAdminDate(value)}</span>
        </Tooltip>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 86,
      align: 'center',
      render: (_, user) => (
        <Space className="admin-user-actions" size={6} wrap={false}>
          <Tooltip title="重置密码">
            <Button
              aria-label="重置密码"
              className="admin-user-action-btn"
              icon={<LockOutlined />}
              size="small"
              onClick={() => setPasswordReset({ user, password: '' })}
            />
          </Tooltip>
        </Space>
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
      title: '渠道',
      dataIndex: 'channelId',
      width: 130,
      render: (channelId?: string) =>
        channelId ? (
          <Tag color="cyan">{apiChannelNameById.get(channelId) || channelId}</Tag>
        ) : (
          <Tag>未标记</Tag>
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

  const apiUsageTeamColumns: ColumnsType<AdminApiUsageGroup> = [
    {
      title: '团队',
      dataIndex: 'teamName',
      render: (_, item) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{item.teamName || '未归属团队'}</Typography.Text>
          <Typography.Text type="secondary">{item.adminName || item.adminUserId || '未绑定管理员'}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '成员数',
      dataIndex: 'userCount',
      width: 90,
      render: (count?: number) => count || 0,
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
      title: '最近调用',
      dataIndex: 'lastCalledAt',
      width: 180,
      render: (value?: string | null) => value || '暂无',
    },
  ];

  const apiUsageUserColumns: ColumnsType<AdminApiUsageGroup> = [
    {
      title: '成员',
      dataIndex: 'displayName',
      render: (_, item) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{item.displayName || item.username || item.userId || '未知成员'}</Typography.Text>
          <Typography.Text type="secondary">{item.username || item.userId || '-'}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      width: 90,
      render: (role?: string) => <Tag color={role === 'admin' ? 'blue' : 'default'}>{role === 'admin' ? '管理员' : '成员'}</Tag>,
    },
    {
      title: '归属团队',
      dataIndex: 'teamName',
      render: (_, item) => (
        <Space direction="vertical" size={0}>
          <Typography.Text>{item.teamName || '未归属团队'}</Typography.Text>
          <Typography.Text type="secondary">{item.managerName || '未绑定管理员'}</Typography.Text>
        </Space>
      ),
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
      title: '本月用量',
      key: 'monthlyUsage',
      width: 180,
      render: (_, item) => {
        const limit = item.monthlyApiCallLimit || 0;
        const used = item.monthlyCallCount || 0;
        const percent = limit > 0 ? usagePercent(item.monthlyUsageRatio) : 0;
        return (
          <div className="admin-usage-limit-cell">
            <div className="admin-usage-limit-head">
              <Typography.Text strong>{used}</Typography.Text>
              <Typography.Text type="secondary">/ {usageLimitLabel(limit)}</Typography.Text>
            </div>
            {limit > 0 ? (
              <Progress
                percent={percent}
                showInfo={false}
                size="small"
                strokeColor={usageStatusColor(item.usageStatus)}
              />
            ) : (
              <div className="admin-usage-unlimited-bar">不限额</div>
            )}
          </div>
        );
      },
    },
    {
      title: '额度',
      key: 'usageLimitAction',
      width: 86,
      render: (_, item) => {
        const user = users.find((candidate) => candidate.id === item.userId);
        return user ? (
          <Button size="small" onClick={() => void openUsageLimit(user)}>
            设置
          </Button>
        ) : (
          <Tag>系统</Tag>
        );
      },
    },
    {
      title: '成功/失败',
      key: 'statusCount',
      width: 120,
      render: (_, item) => `${item.successCount || 0}/${item.failedCount || 0}`,
    },
    {
      title: '最近调用',
      dataIndex: 'lastCalledAt',
      width: 180,
      render: (value?: string | null) => value || '暂无',
    },
  ];

  const apiUsageChannelColumns: ColumnsType<AdminApiUsageGroup> = [
    {
      title: '渠道',
      dataIndex: 'channelId',
      render: (channelId?: string) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{channelId ? apiChannelNameById.get(channelId) || channelId : '未标记渠道'}</Typography.Text>
          <Typography.Text type="secondary">{channelId || 'legacy/global'}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '使用成员',
      dataIndex: 'userCount',
      width: 100,
      render: (count?: number) => count || 0,
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
      title: '最近调用',
      dataIndex: 'lastCalledAt',
      width: 180,
      render: (value?: string | null) => value || '暂无',
    },
  ];

  const apiUsageCredentialColumns: ColumnsType<AdminApiUsageGroup> = [
    {
      title: 'API Key',
      dataIndex: 'credentialId',
      render: (credentialId: string | undefined, item) => {
        if (item.userId) {
          return (
            <Space direction="vertical" size={0}>
              <Typography.Text strong>{item.displayName || item.username || item.userId}</Typography.Text>
              <Typography.Text type="secondary">{item.username || item.userId}</Typography.Text>
            </Space>
          );
        }
        const credential = credentialId ? aiGatewayCredentialById.get(credentialId) : undefined;
        const displayName = item.credentialName || credential?.name || credentialId || '未标记 Key';
        return (
          <Space direction="vertical" size={0}>
            <Typography.Text strong>{displayName}</Typography.Text>
            <Typography.Text type="secondary">
              {credential?.maskedApiKey || credentialId || 'legacy/global'}
            </Typography.Text>
          </Space>
        );
      },
    },
    {
      title: '渠道',
      dataIndex: 'channelId',
      width: 150,
      render: (channelId: string | undefined, item) => {
        const credential = item.credentialId ? aiGatewayCredentialById.get(item.credentialId) : undefined;
        return <Tag color="cyan">{credential?.channelName || (channelId ? apiChannelNameById.get(channelId) || channelId : '未标记渠道')}</Tag>;
      },
    },
    {
      title: '使用成员',
      dataIndex: 'userCount',
      width: 100,
      render: (count?: number) => count || 0,
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
      title: '成功率',
      key: 'successRate',
      width: 110,
      render: (_, item) => {
        const total = (item.successCount || 0) + (item.failedCount || 0);
        return total ? `${Math.round(((item.successCount || 0) / total) * 100)}%` : '-';
      },
    },
    {
      title: '成功/失败',
      key: 'statusCount',
      width: 120,
      render: (_, item) => `${item.successCount || 0}/${item.failedCount || 0}`,
    },
    {
      title: '最近调用',
      dataIndex: 'lastCalledAt',
      width: 180,
      render: (value?: string | null) => value || '暂无',
    },
  ];

  const apiUsageStageOptions = useMemo(() => {
    const stages = new Set<string>();
    apiUsage.items.forEach((item) => stages.add(item.stage));
    apiUsage.keyStats.forEach((item) => stages.add(item.stage));
    apiUsage.recentLogs.forEach((item) => stages.add(item.stage));
    ['visual_analysis', 'visual_prompt', 'visual_image'].forEach((stage) => stages.add(stage));
    return Array.from(stages)
      .filter(Boolean)
      .sort()
      .map((stage) => ({ value: stage, label: apiStageLabel(stage) }));
  }, [apiUsage.items, apiUsage.keyStats, apiUsage.recentLogs]);

  const apiUsageCredentialOptions = useMemo(() => {
    const credentialMap = new Map<string, { value: string; label: string }>();
    aiGateway.channels.forEach((channel) => {
      (channel.credentials || []).forEach((credential) => {
        credentialMap.set(credential.id, { value: credential.id, label: credential.name || credential.id });
      });
    });
    [...apiUsage.byCredential, ...apiUsage.keyStats, ...apiUsage.recentLogs].forEach((item) => {
      const credentialId = item.credentialId || '';
      if (!credentialId || credentialMap.has(credentialId)) return;
      credentialMap.set(credentialId, { value: credentialId, label: item.credentialName || credentialId });
    });
    return Array.from(credentialMap.values()).sort((left, right) => left.label.localeCompare(right.label));
  }, [aiGateway.channels, apiUsage.byCredential, apiUsage.keyStats, apiUsage.recentLogs]);

  const renderApiCredentialLabel = (credentialId?: string, credentialName?: string) => {
    const credential = credentialId ? aiGatewayCredentialById.get(credentialId) : undefined;
    const displayName = credentialName || credential?.name || credentialId || '未标记 Key';
    const keyLabel = credential?.maskedApiKey || credentialId || 'legacy/global';
    return (
      <Space direction="vertical" size={0}>
        <Typography.Text strong>{displayName}</Typography.Text>
        <Typography.Text type="secondary">{keyLabel}</Typography.Text>
      </Space>
    );
  };

  const renderApiStatusTag = (status?: string) => (
    <Tag color={status === 'failed' ? 'red' : status === 'success' ? 'green' : 'default'}>
      {status === 'failed' ? '失败' : status === 'success' ? '成功' : status || '未知'}
    </Tag>
  );

  const apiUsageKeyColumns: ColumnsType<AdminApiUsageKeyStat> = [
    {
      title: '渠道',
      dataIndex: 'channelId',
      width: 150,
      render: (channelId?: string) => <Tag color="cyan">{channelId ? apiChannelNameById.get(channelId) || channelId : '未标记渠道'}</Tag>,
    },
    {
      title: 'API Key',
      dataIndex: 'credentialId',
      render: (credentialId: string | undefined, item) => renderApiCredentialLabel(credentialId, item.credentialName),
    },
    {
      title: '模型',
      dataIndex: 'model',
      width: 160,
      render: (model: string) => <Typography.Text strong>{model}</Typography.Text>,
    },
    {
      title: '阶段',
      dataIndex: 'stage',
      width: 130,
      render: (stage: string) => <Tag color="blue">{apiStageLabel(stage)}</Tag>,
    },
    {
      title: '类型',
      dataIndex: 'apiType',
      width: 120,
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
      title: '成功率',
      key: 'successRate',
      width: 100,
      render: (_, item) => {
        const total = (item.successCount || 0) + (item.failedCount || 0);
        return total ? `${Math.round(((item.successCount || 0) / total) * 100)}%` : '-';
      },
    },
    {
      title: '最近调用',
      dataIndex: 'lastCalledAt',
      width: 170,
      render: (value?: string | null) => value || '暂无',
    },
    {
      title: '最近错误',
      dataIndex: 'lastErrorMessage',
      ellipsis: true,
      render: (value?: string) => value ? <Typography.Text type="danger">{value}</Typography.Text> : <Typography.Text type="secondary">无</Typography.Text>,
    },
  ];

  const apiUsageLogColumns: ColumnsType<AdminApiUsageLog> = [
    {
      title: '时间',
      dataIndex: 'createdAt',
      width: 170,
      render: (value?: string | null) => value || '暂无',
    },
    {
      title: '渠道',
      dataIndex: 'channelId',
      width: 140,
      render: (channelId?: string) => <Tag color="cyan">{channelId ? apiChannelNameById.get(channelId) || channelId : '未标记渠道'}</Tag>,
    },
    {
      title: 'API Key',
      dataIndex: 'credentialId',
      render: (credentialId: string | undefined, item) => renderApiCredentialLabel(credentialId, item.credentialName),
    },
    {
      title: '阶段',
      dataIndex: 'stage',
      width: 130,
      render: (stage: string) => <Tag color="blue">{apiStageLabel(stage)}</Tag>,
    },
    {
      title: '模型',
      dataIndex: 'model',
      width: 150,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (status: string) => renderApiStatusTag(status),
    },
    {
      title: '任务 ID',
      dataIndex: 'relatedId',
      width: 190,
      ellipsis: true,
      render: (value?: string | null) => value || '暂无',
    },
    {
      title: '错误',
      dataIndex: 'errorMessage',
      ellipsis: true,
      render: (value?: string | null) => value ? <Typography.Text type="danger">{value}</Typography.Text> : <Typography.Text type="secondary">无</Typography.Text>,
    },
  ];

  const aiGatewayChannelOptions = useMemo(
    () => aiGateway.channels.map((channel) => ({ value: channel.id, label: channel.name })),
    [aiGateway.channels],
  );

  const aiGatewayCredentialColumns: ColumnsType<AiGatewayCredential> = [
    {
      title: 'Key',
      dataIndex: 'name',
      render: (value: string, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{value}</Typography.Text>
          <Space size={6} wrap>
            <Tag color={record.enabled ? 'green' : 'default'}>{record.enabled ? '启用' : '停用'}</Tag>
            <Tag color={record.apiKeyConfigured ? 'green' : 'gold'}>
              {record.apiKeyConfigured ? record.maskedApiKey || '已配置' : '未配置'}
            </Tag>
          </Space>
        </Space>
      ),
    },
    {
      title: '调度',
      width: 260,
      render: (_, record) => {
        const state = schedulerCredentialState(record.id);
        const isRuntimeOpen = Boolean(state?.openUntil && state.openUntil * 1000 > Date.now());
        return (
          <Space size={6} wrap>
            <Tag>优先级 {record.priority}</Tag>
            <Tag>权重 {record.weight}</Tag>
            <Tag>并发 {record.maxConcurrency || '不限'}</Tag>
            <Tag color={state?.inFlight ? 'blue' : 'default'}>运行中 {state?.inFlight || 0}</Tag>
            <Tag color={schedulerHealthPercent(state?.healthScore) < 60 ? 'gold' : 'green'}>
              健康 {schedulerHealthPercent(state?.healthScore)}%
            </Tag>
            {state?.recentTotalCount ? (
              <Tag color={state.recentFailureCount ? 'red' : 'green'}>
                失败 {state.recentFailureCount}/{state.recentTotalCount}
              </Tag>
            ) : null}
            {isRuntimeOpen ? <Tag color="red">运行熔断</Tag> : null}
          </Space>
        );
      },
    },
    {
      title: '限额',
      width: 180,
      render: (_, record) => (
        <Space size={6} wrap>
          <Tag>RPM {record.rpmLimit || '不限'}</Tag>
          <Tag>? {record.dailyLimit || '??'}</Tag>
          <Tag>? {record.monthlyLimit || '??'}</Tag>
        </Space>
      ),
    },
    {
      title: '操作',
      width: 210,
      render: (_, record) => (
        <Space size={6} wrap>
          <Button size="small" onClick={() => setAiGatewayEditor({ credential: { ...record, apiKey: '' } })}>
            编辑
          </Button>
          <Button size="small" onClick={() => void openAiGatewayCircuit('credential', record.id, record.name)}>
            熔断
          </Button>
          <Button
            danger
            size="small"
            onClick={() => {
              Modal.confirm({
                title: `?? Key ${record.name}?`,
                okText: '删除',
                okButtonProps: { danger: true },
                cancelText: '取消',
                onOk: async () => {
                  await deleteAiGatewayCredential(record.id);
                  await refreshAiGateway({ silent: true });
                },
              });
            }}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  const aiGatewayCircuitColumns: ColumnsType<AiGatewayCircuit> = [
    {
      title: '对象',
      render: (_, record) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{record.scopeType} / {record.scopeId}</Typography.Text>
          <Typography.Text type="secondary">{record.stage || '全部阶段'} · {record.model || '全部模型'}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '??',
      width: 120,
      render: (_, record) => (
        <Tag color={record.state === 'open' ? 'red' : record.state === 'half_open' ? 'gold' : 'green'}>
          {record.state === 'open' ? '熔断' : record.state === 'half_open' ? '试探' : '正常'}
        </Tag>
      ),
    },
    {
      title: '失败',
      width: 110,
      dataIndex: 'failureCount',
    },
    {
      title: '最近错误',
      dataIndex: 'lastErrorMessage',
      render: (value: string) => value || '-',
    },
    {
      title: '更新时间',
      dataIndex: 'updatedAt',
      width: 170,
    },
    {
      title: '操作',
      width: 100,
      render: (_, record) => (
        <Button size="small" onClick={() => void resetAiGatewayCircuitById(record.id)}>
          恢复
        </Button>
      ),
    },
  ];

  const activeKeyManagerChannel = useMemo(
    () =>
      aiGatewayEditor.keyManagerChannel
        ? aiGateway.channels.find((channel) => channel.id === aiGatewayEditor.keyManagerChannel?.id) ||
          aiGatewayEditor.keyManagerChannel
        : undefined,
    [aiGateway.channels, aiGatewayEditor.keyManagerChannel],
  );

  const aiGatewayTab = {
    key: 'ai-gateway',
    label: 'API 中枢',
    children: (
      <div className="admin-ai-gateway">
        <Card
          className="admin-table-card"
          title="渠道池"
          extra={
            <Space>
              <Button onClick={() => void refreshAiGateway()} loading={savingAiGateway}>
                刷新
              </Button>
              <Button
                type="primary"
                onClick={() =>
                  setAiGatewayEditor({
                    channel: {
                      name: '',
                      providerType: 'openai_compatible',
                      baseUrl: '',
                      textModel: 'gpt-5.5',
                      imageModel: 'gpt-image-2-1k',
                      modelTemplates: {},
                      capabilities: ['chat'],
                      enabled: true,
                      priority: 100,
                      connectTimeoutSeconds: 10,
                      readTimeoutSeconds: 60,
                    },
                  })
                }
              >
                新增渠道
              </Button>
            </Space>
          }
        >
          <div className="admin-ai-gateway-channel-list">
            {aiGateway.channels.length ? (
              aiGateway.channels.map((channel) => (
                <div className="admin-ai-gateway-channel" key={channel.id}>
                  <div className="admin-ai-gateway-channel-head">
                    <div>
                      <Space size={8} wrap>
                        <Typography.Text strong>{channel.name}</Typography.Text>
                        <Tag color={channel.enabled ? 'green' : 'default'}>{channel.enabled ? '启用' : '停用'}</Tag>
                        <Tag>{channel.providerType}</Tag>
                        {channel.capabilities.map((capability) => (
                          <Tag color={capability === 'image' ? 'purple' : 'blue'} key={capability}>
                            {capability}
                          </Tag>
                        ))}
                      </Space>
                      <Typography.Text className="admin-ai-gateway-url" type="secondary">
                        {channel.baseUrl || '未配置接口地址'}
                      </Typography.Text>
                    </div>
                    <Space size={6} wrap>
                      <Button size="small" onClick={() => setAiGatewayEditor({ keyManagerChannel: channel })}>
                        管理 Key
                      </Button>
                      <Button size="small" onClick={() => setAiGatewayEditor({ channel })}>
                        编辑
                      </Button>
                      <Button size="small" onClick={() => void openAiGatewayCircuit('channel', channel.id, channel.name)}>
                        熔断
                      </Button>
                      <Button
                        danger
                        size="small"
                        onClick={() => {
                          Modal.confirm({
                            title: `删除渠道 ${channel.name}？`,
                            content: '删除渠道会同时删除它下面的 Key 配置。',
                            okText: '删除',
                            okButtonProps: { danger: true },
                            cancelText: '取消',
                            onOk: async () => {
                              await deleteAiGatewayChannel(channel.id);
                              await refreshAiGateway({ silent: true });
                            },
                          });
                        }}
                      >
                        删除
                      </Button>
                    </Space>
                  </div>
                  <Space size={6} wrap>
                    <Tag>优先级 {channel.priority}</Tag>
                    <Tag>连接超时 {channel.connectTimeoutSeconds}s</Tag>
                    <Tag>读取超时 {channel.readTimeoutSeconds}s</Tag>
                    <Tag>阶段模型 {Object.keys(channel.modelTemplates || {}).length}</Tag>
                  </Space>
                  <div className="admin-ai-gateway-key-summary">
                    <span>Key {channel.credentials.length}</span>
                    <span>可用 {channel.credentials.filter((credential) => credential.enabled && credential.apiKeyConfigured).length}</span>
                    <span>运行中 {schedulerChannelState(channel.id)?.inFlight || 0}</span>
                    <span>健康 {schedulerHealthPercent(schedulerChannelState(channel.id)?.healthScore)}%</span>
                    <span>
                      总并发{' '}
                      {channel.credentials.reduce(
                        (total, credential) =>
                          credential.enabled && credential.apiKeyConfigured
                            ? total + credential.maxConcurrency
                            : total,
                        0,
                      )}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <Empty description="还没有渠道，先新增一个 OpenAI 兼容渠道" />
            )}
          </div>
        </Card>

        <Card className="admin-table-card" title="业务路由">
          <Table<AiGatewayRoute>
            rowKey="stage"
            dataSource={aiGateway.routes}
            pagination={false}
            size="middle"
            columns={[
              {
                title: '业务阶段',
                render: (_, route) => (
                  <Space direction="vertical" size={2}>
                    <Typography.Text strong>{route.title}</Typography.Text>
                    <Typography.Text type="secondary">{route.stage}</Typography.Text>
                  </Space>
                ),
              },
              {
                title: '类型',
                width: 90,
                render: (_, route) => <Tag color={route.modelType === 'image' ? 'purple' : 'blue'}>{route.modelType}</Tag>,
              },
              {
                title: '候选渠道',
                render: (_, route) =>
                  route.channelOrder.length ? (
                    <Space size={6} wrap>
                      {route.channelOrder.map((channelId) => (
                        <Tag key={channelId}>{aiGatewayChannelOptions.find((item) => item.value === channelId)?.label || channelId}</Tag>
                      ))}
                    </Space>
                  ) : (
                    <Typography.Text type="secondary">按渠道优先级自动选择</Typography.Text>
                  ),
              },
              {
                title: '策略',
                width: 190,
                render: (_, route) => (
                  <Space size={6} wrap>
                    <Tag>{route.keySelectionPolicy}</Tag>
                    <Tag>?? {route.maxChannelAttempts}</Tag>
                  </Space>
                ),
              },
              {
                title: '操作',
                width: 170,
                render: (_, route) => (
                  <Space size={6}>
                    <Button size="small" onClick={() => setAiGatewayEditor({ route })}>
                      编辑
                    </Button>
                    <Button size="small" loading={savingAiGateway} onClick={() => void runAiGatewayDryRun(route.stage)}>
                      干跑
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        </Card>

        <Card className="admin-table-card" title="熔断状态">
          <Table<AiGatewayCircuit>
            rowKey="id"
            columns={aiGatewayCircuitColumns}
            dataSource={aiGateway.circuits}
            locale={{ emptyText: '暂无熔断记录' }}
            pagination={{ pageSize: 8, showSizeChanger: false }}
            size="middle"
          />
        </Card>
      </div>
    ),
  };

  const settingDraftValue = (key: string, setting?: AdminSetting) =>
    Object.prototype.hasOwnProperty.call(settingDrafts, key) ? settingDrafts[key] || '' : settingValue(setting);
  const promptConfigTab = {
    key: 'prompt-configs',
    label: '提示词配置',
    children: (
      <div className="admin-prompt-config-tab">
        <div className="admin-setting-group-head">
          <Typography.Text strong>提示词配置</Typography.Text>
          <Typography.Text type="secondary">查看各个 AI 阶段的输入、输出和实际提示词模板</Typography.Text>
        </div>
        {promptConfigs.length ? (
          <div className="admin-prompt-config-grid">
            {promptConfigs.map((prompt) => (
              <div className="admin-prompt-config-card" key={prompt.id}>
                <div className="admin-prompt-config-card-head">
                  <div>
                    <Typography.Text strong>{prompt.title}</Typography.Text>
                    <Typography.Text type="secondary">{prompt.description}</Typography.Text>
                  </div>
                  <Space size={6} wrap>
                    <Tag color="blue">{prompt.modelKey}</Tag>
                    <Tag color={prompt.overridden ? 'gold' : 'green'}>
                      {prompt.overridden ? '云端覆盖' : '默认文件'}
                    </Tag>
                  </Space>
                </div>
                <div className="admin-prompt-flow-row">
                  <div>
                    <span>输入</span>
                    <Typography.Text>{prompt.inputFrom}</Typography.Text>
                  </div>
                  <div>
                    <span>输出</span>
                    <Typography.Text>{prompt.outputTo}</Typography.Text>
                  </div>
                </div>
                <Space size={6} wrap>
                  {prompt.variables.map((variable) => (
                    <Tag key={variable}>{variable}</Tag>
                  ))}
                </Space>
                <Typography.Text className="admin-prompt-source" type="secondary">
                  {prompt.source}
                </Typography.Text>
                <Input.TextArea
                  className="admin-prompt-template"
                  value={Object.prototype.hasOwnProperty.call(promptDrafts, prompt.id) ? promptDrafts[prompt.id] : prompt.content}
                  onChange={(event) =>
                    setPromptDrafts((current) => ({
                      ...current,
                      [prompt.id]: event.target.value,
                    }))
                  }
                  autoSize={{ minRows: 8, maxRows: 18 }}
                />
                <Space size={8} wrap>
                  <Button
                    type="primary"
                    size="small"
                    loading={Boolean(savingPromptIds[prompt.id])}
                    onClick={() => void savePromptConfig(prompt)}
                  >
                    保存到云数据库
                  </Button>
                  <Button
                    size="small"
                    disabled={!prompt.overridden && !Object.prototype.hasOwnProperty.call(promptDrafts, prompt.id)}
                    onClick={() => {
                      if (Object.prototype.hasOwnProperty.call(promptDrafts, prompt.id)) {
                        setPromptDrafts((current) => {
                          const next = { ...current };
                          delete next[prompt.id];
                          return next;
                        });
                        return;
                      }
                      void restorePromptConfig(prompt);
                    }}
                  >
                    撤销编辑
                  </Button>
                  <Button
                    size="small"
                    danger
                    loading={Boolean(savingPromptIds[prompt.id])}
                    disabled={!prompt.overridden}
                    onClick={() => void restorePromptConfig(prompt)}
                  >
                    恢复默认文件
                  </Button>
                </Space>
              </div>
            ))}
          </div>
        ) : (
          <Empty description="暂无提示词配置" />
        )}
      </div>
    ),
  };

  return (
    <div className="admin-page">
      <Tabs
        className="admin-tabs"
        onChange={(key) => {
          if (key === 'api-usage') {
            void loadApiUsageIfNeeded();
          }
        }}
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
                    <Form.Item label="归属管理员" name="managerId">
                      <Select
                        allowClear
                        options={adminUserOptions}
                        placeholder="默认归属当前管理员"
                      />
                    </Form.Item>
                    <Form.Item label="??" name="status">
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
                  <Table<AdminUserRow>
                    rowKey="id"
                    className="admin-user-table"
                    columns={userColumns}
                    dataSource={userTableRows}
                    rowSelection={{
                      columnWidth: 34,
                      selectedRowKeys: selectedUserRowKeys,
                      onChange: (keys) => setSelectedUserRowKeys([...keys]),
                    }}
                    expandable={{
                      columnWidth: 30,
                      expandedRowKeys: expandedUserRowKeys,
                      indentSize: 18,
                      onExpandedRowsChange: (keys) => setExpandedUserRowKeys([...keys]),
                    }}
                    pagination={false}
                    rowClassName={(user) =>
                      [
                        'admin-user-table-row',
                        user.rowKind === 'admin' ? 'admin-user-table-row-admin' : '',
                        user.rowKind === 'member' ? 'admin-user-table-row-member' : '',
                        user.rowKind === 'unassigned' ? 'admin-user-table-row-unassigned' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')
                    }
                    size="small"
                    title={() => (
                      <div className="admin-user-table-summary">
                        <Space className="admin-user-summary-tags" size={10} wrap>
                          <span>管理员 {userTableSummary.adminCount}</span>
                          <span>成员 {userTableSummary.memberCount}</span>
                          {userTableSummary.unassignedCount ? <span>未归属 {userTableSummary.unassignedCount}</span> : null}
                          {selectedUserRowKeys.length ? <span>?? {selectedUserRowKeys.length}</span> : null}
                        </Space>
                        <Button
                          danger
                          size="small"
                          disabled={!selectedUserRowKeys.length}
                          loading={deletingUsers}
                          onClick={batchDeleteSelectedUsers}
                        >
                          批量删除
                        </Button>
                      </div>
                    )}
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
                    <Button loading={loadingApiUsageModels || loadingApiUsageGroups} onClick={refreshApiUsage}>
                      刷新统计
                    </Button>
                  }
                  loading={loadingApiUsageModels}
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

                <Card title="渠道 Key 调用统计" className="admin-table-card admin-api-usage-key-card" loading={loadingApiUsageGroups}>
                  <div className="admin-api-usage-filterbar">
                    <Select
                      aria-label="时间范围"
                      options={[
                        { value: 'all', label: '全部时间' },
                        { value: '1h', label: '最近 1 小时' },
                        { value: '24h', label: '最近 24 小时' },
                        { value: '7d', label: '最近 7 天' },
                      ]}
                      value={apiUsageFilters.timeRange || 'all'}
                      onChange={(timeRange) => setApiUsageFilters((current) => ({ ...current, timeRange }))}
                    />
                    <Select
                      allowClear
                      aria-label="渠道"
                      options={aiGatewayChannelOptions}
                      placeholder="全部渠道"
                      value={apiUsageFilters.channelId || undefined}
                      onChange={(channelId) => setApiUsageFilters((current) => ({ ...current, channelId }))}
                    />
                    <Select
                      allowClear
                      aria-label="API Key"
                      options={apiUsageCredentialOptions}
                      placeholder="全部 Key"
                      value={apiUsageFilters.credentialId || undefined}
                      onChange={(credentialId) => setApiUsageFilters((current) => ({ ...current, credentialId }))}
                    />
                    <Select
                      allowClear
                      aria-label="阶段"
                      options={apiUsageStageOptions}
                      placeholder="全部阶段"
                      value={apiUsageFilters.stage || undefined}
                      onChange={(stage) => setApiUsageFilters((current) => ({ ...current, stage }))}
                    />
                    <Select
                      aria-label="状态"
                      options={[
                        { value: '', label: '全部状态' },
                        { value: 'success', label: '成功' },
                        { value: 'failed', label: '失败' },
                      ]}
                      value={apiUsageFilters.status || ''}
                      onChange={(status) => setApiUsageFilters((current) => ({ ...current, status: status as AdminApiUsageFilters['status'] }))}
                    />
                    <Button loading={loadingApiUsageGroups} onClick={refreshApiUsage} type="primary">
                      应用筛选
                    </Button>
                  </div>
                  <Table<AdminApiUsageKeyStat>
                    rowKey="id"
                    columns={apiUsageKeyColumns}
                    dataSource={apiUsage.keyStats}
                    locale={{ emptyText: '暂无渠道 Key 调用数据' }}
                    pagination={{ pageSize: 8, showSizeChanger: false }}
                    scroll={{ x: 1200 }}
                    size="middle"
                  />
                </Card>

                <Card title="最近调用日志" className="admin-table-card" loading={loadingApiUsageGroups}>
                  <Table<AdminApiUsageLog>
                    rowKey="id"
                    columns={apiUsageLogColumns}
                    dataSource={apiUsage.recentLogs}
                    locale={{ emptyText: '暂无最近调用日志' }}
                    pagination={{ pageSize: 10, showSizeChanger: false }}
                    scroll={{ x: 1180 }}
                    size="middle"
                  />
                </Card>
                <Card title="模型调用明细" className="admin-table-card" loading={loadingApiUsageModels}>
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

                <Card title="团队与成员用量" className="admin-table-card admin-api-usage-group-card" loading={loadingApiUsageGroups}>
                  <Tabs
                    size="small"
                    items={[
                      {
                        key: 'teams',
                        label: '管理员团队',
                        children: (
                          <Table<AdminApiUsageGroup>
                            rowKey={(record) => record.teamId || record.adminUserId || 'unassigned'}
                            columns={apiUsageTeamColumns}
                            dataSource={apiUsage.byTeam}
                            locale={{ emptyText: '暂无团队用量数据' }}
                            pagination={{ pageSize: 8, showSizeChanger: false }}
                            size="middle"
                          />
                        ),
                      },
                      {
                        key: 'users',
                        label: '成员用量',
                        children: (
                          <Table<AdminApiUsageGroup>
                            rowKey={(record) => record.userId || 'unknown-user'}
                            columns={apiUsageUserColumns}
                            dataSource={apiUsage.byUser}
                            locale={{ emptyText: '暂无成员用量数据' }}
                            pagination={{ pageSize: 8, showSizeChanger: false }}
                            size="middle"
                          />
                        ),
                      },
                      {
                        key: 'channels',
                        label: '渠道用量',
                        children: (
                          <Table<AdminApiUsageGroup>
                            rowKey={(record) => record.channelId || 'unmarked-channel'}
                            columns={apiUsageChannelColumns}
                            dataSource={apiUsage.byChannel}
                            locale={{ emptyText: '暂无渠道用量数据' }}
                            pagination={{ pageSize: 8, showSizeChanger: false }}
                            size="middle"
                          />
                        ),
                      },
                      {
                        key: 'credentials',
                        label: 'Key 用量',
                        children: (
                          <Table<AdminApiUsageGroup>
                            rowKey={(record) =>
                              record.userId
                                ? `${record.credentialId || 'unmarked-credential'}:${record.userId}`
                                : record.credentialId || 'unmarked-credential'
                            }
                            columns={apiUsageCredentialColumns}
                            dataSource={apiUsage.byCredential}
                            locale={{ emptyText: '暂无 Key 用量数据' }}
                            pagination={{ pageSize: 8, showSizeChanger: false }}
                            size="middle"
                          />
                        ),
                      },
                    ]}
                  />
                </Card>
              </div>
            ),
          },
          aiGatewayTab,
          {
            key: 'settings',
            label: 'API 配置',
            children: (
              <Card
                className="admin-settings-card"
                title="运行配置"
                extra={
                  <Button type="primary" loading={savingSettings} onClick={() => void saveAllRuntimeConfig()}>
                    保存全部配置
                  </Button>
                }
                loading={loading}
              >
                <Tabs
                  activeKey={activeApiConfigTab}
                  tabPosition="left"
                  onChange={setActiveApiConfigTab}
                  items={[
                    promptConfigTab,
                    ...settingGroups.map(([category, groupSettings]) => ({
                    key: category,
                    label: categoryLabel(category),
                    children: (
                      <div className="admin-settings-list">
                        {category === 'database' ? (
                          <div className="admin-db-pool-presets">
                            {Object.entries(DATABASE_POOL_PRESETS).map(([presetKey, preset]) => {
                              const typedPresetKey = presetKey as DatabasePoolPresetKey;
                              const active = settingDrafts.DB_POOL_MODE === preset.values.DB_POOL_MODE;
                              return (
                                <Button
                                  key={presetKey}
                                  type={active ? 'primary' : 'default'}
                                  loading={savingDatabasePoolPreset === typedPresetKey}
                                  onClick={() => void applyDatabasePoolPreset(typedPresetKey)}
                                >
                                  <span>{preset.label}</span>
                                  <small>{preset.description}</small>
                                </Button>
                              );
                            })}
                          </div>
                        ) : null}
                        {groupSettings.map((setting) => {
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
                    })),
                  ]}
                />
              </Card>
            ),
          },
        ]}
      />

      <Modal
        title={aiGatewayEditor.channel?.id ? '编辑渠道' : '新增渠道'}
        open={Boolean(aiGatewayEditor.channel)}
        okText="保存渠道"
        cancelText="关闭"
        confirmLoading={savingAiGateway}
        onOk={() => void saveAiGatewayChannelEditor()}
        onCancel={() => setAiGatewayEditor({})}
        width={760}
      >
        {aiGatewayEditor.channel ? (
          <div className="admin-ai-gateway-form">
            <label>
              <span>渠道名称</span>
              <Input
                value={aiGatewayEditor.channel.name}
                onChange={(event) =>
                  setAiGatewayEditor((current) => ({
                    ...current,
                    channel: { ...current.channel, name: event.target.value },
                  }))
                }
              />
            </label>
            <label>
              <span>接口地址</span>
              <Input
                placeholder="https://example.com/v1"
                value={aiGatewayEditor.channel.baseUrl}
                onChange={(event) =>
                  setAiGatewayEditor((current) => ({
                    ...current,
                    channel: { ...current.channel, baseUrl: event.target.value },
                  }))
                }
              />
            </label>
            <div className="admin-ai-gateway-form-grid">
              <label>
                <span>Provider 类型</span>
                <Select
                  value={aiGatewayEditor.channel.providerType || 'openai_compatible'}
                  options={[{ value: 'openai_compatible', label: 'OpenAI 兼容' }]}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      channel: { ...current.channel, providerType: value },
                    }))
                  }
                />
              </label>
              <label>
                <span>能力</span>
                <Select
                  mode="multiple"
                  value={aiGatewayEditor.channel.capabilities || ['chat']}
                  options={[
                    { value: 'chat', label: '文本/视觉理解' },
                    { value: 'image', label: '图片生成' },
                  ]}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      channel: { ...current.channel, capabilities: value },
                    }))
                  }
                />
              </label>
              <label>
                <span>文本模型</span>
                <Input
                  value={aiGatewayEditor.channel.textModel}
                  onChange={(event) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      channel: { ...current.channel, textModel: event.target.value },
                    }))
                  }
                />
              </label>
              <label>
                <span>图片模型</span>
                <Input
                  value={aiGatewayEditor.channel.imageModel}
                  onChange={(event) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      channel: { ...current.channel, imageModel: event.target.value },
                    }))
                  }
                />
              </label>
              <div className="admin-ai-gateway-template-grid">
                <div className="admin-ai-gateway-template-title">
                  <Typography.Text strong>阶段模型模板</Typography.Text>
                  <Typography.Text type="secondary">留空时使用上面的默认文本/图片模型</Typography.Text>
                </div>
                {aiGateway.routes.map((route) => (
                  <label key={route.stage}>
                    <span>{route.title}</span>
                    <Input
                      placeholder={
                        route.modelType === 'image'
                          ? aiGatewayEditor.channel?.imageModel
                          : aiGatewayEditor.channel?.textModel
                      }
                      value={(aiGatewayEditor.channel?.modelTemplates || {})[route.stage] || ''}
                      onChange={(event) =>
                        setAiGatewayEditor((current) => {
                          const templates = { ...(current.channel?.modelTemplates || {}) };
                          const nextValue = event.target.value.trim();
                          if (nextValue) {
                            templates[route.stage] = nextValue;
                          } else {
                            delete templates[route.stage];
                          }
                          return {
                            ...current,
                            channel: { ...current.channel, modelTemplates: templates },
                          };
                        })
                      }
                    />
                  </label>
                ))}
              </div>
              <label>
                <span>优先级</span>
                <InputNumber
                  min={1}
                  value={aiGatewayEditor.channel.priority}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      channel: { ...current.channel, priority: Number(value || 100) },
                    }))
                  }
                />
              </label>
              <label>
                <span>启用</span>
                <Switch
                  checked={aiGatewayEditor.channel.enabled !== false}
                  onChange={(enabled) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      channel: { ...current.channel, enabled },
                    }))
                  }
                />
              </label>
              <label>
                <span>连接超时秒</span>
                <InputNumber
                  min={1}
                  value={aiGatewayEditor.channel.connectTimeoutSeconds}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      channel: { ...current.channel, connectTimeoutSeconds: Number(value || 10) },
                    }))
                  }
                />
              </label>
              <label>
                <span>读取超时秒</span>
                <InputNumber
                  min={1}
                  value={aiGatewayEditor.channel.readTimeoutSeconds}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      channel: { ...current.channel, readTimeoutSeconds: Number(value || 60) },
                    }))
                  }
                />
              </label>
            </div>
          </div>
        ) : null}
      </Modal>

      <Modal
        title={aiGatewayEditor.credential?.id ? '编辑 Key' : '新增 Key'}
        open={Boolean(aiGatewayEditor.credential)}
        okText="保存 Key"
        cancelText="关闭"
        confirmLoading={savingAiGateway}
        onOk={() => void saveAiGatewayCredentialEditor()}
        onCancel={() => setAiGatewayEditor({})}
        width={760}
      >
        {aiGatewayEditor.credential ? (
          <div className="admin-ai-gateway-form">
            <div className="admin-ai-gateway-form-grid">
              <label>
                <span>所属渠道</span>
                <Select
                  value={aiGatewayEditor.credential.channelId}
                  options={aiGatewayChannelOptions}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      credential: { ...current.credential, channelId: value },
                    }))
                  }
                />
              </label>
              <label>
                <span>Key 名称</span>
                <Input
                  value={aiGatewayEditor.credential.name}
                  onChange={(event) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      credential: { ...current.credential, name: event.target.value },
                    }))
                  }
                />
              </label>
            </div>
            <label>
              <span>API Key</span>
              <Input.Password
                placeholder={aiGatewayEditor.credential.id ? '输入新 Key 才会替换' : '输入 API Key'}
                value={aiGatewayEditor.credential.apiKey}
                onChange={(event) =>
                  setAiGatewayEditor((current) => ({
                    ...current,
                    credential: { ...current.credential, apiKey: event.target.value, clearApiKey: false },
                  }))
                }
              />
            </label>
            <div className="admin-ai-gateway-form-grid">
              <label>
                <span>启用</span>
                <Switch
                  checked={aiGatewayEditor.credential.enabled !== false}
                  onChange={(enabled) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      credential: { ...current.credential, enabled },
                    }))
                  }
                />
              </label>
              <label>
                <span>优先级</span>
                <InputNumber
                  min={1}
                  value={aiGatewayEditor.credential.priority}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      credential: { ...current.credential, priority: Number(value || 100) },
                    }))
                  }
                />
              </label>
              <label>
                <span>权重</span>
                <InputNumber
                  min={1}
                  value={aiGatewayEditor.credential.weight}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      credential: { ...current.credential, weight: Number(value || 1) },
                    }))
                  }
                />
              </label>
              <label>
                <span>最大并发</span>
                <InputNumber
                  min={0}
                  value={aiGatewayEditor.credential.maxConcurrency}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      credential: { ...current.credential, maxConcurrency: Number(value || 0) },
                    }))
                  }
                />
              </label>
              <label>
                <span>RPM 限制</span>
                <InputNumber
                  min={0}
                  value={aiGatewayEditor.credential.rpmLimit}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      credential: { ...current.credential, rpmLimit: Number(value || 0) },
                    }))
                  }
                />
              </label>
              <label>
                <span>每日限制</span>
                <InputNumber
                  min={0}
                  value={aiGatewayEditor.credential.dailyLimit}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      credential: { ...current.credential, dailyLimit: Number(value || 0) },
                    }))
                  }
                />
              </label>
            </div>
          </div>
        ) : null}
      </Modal>

      <Modal
        title={activeKeyManagerChannel ? `?? Key ${activeKeyManagerChannel.name}` : '?? Key'}
        open={Boolean(aiGatewayEditor.keyManagerChannel)}
        footer={
          <Space>
            <Button onClick={() => setAiGatewayEditor({})}>关闭</Button>
            {activeKeyManagerChannel ? (
              <Button
                type="primary"
                onClick={() =>
                  setAiGatewayEditor({
                    credential: {
                      channelId: activeKeyManagerChannel.id,
                      name: '',
                      enabled: true,
                      priority: 100,
                      weight: 1,
                      maxConcurrency: 2,
                    },
                    keyManagerChannel: activeKeyManagerChannel,
                  })
                }
              >
                新增 Key
              </Button>
            ) : null}
          </Space>
        }
        onCancel={() => setAiGatewayEditor({})}
        width={980}
      >
        {activeKeyManagerChannel ? (
          <div className="admin-ai-gateway-key-manager">
            <div className="admin-ai-gateway-key-manager-head">
              <Space size={6} wrap>
                <Tag>{activeKeyManagerChannel.providerType}</Tag>
                {activeKeyManagerChannel.capabilities.map((capability) => (
                  <Tag color={capability === 'image' ? 'purple' : 'blue'} key={capability}>
                    {capability}
                  </Tag>
                ))}
              </Space>
              <Typography.Text type="secondary">{activeKeyManagerChannel.baseUrl || '未配置接口地址'}</Typography.Text>
            </div>
            <Table<AiGatewayCredential>
              rowKey="id"
              columns={aiGatewayCredentialColumns}
              dataSource={activeKeyManagerChannel.credentials}
              locale={{ emptyText: '还没有 Key，点击右下角新增 Key' }}
              pagination={false}
              size="middle"
            />
          </div>
        ) : null}
      </Modal>

      <Modal
        title={aiGatewayEditor.route ? `路由策略 ${aiGatewayEditor.route.title}` : '路由策略'}
        open={Boolean(aiGatewayEditor.route)}
        okText="保存路由"
        cancelText="关闭"
        confirmLoading={savingAiGateway}
        onOk={() => void saveAiGatewayRouteEditor()}
        onCancel={() => setAiGatewayEditor({})}
      >
        {aiGatewayEditor.route ? (
          <div className="admin-ai-gateway-form">
            <label>
              <span>候选渠道顺序</span>
              <Select
                mode="multiple"
                value={aiGatewayEditor.route.channelOrder}
                options={aiGatewayChannelOptions}
                placeholder="不选择时按渠道优先级自动选择"
                onChange={(value) =>
                  setAiGatewayEditor((current) => ({
                    ...current,
                    route: current.route ? { ...current.route, channelOrder: value } : undefined,
                  }))
                }
              />
            </label>
            <div className="admin-ai-gateway-form-grid">
              <label>
                <span>Key 选择策略</span>
                <Select
                  value={aiGatewayEditor.route.keySelectionPolicy}
                  options={[{ value: 'least_in_flight_weighted', label: '最少并发 + 权重' }]}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      route: current.route ? { ...current.route, keySelectionPolicy: value } : undefined,
                    }))
                  }
                />
              </label>
              <label>
                <span>最多尝试渠道</span>
                <InputNumber
                  min={1}
                  value={aiGatewayEditor.route.maxChannelAttempts}
                  onChange={(value) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      route: current.route ? { ...current.route, maxChannelAttempts: Number(value || 1) } : undefined,
                    }))
                  }
                />
              </label>
              <label>
                <span>跨渠道兜底</span>
                <Switch
                  checked={aiGatewayEditor.route.allowCrossChannelFallback}
                  onChange={(allowCrossChannelFallback) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      route: current.route ? { ...current.route, allowCrossChannelFallback } : undefined,
                    }))
                  }
                />
              </label>
              <label>
                <span>启用</span>
                <Switch
                  checked={aiGatewayEditor.route.enabled}
                  onChange={(enabled) =>
                    setAiGatewayEditor((current) => ({
                      ...current,
                      route: current.route ? { ...current.route, enabled } : undefined,
                    }))
                  }
                />
              </label>
            </div>
          </div>
        ) : null}
      </Modal>

      <Modal
        title="路由干跑结果"
        open={Boolean(aiGatewayEditor.dryRun)}
        footer={<Button onClick={() => setAiGatewayEditor({})}>关闭</Button>}
        onCancel={() => setAiGatewayEditor({})}
      >
        {aiGatewayEditor.dryRun ? (
          <div className="admin-ai-gateway-dry-run">
            <Space direction="vertical" size={8}>
              <Typography.Text strong>
                {aiGatewayEditor.dryRun.selected
                  ? `将使用 ${aiGatewayEditor.dryRun.selected.channel.name} / ${aiGatewayEditor.dryRun.selected.credential.name}`
                  : '当前没有可用渠道'}
              </Typography.Text>
              {aiGatewayEditor.dryRun.selected ? (
                <Tag color="blue">模型 {aiGatewayEditor.dryRun.selected.model || '未配置'}</Tag>
              ) : null}
            </Space>
            <div className="admin-ai-gateway-dry-run-list">
              {aiGatewayEditor.dryRun.attempts.map((attempt, index) => (
                <div className="admin-ai-gateway-dry-run-item" key={`${attempt.channelId}-${index}`}>
                  <Tag color={attempt.status === 'selected' ? 'green' : 'default'}>
                    {attempt.status === 'selected' ? '选中' : '跳过'}
                  </Tag>
                  <Typography.Text>{attempt.channelName || attempt.channelId}</Typography.Text>
                  <Typography.Text type="secondary">{attempt.reason}</Typography.Text>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </Modal>

      <Modal
        title={`用量额度 ${usageLimitState.user?.displayName || usageLimitState.user?.username || ''}`}
        open={Boolean(usageLimitState.user)}
        okText="保存额度"
        cancelText="关闭"
        confirmLoading={usageLimitState.saving}
        onOk={() => void saveUsageLimit()}
        onCancel={() => setUsageLimitState({ monthlyApiCallLimit: 0, loading: false, saving: false })}
      >
        {usageLimitState.loading ? (
          <Card loading />
        ) : (
          <div className="admin-usage-limit-modal">
            <div className="admin-usage-limit-overview">
              <div>
                <Typography.Text type="secondary">本月已用</Typography.Text>
                <Typography.Title level={4}>{usageLimitState.limit?.monthlyCallCount || 0}</Typography.Title>
              </div>
              <div>
                <Typography.Text type="secondary">当前额度</Typography.Text>
                <Typography.Title level={4}>{usageLimitLabel(usageLimitState.limit?.monthlyApiCallLimit)}</Typography.Title>
              </div>
              <div>
                <Typography.Text type="secondary">剩余</Typography.Text>
                <Typography.Title level={4}>
                  {usageLimitState.limit?.monthlyRemainingCalls ?? '不限'}
                </Typography.Title>
              </div>
            </div>
            <label className="admin-usage-limit-input">
              <span>本月 API 调用上限</span>
              <InputNumber
                min={0}
                precision={0}
                value={usageLimitState.monthlyApiCallLimit}
                onChange={(value) =>
                  setUsageLimitState((current) => ({
                    ...current,
                    monthlyApiCallLimit: Number(value || 0),
                  }))
                }
              />
            </label>
            <Typography.Text type="secondary">填 0 表示不限额；成员本月达到上限后，新的 AI 请求会被拦截。</Typography.Text>
          </div>
        )}
      </Modal>

      <Modal
        title={`重置密码 ${passwordReset.user?.username || ''}`}
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


