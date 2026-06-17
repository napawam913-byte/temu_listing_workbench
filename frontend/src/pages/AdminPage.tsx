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
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties, Key } from 'react';
import {
  createAdminUser,
  deleteAdminUsers,
  fetchAdminApiChannels,
  fetchAdminPromptConfigs,
  fetchAdminApiUsage,
  fetchAdminSettings,
  fetchAdminUserApiCredentials,
  fetchAdminUserUsageLimit,
  fetchAdminUsers,
  resetAdminUserPassword,
  updateAdminApiChannels,
  updateAdminSettings,
  updateAdminUserApiCredentials,
  updateAdminUserUsageLimit,
  updateAdminUser,
} from '../api/backendApi';
import type {
  AdminApiChannel,
  AdminApiChannelUpdateItem,
  AdminApiUsageGroup,
  AdminApiUsageItem,
  AdminApiUsageSummary,
  AdminPromptConfig,
  AdminSetting,
  AdminSettingsUpdateItem,
  AdminUser,
  AdminUserApiCredential,
  AdminUserApiCredentialUpdateItem,
  AdminUserUsageLimit,
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

type ApiChannelDraft = {
  name: string;
  enabled: boolean;
  baseUrl: string;
  apiKey: string;
  clearApiKey?: boolean;
};

type MemberCredentialDraft = {
  enabled: boolean;
  apiKey: string;
  baseUrl: string;
  clearApiKey?: boolean;
};

type MemberCredentialState = {
  user?: AdminUser;
  credentials: AdminUserApiCredential[];
  drafts: Record<string, MemberCredentialDraft>;
  loading: boolean;
  saving: boolean;
};

type UsageLimitState = {
  user?: AdminUser;
  limit?: AdminUserUsageLimit;
  monthlyApiCallLimit: number;
  loading: boolean;
  saving: boolean;
};

const EMPTY_API_USAGE: AdminApiUsageSummary = {
  items: [],
  totalCalls: 0,
  exactCalls: 0,
  inferredCalls: 0,
  byUser: [],
  byTeam: [],
  byChannel: [],
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
    modelKey: 'OPENAI_TITLE_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '中文标题、英文标题、变种值英文翻译',
  },
  {
    title: '标题拆分',
    modelKey: 'OPENAI_TITLE_SPLIT_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '把商品标题拆成 1688 采购搜索关键词',
  },
  {
    title: '智能推荐',
    modelKey: 'OPENAI_RECOMMENDATION_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '商品标题、类目、图片分析和推荐关键词',
  },
  {
    title: '产品属性填写',
    modelKey: 'OPENAI_PRODUCT_ATTRIBUTE_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '导出时根据类目属性库和商品信息填写产品属性',
  },
  {
    title: '图片理解',
    modelKey: 'OPENAI_VISUAL_ANALYSIS_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '生图前分析主体、材质、结构、风险和画风',
  },
  {
    title: '提示词规划',
    modelKey: 'OPENAI_VISUAL_PROMPT_MODEL',
    modelFallbackKey: 'OPENAI_TEXT_MODEL',
    description: '把分析结果转成九宫格或四宫格母图提示词',
  },
  {
    title: '图片生成',
    modelKey: 'OPENAI_IMAGE_MODEL',
    description: '实际生成母图、单图精修和 SKU 适配图',
  },
];

function categoryLabel(category: string) {
  if (category === 'ai') return 'AI 配置';
  if (category === 'visual') return '生图配置';
  if (category === '1688') return '1688 API';
  if (category === 'oss') return '阿里云 OSS';
  return category;
}

function categoryDescription(category: string) {
  if (category === 'ai') return '管理各个 AI 阶段实际调用的模型，API Key 和 Base URL 请到初凡 API 配置。';
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

function apiStageLabel(stage: string) {
  const normalizedStage = stage.replace(/_/g, '-');
  if (normalizedStage === 'visual-analysis') return '图片理解';
  if (normalizedStage === 'visual-prompt') return '提示词规划';
  if (normalizedStage === 'visual-image') return '图片生成';
  if (normalizedStage === 'recommendation') return '智能推荐';
  if (normalizedStage === 'title') return '标题生成';
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

function apiChannelDraftsFromChannels(channels: AdminApiChannel[]) {
  return Object.fromEntries(
    channels.map((channel) => [
      channel.id,
      {
        name: channel.name,
        enabled: channel.id === 'chufan_ai' ? true : channel.enabled,
        baseUrl: channel.baseUrl,
        apiKey: '',
        clearApiKey: false,
      },
    ]),
  );
}

function memberCredentialDraftsFromItems(items: AdminUserApiCredential[]) {
  return Object.fromEntries(
    items.map((item) => [
      item.channelId,
      {
        enabled: item.enabled,
        apiKey: '',
        baseUrl: item.baseUrl,
        clearApiKey: false,
      },
    ]),
  );
}

function adminUserInitial(user: AdminUser) {
  return (user.displayName || user.username || '?').trim().slice(0, 1).toUpperCase();
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
  const [apiChannels, setApiChannels] = useState<AdminApiChannel[]>([]);
  const [promptConfigs, setPromptConfigs] = useState<AdminPromptConfig[]>([]);
  const [apiChannelDrafts, setApiChannelDrafts] = useState<Record<string, ApiChannelDraft>>({});
  const [activeApiConfigTab, setActiveApiConfigTab] = useState('chufan-api');
  const [settingDrafts, setSettingDrafts] = useState<Record<string, string>>({});
  const [secretEditingKeys, setSecretEditingKeys] = useState<Record<string, boolean>>({});
  const [editingAiStageKey, setEditingAiStageKey] = useState<string | null>(null);
  const [highlightedModel, setHighlightedModel] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [creatingUser, setCreatingUser] = useState(false);
  const [deletingUsers, setDeletingUsers] = useState(false);
  const [selectedUserRowKeys, setSelectedUserRowKeys] = useState<Key[]>([]);
  const [passwordReset, setPasswordReset] = useState<PasswordResetState>({ password: '' });
  const [expandedUserRowKeys, setExpandedUserRowKeys] = useState<Key[]>([]);
  const [memberCredentialState, setMemberCredentialState] = useState<MemberCredentialState>({
    credentials: [],
    drafts: {},
    loading: false,
    saving: false,
  });
  const [usageLimitState, setUsageLimitState] = useState<UsageLimitState>({
    monthlyApiCallLimit: 0,
    loading: false,
    saving: false,
  });

  const loadAdminData = useCallback(async () => {
    setLoading(true);
    try {
      const [nextUsers, nextSettings, nextApiUsage, nextApiChannels, nextPromptConfigs] = await Promise.all([
        fetchAdminUsers(),
        fetchAdminSettings(),
        fetchAdminApiUsage(),
        fetchAdminApiChannels(),
        fetchAdminPromptConfigs(),
      ]);
      setUsers(nextUsers);
      setSettings(nextSettings);
      setApiUsage(nextApiUsage);
      setApiChannels(nextApiChannels.channels);
      setPromptConfigs(nextPromptConfigs);
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
      content: '删除后会清理这些成员的登录会话、团队关系、API Key 配置和用量记录。当前登录管理员和最后一个管理员不会被允许删除。',
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

  const openMemberApiCredentials = async (user: AdminUser) => {
    setMemberCredentialState({ user, credentials: [], drafts: {}, loading: true, saving: false });
    try {
      const credentials = await fetchAdminUserApiCredentials(user.id);
      setMemberCredentialState({
        user,
        credentials,
        drafts: memberCredentialDraftsFromItems(credentials),
        loading: false,
        saving: false,
      });
    } catch (error) {
      setMemberCredentialState({ credentials: [], drafts: {}, loading: false, saving: false });
      message.error(error instanceof Error ? error.message : '成员 API 配置读取失败');
    }
  };

  const saveMemberApiCredentials = async () => {
    const user = memberCredentialState.user;
    if (!user) return;
    setMemberCredentialState((current) => ({ ...current, saving: true }));
    try {
      const items: AdminUserApiCredentialUpdateItem[] = memberCredentialState.credentials.map((credential) => {
        const draft = memberCredentialState.drafts[credential.channelId];
        return {
          channelId: credential.channelId,
          enabled: draft?.enabled,
          apiKey: draft?.apiKey?.trim() || undefined,
          clearApiKey: Boolean(draft?.clearApiKey),
          baseUrl: draft?.baseUrl,
        };
      });
      const credentials = await updateAdminUserApiCredentials(user.id, items);
      setMemberCredentialState({
        user,
        credentials,
        drafts: memberCredentialDraftsFromItems(credentials),
        loading: false,
        saving: false,
      });
      message.success('成员 API 配置已保存');
    } catch (error) {
      setMemberCredentialState((current) => ({ ...current, saving: false }));
      message.error(error instanceof Error ? error.message : '成员 API 配置保存失败');
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
      setApiUsage(await fetchAdminApiUsage());
      message.success('用量额度已保存');
    } catch (error) {
      setUsageLimitState((current) => ({ ...current, saving: false }));
      message.error(error instanceof Error ? error.message : '用量额度保存失败');
    }
  };

  const saveSettings = async (options?: { silent?: boolean; skipNoopMessage?: boolean }) => {
    const items: AdminSettingsUpdateItem[] = [];
    const knownSettingKeys = new Set<string>();
    const aiStageModelKeys = new Set(AI_STAGE_CONFIGS.map((stage) => stage.modelKey));
    settings.forEach((setting) => {
      if (setting.category === 'ai' && !aiStageModelKeys.has(setting.key)) return;
      knownSettingKeys.add(setting.key);
      const value = settingDrafts[setting.key] ?? '';
      if (setting.isSecret && !value) return;
      if (!setting.isSecret && value === (setting.value || '')) return;
      items.push({ key: setting.key, value });
    });

    AI_STAGE_CONFIGS.forEach((stage) => {
      const value = settingDrafts[stage.modelKey] ?? '';
      if (!value || knownSettingKeys.has(stage.modelKey)) return;
      items.push({ key: stage.modelKey, value });
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
      const items: AdminApiChannelUpdateItem[] = apiChannels
        .filter((channel) => channel.id === 'chufan_ai')
        .map((channel) => {
          const draft = apiChannelDrafts[channel.id];
          return {
            id: channel.id,
            name: draft?.name,
            enabled: true,
            apiKey: draft?.apiKey?.trim() || undefined,
            clearApiKey: Boolean(draft?.clearApiKey),
            baseUrl: draft?.baseUrl,
          };
        });
      const bundle = await updateAdminApiChannels(items);
      syncApiChannelBundle(bundle);
      if (!options?.silent) {
        message.success('初凡 API 已保存');
      }
      return bundle;
    } catch (error) {
      if (!options?.silent) {
        message.error(error instanceof Error ? error.message : '初凡 API 保存失败');
      }
      throw error;
    } finally {
      setSavingSettings(false);
    }
  };

  const saveAllRuntimeConfig = async () => {
    setSavingSettings(true);
    try {
      await saveApiChannels({ silent: true });
      await saveSettings({ silent: true, skipNoopMessage: true });
      message.success('全部运行配置已保存');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '全部运行配置保存失败');
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
  const adminUserOptions = useMemo(
    () =>
      users
        .filter((user) => user.role === 'admin' && user.status === 'active')
        .map((user) => ({ value: user.id, label: user.displayName || user.username })),
    [users],
  );
  const apiChannelNameById = useMemo(
    () => new Map(apiChannels.map((channel) => [channel.id, channel.name])),
    [apiChannels],
  );
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

  const editingAiStage = useMemo(
    () => AI_STAGE_CONFIGS.find((stage) => stage.modelKey === editingAiStageKey) || null,
    [editingAiStageKey],
  );

  const userColumns: ColumnsType<AdminUserRow> = [
    {
      title: '用户',
      dataIndex: 'username',
      width: 190,
      render: (_, user) => (
        <div className="admin-user-cell">
          <span className={`admin-user-avatar admin-user-avatar-${user.role}`}>{adminUserInitial(user)}</span>
          <div className="admin-user-meta">
            <Typography.Text className="admin-user-display" strong>
              {user.displayName || user.username}
            </Typography.Text>
            <Typography.Text className="admin-user-username" type="secondary">
              @{user.username}
            </Typography.Text>
          </div>
        </div>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      width: 100,
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
      title: '状态',
      dataIndex: 'status',
      width: 100,
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
      width: 140,
      render: (_, user) =>
        user.role === 'admin' ? (
          <Space className="admin-user-manager-inline" size={6}>
            <Tag className="admin-user-manager-tag" color="blue">
              管理员团队
            </Tag>
            <Tag className="admin-user-member-count" color={user.memberCount ? 'processing' : 'default'}>
              {user.memberCount || 0} 人
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
      width: 72,
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
      width: 128,
      render: (value: string) => <span className="admin-user-date">{value}</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 132,
      render: (_, user) => (
        <Space className="admin-user-actions" size={8} wrap={false}>
          <Button className="admin-user-action-btn" size="small" onClick={() => void openMemberApiCredentials(user)}>
            API 配置
          </Button>
          <Button className="admin-user-action-btn" size="small" onClick={() => setPasswordReset({ user, password: '' })}>
            重置密码
          </Button>
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

  const editingStageModelSetting = editingAiStage ? settingsByKey.get(editingAiStage.modelKey) : undefined;
  const editingStageFallbackModelSetting =
    editingAiStage && editingAiStage.modelFallbackKey ? settingsByKey.get(editingAiStage.modelFallbackKey) : undefined;
  const settingDraftValue = (key: string, setting?: AdminSetting) =>
    Object.prototype.hasOwnProperty.call(settingDrafts, key) ? settingDrafts[key] || '' : settingValue(setting);
  const editingStageModelDraft = editingAiStage ? settingDrafts[editingAiStage.modelKey] ?? '' : '';
  const editingStageFallbackModelValue =
    editingAiStage && editingAiStage.modelFallbackKey
      ? settingDraftValue(editingAiStage.modelFallbackKey, editingStageFallbackModelSetting)
      : '';
  const promptConfigTab = {
    key: 'prompt-configs',
    label: '提示词配置',
    children: (
      <div className="admin-prompt-config-tab">
        <div className="admin-setting-group-head">
          <Typography.Text strong>提示词配置</Typography.Text>
          <Typography.Text type="secondary">查看各个 AI 阶段的输入、输出和实际提示词模板。</Typography.Text>
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
                    <Tag color="green">只读</Tag>
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
                  readOnly
                  value={prompt.content}
                  autoSize={{ minRows: 8, maxRows: 18 }}
                />
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
                  <Table<AdminUserRow>
                    rowKey="id"
                    className="admin-user-table"
                    columns={userColumns}
                    dataSource={userTableRows}
                    rowSelection={{
                      selectedRowKeys: selectedUserRowKeys,
                      onChange: (keys) => setSelectedUserRowKeys([...keys]),
                    }}
                    expandable={{
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
                    scroll={{ x: 876 }}
                    size="middle"
                    title={() => (
                      <div className="admin-user-table-summary">
                        <Space className="admin-user-summary-tags" size={10} wrap>
                          <span>管理员 {userTableSummary.adminCount}</span>
                          <span>成员 {userTableSummary.memberCount}</span>
                          {userTableSummary.unassignedCount ? <span>未归属 {userTableSummary.unassignedCount}</span> : null}
                          {selectedUserRowKeys.length ? <span>已选 {selectedUserRowKeys.length}</span> : null}
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

                <Card title="团队与成员用量" className="admin-table-card admin-api-usage-group-card" loading={loading}>
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
                    ]}
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
                    {
                      key: 'chufan-api',
                      label: '初凡 API',
                      children: (
                        <div className="admin-api-channel-tab">
                  <section className="admin-api-channel-panel">
                    <div className="admin-api-section-head">
                      <div>
                        <Typography.Text strong>初凡 API</Typography.Text>
                        <Typography.Text type="secondary">配置初凡 AI 的 API Key 和 OpenAI 兼容 Base URL。</Typography.Text>
                      </div>
                      <Button loading={savingSettings} onClick={() => void saveApiChannels()}>
                        保存初凡 API
                      </Button>
                    </div>
                    <div className="admin-api-channel-grid">
                      {apiChannels.filter((channel) => channel.id === 'chufan_ai').map((channel) => {
                        const draft = apiChannelDrafts[channel.id] || {
                          name: channel.name,
                          enabled: true,
                          baseUrl: channel.baseUrl,
                          apiKey: '',
                        };
                        return (
                          <div className="admin-api-channel-card" key={channel.id}>
                            <div className="admin-api-channel-title">
                              <Typography.Text strong>{channel.name}</Typography.Text>
                            </div>
                            <Typography.Text type="secondary">{channel.description}</Typography.Text>
                            <Space size={6} wrap>
                              <Tag color="green">启用</Tag>
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
                    promptConfigTab,
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
                                      编辑模型
                                    </Button>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                        {(category === 'ai' ? [] : groupSettings).map((setting) => {
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
        title={editingAiStage ? `${editingAiStage.title}模型配置` : '模型配置'}
        open={Boolean(editingAiStage)}
        okText="保存模型"
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
          </div>
        ) : null}
      </Modal>

      <Modal
        title={`成员 API 配置：${memberCredentialState.user?.displayName || memberCredentialState.user?.username || ''}`}
        open={Boolean(memberCredentialState.user)}
        okText="保存成员配置"
        cancelText="关闭"
        width={980}
        confirmLoading={memberCredentialState.saving}
        onOk={() => void saveMemberApiCredentials()}
        onCancel={() => setMemberCredentialState({ credentials: [], drafts: {}, loading: false, saving: false })}
      >
        <div className="admin-api-member-credentials">
          <Typography.Text type="secondary">
            管理员代管成员 API Key。成员调用 AI 时优先使用这里启用的渠道，成员本人不可修改密钥。
          </Typography.Text>
          {memberCredentialState.loading ? (
            <Card loading />
          ) : (
            <div className="admin-api-channel-grid">
              {memberCredentialState.credentials.map((credential) => {
                const draft = memberCredentialState.drafts[credential.channelId] || {
                  enabled: credential.enabled,
                  apiKey: '',
                  baseUrl: credential.baseUrl,
                };
                return (
                  <div className="admin-api-channel-card" key={credential.channelId}>
                    <div className="admin-api-channel-title">
                      <Typography.Text strong>{credential.name}</Typography.Text>
                      <Switch
                        checked={draft.enabled}
                        onChange={(enabled) =>
                          setMemberCredentialState((current) => {
                            const nextDrafts = Object.fromEntries(
                              Object.entries(current.drafts).map(([channelId, value]) => [
                                channelId,
                                {
                                  ...value,
                                  enabled: enabled ? channelId === credential.channelId : false,
                                },
                              ]),
                            );
                            return {
                              ...current,
                              drafts: {
                                ...nextDrafts,
                                [credential.channelId]: {
                                  ...draft,
                                  enabled,
                                },
                              },
                            };
                          })
                        }
                      />
                    </div>
                    <Typography.Text type="secondary">{credential.description}</Typography.Text>
                    <Space size={6} wrap>
                      <Tag color={draft.enabled ? 'green' : 'default'}>{draft.enabled ? '启用' : '停用'}</Tag>
                      <Tag color={credential.apiKeyConfigured && !draft.clearApiKey ? 'green' : 'gold'}>
                        {credential.apiKeyConfigured && !draft.clearApiKey
                          ? credential.maskedApiKey || 'Key 已配置'
                          : 'Key 待配置'}
                      </Tag>
                    </Space>
                    <div className="admin-api-channel-fields">
                      <label>
                        <span>API Key</span>
                        <Input.Password
                          placeholder={credential.apiKeyConfigured ? '输入新 Key 才会替换' : '输入 API Key'}
                          value={draft.apiKey}
                          onChange={(event) =>
                            setMemberCredentialState((current) => ({
                              ...current,
                              drafts: {
                                ...current.drafts,
                                [credential.channelId]: {
                                  ...draft,
                                  apiKey: event.target.value,
                                  clearApiKey: false,
                                },
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
                            setMemberCredentialState((current) => ({
                              ...current,
                              drafts: {
                                ...current.drafts,
                                [credential.channelId]: {
                                  ...draft,
                                  baseUrl: event.target.value,
                                },
                              },
                            }))
                          }
                        />
                      </label>
                    </div>
                    <Button
                      danger
                      disabled={!credential.apiKeyConfigured && !draft.apiKey}
                      size="small"
                      onClick={() =>
                        setMemberCredentialState((current) => ({
                          ...current,
                          drafts: {
                            ...current.drafts,
                            [credential.channelId]: {
                              ...draft,
                              apiKey: '',
                              clearApiKey: true,
                            },
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
          )}
        </div>
      </Modal>

      <Modal
        title={`用量额度：${usageLimitState.user?.displayName || usageLimitState.user?.username || ''}`}
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
