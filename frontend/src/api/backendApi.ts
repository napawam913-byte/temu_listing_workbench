import type { Product } from '../types/product';
import type { LinkListRecord } from '../types/linkList';

function resolveApiBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  if (configured) return configured.replace(/\/$/, '');
  if (typeof window !== 'undefined') {
    if (!import.meta.env.DEV) {
      return window.location.origin;
    }
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return 'http://localhost:8000';
}

export const API_BASE_URL = resolveApiBaseUrl();
const LEGACY_AUTH_TOKEN_STORAGE_KEY = 'temuListingWorkbenchAuthToken';

export type CurrentUser = {
  id: string;
  username: string;
  displayName: string;
  role: string;
  status?: string;
};

export type AuthResponse = {
  user: CurrentUser;
};

export type AdminUser = {
  id: string;
  username: string;
  displayName: string;
  role: 'admin' | 'user';
  status: 'active' | 'disabled';
  managerId?: string;
  managerName?: string;
  teamId?: string;
  teamName?: string;
  createdAt: string;
  updatedAt: string;
  activeSessionCount: number;
};

export type AdminSetting = {
  key: string;
  category: 'ai' | 'visual' | 'oss' | '1688' | string;
  label: string;
  description: string;
  value: string;
  maskedValue: string;
  isSecret: boolean;
  configured: boolean;
  source: 'database' | 'env' | 'default' | string;
  updatedAt?: string | null;
};

export type AdminSettingsUpdateItem = {
  key: string;
  value?: string | null;
  clear?: boolean;
};

export type AdminApiUsageItem = {
  id: string;
  userId?: string;
  channelId?: string;
  provider: string;
  apiType: string;
  stage: string;
  model: string;
  callCount: number;
  successCount: number;
  failedCount: number;
  lastCalledAt?: string | null;
  source: string;
  isInferred: boolean;
  notes?: string;
};

export type AdminApiUsageGroup = {
  userId?: string;
  username?: string;
  displayName?: string;
  role?: string;
  managerId?: string;
  managerName?: string;
  teamId?: string;
  teamName?: string;
  adminUserId?: string;
  adminName?: string;
  channelId?: string;
  userCount?: number;
  callCount: number;
  successCount: number;
  failedCount: number;
  monthlyCallCount?: number;
  monthlyApiCallLimit?: number;
  monthlyRemainingCalls?: number | null;
  monthlyUsageRatio?: number;
  usageStatus?: 'unlimited' | 'ok' | 'warning' | 'exceeded' | string;
  periodStart?: string;
  lastCalledAt?: string | null;
};

export type AdminApiUsageSummary = {
  items: AdminApiUsageItem[];
  totalCalls: number;
  exactCalls: number;
  inferredCalls: number;
  byUser: AdminApiUsageGroup[];
  byTeam: AdminApiUsageGroup[];
  byChannel: AdminApiUsageGroup[];
};

export type AdminApiChannel = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  baseUrl: string;
  textModel: string;
  imageModel: string;
  apiKeyConfigured: boolean;
  maskedApiKey: string;
  isCommon: boolean;
};

export type AdminApiRoute = {
  stage: string;
  title: string;
  description: string;
  modelType: 'text' | 'image' | string;
  channelId: string;
  channelName: string;
  model: string;
  baseUrl: string;
  apiKeyConfigured: boolean;
  isInherited: boolean;
};

export type AdminApiChannelBundle = {
  channels: AdminApiChannel[];
  routes: AdminApiRoute[];
};

export type AdminPromptConfig = {
  id: string;
  stage: string;
  title: string;
  description: string;
  modelKey: string;
  source: string;
  inputFrom: string;
  outputTo: string;
  variables: string[];
  content: string;
  readOnly: boolean;
};

export type AdminApiChannelUpdateItem = {
  id: string;
  name?: string;
  enabled?: boolean;
  apiKey?: string;
  clearApiKey?: boolean;
  baseUrl?: string;
  textModel?: string;
  imageModel?: string;
};

export type AdminUserApiCredential = {
  userId: string;
  channelId: string;
  name: string;
  description: string;
  enabled: boolean;
  baseUrl: string;
  textModel: string;
  imageModel: string;
  apiKeyConfigured: boolean;
  maskedApiKey: string;
  updatedAt?: string | null;
};

export type AdminUserApiCredentialUpdateItem = {
  channelId: string;
  enabled?: boolean;
  apiKey?: string;
  clearApiKey?: boolean;
  baseUrl?: string;
  textModel?: string;
  imageModel?: string;
};

export type AdminUserUsageLimit = {
  userId: string;
  monthlyApiCallLimit: number;
  monthlyCallCount: number;
  monthlyRemainingCalls: number | null;
  monthlyUsageRatio: number;
  usageStatus: 'unlimited' | 'ok' | 'warning' | 'exceeded' | string;
  periodStart: string;
  updatedAt?: string | null;
};

export function clearLegacyAuthToken() {
  localStorage.removeItem(LEGACY_AUTH_TOKEN_STORAGE_KEY);
}

function authHeaders(headers: HeadersInit = {}): HeadersInit {
  return headers;
}

function withSession(init: RequestInit = {}): RequestInit {
  return { ...init, credentials: 'include' };
}

export type BackendProduct = {
  id: string;
  source_type?: string | null;
  source_product_id: string;
  title: string;
  title_cn?: string | null;
  title_en?: string | null;
  main_image_url?: string | null;
  gallery_image_urls: string[];
  video_url?: string | null;
  source_url?: string | null;
  category_path?: string | null;
  category_level1?: string | null;
  category_level2?: string | null;
  tags: string[];
  price_usd: number;
  gmv_usd: number;
  weekly_sales: number;
  monthly_sales: number;
  review_count: number;
  listing_time?: string;
  pool_added_at?: string | null;
  status: 'active' | 'deleted' | 'sourced';
  in_product_pool?: boolean;
  source_row_index: number;
};

export type ProductListResponse = {
  items: BackendProduct[];
  total: number;
  page: number;
  page_size: number;
};

export type ProductListParams = {
  page: number;
  pageSize: number;
  keyword?: string;
  period?: Product['period'] | '全部';
  category?: string;
  priceRange?: string;
  salesRange?: string;
  gmvRange?: string;
  poolAddedStart?: string;
  poolAddedEnd?: string;
  scope?: 'pool' | 'all';
  sortBy?: 'price' | 'gmv';
  sortOrder?: 'asc' | 'desc';
};

export type ProductStats = {
  active_count: number;
  recent_7_count: number;
  recent_30_count: number;
  deleted_count: number;
};

export type AddProductsToPoolResponse = {
  ok: boolean;
  added_count: number;
};

export type ProductCategoryOption = {
  value: string;
  label: string;
  count: number;
  level: 1 | 2 | 3 | 4;
  children?: ProductCategoryOption[];
};

export type Captured1688Sku = {
  sku_id?: string;
  specs: Record<string, string>;
  price?: number;
  stock?: number;
  image_url?: string;
  weight_kg?: number;
};

export type Captured1688Candidate = {
  id: string;
  temu_product_id: string;
  offer_id?: string | null;
  product_url: string;
  title: string;
  main_image_url?: string | null;
  gallery_image_urls?: string[];
  price?: number | null;
  price_range?: string | null;
  moq?: number | null;
  shop_name?: string | null;
  shop_url?: string | null;
  sku_list: Captured1688Sku[];
  raw_data: Record<string, unknown>;
  captured_at: string;
  created_at: string;
  updated_at: string;
};

export type Captured1688Material = {
  id: string;
  offer_id?: string | null;
  product_url: string;
  title: string;
  main_image_url?: string | null;
  gallery_image_urls?: string[];
  price?: number | null;
  price_range?: string | null;
  moq?: number | null;
  shop_name?: string | null;
  shop_url?: string | null;
  sku_list: Captured1688Sku[];
  raw_data: Record<string, unknown>;
  captured_at: string;
  assigned_product_id?: string | null;
  assigned_at?: string | null;
  product_list_product_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type YunqiImportResponse = {
  batch_id: string;
  source_filename: string;
  file_type: string;
  total_rows: number;
  imported_count: number;
  failed_count: number;
  errors: string[];
};

export type YunqiSyncResponse = YunqiImportResponse & {
  ok: boolean;
  source: string;
  created_count: number;
  updated_count: number;
  keyword_count: number;
  excel_path?: string;
};

export type Link1688ImportResponse = YunqiImportResponse;

export type DianxiaomiTemplateImportResponse = YunqiImportResponse & {
  records: LinkListRecord[];
};

export type DianxiaomiExportMode = 'distribution' | 'curated';

export type DianxiaomiProductAttributeQueueSummary = {
  queued: number;
  running: number;
  done: number;
  failed: number;
  pending: number;
  total: number;
  queuedNow?: number;
  reused?: number;
  processedNow?: number;
  failedNow?: number;
};

export type DianxiaomiExportTask = {
  id: string;
  userId: string;
  exportMode: DianxiaomiExportMode;
  status: 'queued' | 'running' | 'completed' | 'failed' | string;
  recordCount: number;
  recordIds: string[];
  filename?: string | null;
  downloadUrl?: string | null;
  errorMessage?: string | null;
  createdAt: string;
  updatedAt: string;
  completedAt?: string | null;
};

export type LinkListRecordsResponse = {
  items: LinkListRecord[];
};

export type ChatgptListingPackageResponse = {
  status: 'planned' | 'generated';
  safeTitleCn: string;
  safeTitleEn: string;
  blockedTerms: string[];
  imagePlan: Array<Record<string, string>>;
  generatedImages: Array<Record<string, string>>;
  record: LinkListRecord;
};

export type PluginCreativeJob = {
  id: string;
  provider: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  recordId: string;
  productId?: string | null;
  recordTitle?: string | null;
  safeTitleEn?: string | null;
  imageIndex: number;
  imageKind: string;
  imageLabel: string;
  targetSkuEntryId?: string | null;
  prompt: string;
  analysisText?: string | null;
  inputImageUrl?: string | null;
  resultImageUrl?: string | null;
  resultStorageKey?: string | null;
  errorMessage?: string | null;
  createdAt: string;
  updatedAt: string;
  claimedAt?: string | null;
  completedAt?: string | null;
};

export type PluginCreativeJobsResponse = {
  items: PluginCreativeJob[];
};

export type PluginCreativeSyncResponse = {
  records: LinkListRecord[];
  jobs: PluginCreativeJob[];
  completedRecordIds: string[];
  pendingCount: number;
  failedCount: number;
};

export type VisualGenerationModule = {
  id: string;
  taskId: string;
  panelIndex: number;
  position?: string | null;
  slotType?: string | null;
  title?: string | null;
  purpose?: string | null;
  prompt: string;
  outputPath?: string | null;
  outputUrl?: string | null;
  targetSlotId?: string | null;
  targetSkuEntryId?: string | null;
  status: string;
  createdAt: string;
  updatedAt: string;
};

export type VisualReferenceImageRef = {
  url: string;
  label?: string;
};

export type VisualGenerationTask = {
  id: string;
  userId: string;
  linkRecordId?: string | null;
  productId?: string | null;
  mode: string;
  layout: '1x1' | '2x2' | '3x3' | string;
  requestedCount: number;
  status: string;
  sourceImageRef?: string | null;
  referenceImageRefs?: VisualReferenceImageRef[];
  record?: Record<string, unknown>;
  analysis?: Record<string, unknown>;
  promptText?: string;
  motherImagePath?: string | null;
  motherImageUrl?: string | null;
  manifest?: Record<string, unknown>;
  modules: VisualGenerationModule[];
  errorMessage?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type VisualQueueSummary = {
  counts: Record<string, number>;
  activeCount: number;
  runningCount?: number;
  queuedCount?: number;
  teamActiveCount: number;
  teamRunningCount?: number;
  userConcurrencyLimit: number;
  teamConcurrencyLimit: number;
  team?: Record<string, string>;
  redisEnabled: boolean;
  redisQueueName: string;
  redisQueueLength?: number | null;
  redisRetryQueueName?: string;
  redisRetryQueueLength?: number | null;
  redisDeadQueueName?: string;
  redisDeadQueueLength?: number | null;
};

export type VisualGenerationRunResponse = {
  item: VisualGenerationTask;
  queued: boolean;
  queueBackend: 'redis' | 'background' | string;
  waitingForConcurrency?: boolean;
  message?: string;
};

export type VisualTaskCreatePayload = {
  record?: LinkListRecord;
  linkRecordId?: string;
  productId?: string;
  mode?: string;
  layout?: '1x1' | '2x2' | '3x3' | string;
  requestedCount?: number;
  sourceImageRef?: string;
  referenceImageRefs?: VisualReferenceImageRef[];
};

export type VisualTaskPlanPayload = {
  sourceImageRef?: string;
  referenceImageRefs?: VisualReferenceImageRef[];
  allowShortLabels?: boolean;
  analysisModel?: string;
  promptModel?: string;
};

export type VisualTaskGeneratePayload = {
  splitAfter?: boolean;
  uploadToOss?: boolean;
  imageModel?: string;
  imageSize?: string;
  useReferenceImage?: boolean;
};

export type VisualTaskRunPayload = VisualTaskPlanPayload & VisualTaskGeneratePayload & {
  applyToLinkRecord?: boolean;
  reuseExistingOutputs?: boolean;
};

export type VisualTaskSplitPayload = {
  motherImageRef?: string;
  uploadToOss?: boolean;
  targetSize?: number;
  safeMarginRatio?: number;
  outputFormat?: 'webp' | 'jpg' | 'jpeg' | 'png' | string;
  quality?: number;
  sharpen?: number;
};

export type VisualSplitPayload = VisualTaskSplitPayload & {
  motherImageRef: string;
  layout?: '1x1' | '2x2' | '3x3' | string;
};

export type Smart1688Recommendation = {
  id: string;
  type: 'offer' | 'search';
  title: string;
  main_image_url?: string | null;
  product_url: string;
  image_search_url?: string | null;
  keyword: string;
  reason: string;
  shop_name?: string | null;
  price?: number | null;
  source: 'material' | 'product' | 'ai_search';
  score: number;
};

export type Smart1688RecommendationsResponse = {
  summary: string;
  strategy: string;
  keywords: Smart1688Keyword[];
  items: Smart1688Recommendation[];
};

export type Smart1688Keyword = {
  keyword: string;
  intent: string;
  reason: string;
  searchUrl?: string;
};

export type Title1688KeywordsResponse = {
  primary_keyword: string;
  keywords: Smart1688Keyword[];
  removed_terms: string[];
  source: string;
  model: string;
};

export type ImageSearch1688Item = {
  id: string;
  offer_id?: string;
  title: string;
  main_image_url?: string | null;
  product_url: string;
  price?: string | null;
  shop_name?: string | null;
  sales?: string | number | null;
  keyword?: string | null;
  raw_data?: Record<string, unknown>;
};

export type ImageSearch1688Response = {
  provider: string;
  image_url: string;
  query_image_url: string;
  items: ImageSearch1688Item[];
};

export async function loginUser(username: string, password: string): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, withSession({
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body: AuthResponse = await response.json();
  clearLegacyAuthToken();
  return body;
}

export async function registerUser(username: string, password: string, displayName?: string): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/register`, withSession({
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, display_name: displayName }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body: AuthResponse = await response.json();
  clearLegacyAuthToken();
  return body;
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    if (response.status === 401) clearLegacyAuthToken();
    throw new Error(await readErrorMessage(response));
  }

  const body: { user: CurrentUser } = await response.json();
  return body.user;
}

export async function logoutUser(): Promise<void> {
  await fetch(`${API_BASE_URL}/api/auth/logout`, withSession({
    method: 'POST',
    headers: authHeaders(),
  })).catch(() => undefined);
  clearLegacyAuthToken();
}

export async function uploadYunqiFile(file: File): Promise<YunqiImportResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE_URL}/api/uploads/yunqi`, withSession({
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  }));

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function syncYunqiFile(
  file: File,
  token?: string,
  options: { limit?: number; rebuildKeywords?: boolean } = {},
): Promise<YunqiSyncResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const search = new URLSearchParams();
  if (options.limit) search.set('limit', String(options.limit));
  if (options.rebuildKeywords === false) search.set('rebuild_keywords', 'false');

  const headers: HeadersInit = {};
  if (token) headers['X-Workbench-Sync-Token'] = token;

  const query = search.toString();
  const response = await fetch(`${API_BASE_URL}/api/sync/yunqi/file${query ? `?${query}` : ''}`, withSession({
    method: 'POST',
    headers,
    body: formData,
  }));

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function upload1688Links(productUrls: string[]): Promise<Link1688ImportResponse> {
  const response = await fetch(`${API_BASE_URL}/api/uploads/1688`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ product_urls: productUrls }),
  }));

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchProducts(params: ProductListParams): Promise<ProductListResponse> {
  const search = new URLSearchParams();
  search.set('page', String(params.page));
  search.set('page_size', String(params.pageSize));
  if (params.keyword) search.set('keyword', params.keyword);
  if (params.period && params.period !== '全部') search.set('period', params.period);
  if (params.category && params.category !== '全部类目') search.set('category', params.category);
  if (params.scope) search.set('scope', params.scope);
  if (params.sortBy) search.set('sort_by', params.sortBy);
  if (params.sortOrder) search.set('sort_order', params.sortOrder);
  if (params.poolAddedStart) search.set('pool_added_start', params.poolAddedStart);
  if (params.poolAddedEnd) search.set('pool_added_end', params.poolAddedEnd);
  appendRangeParams(search, 'price', params.priceRange);
  appendRangeParams(search, 'sales', params.salesRange);
  appendRangeParams(search, 'gmv', params.gmvRange);

  const response = await fetch(`${API_BASE_URL}/api/products?${search.toString()}`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchProductStats(scope: 'pool' | 'all' = 'pool'): Promise<ProductStats> {
  const search = new URLSearchParams({ scope });
  const response = await fetch(`${API_BASE_URL}/api/products/stats?${search.toString()}`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function addProductsToPool(productIds: string[]): Promise<AddProductsToPoolResponse> {
  const response = await fetch(`${API_BASE_URL}/api/products/pool`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ product_ids: productIds }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchProductCategories(scope: 'pool' | 'all' = 'pool'): Promise<ProductCategoryOption[]> {
  const search = new URLSearchParams({ scope });
  const response = await fetch(`${API_BASE_URL}/api/products/categories?${search.toString()}`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function setActive1688CaptureSession(temuProductId: string) {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/active-session`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ temu_product_id: temuProductId }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchCaptured1688Candidates(temuProductId: string): Promise<Captured1688Candidate[]> {
  const search = new URLSearchParams({ temu_product_id: temuProductId });
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/candidates?${search.toString()}`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items;
}

export async function deleteCaptured1688Candidate(candidateId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/candidates/${encodeURIComponent(candidateId)}`, withSession({
    method: 'DELETE',
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function fetchCaptured1688Materials(): Promise<Captured1688Material[]> {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/materials?limit=100`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items;
}

export async function assignCaptured1688Material(materialId: string, temuProductId: string): Promise<Captured1688Candidate> {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/materials/${encodeURIComponent(materialId)}/assign`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ temu_product_id: temuProductId }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function addCaptured1688MaterialToProductList(materialId: string): Promise<BackendProduct> {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/materials/${encodeURIComponent(materialId)}/add-to-products`, withSession({
    method: 'POST',
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function deleteCaptured1688Material(materialId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/materials/${encodeURIComponent(materialId)}`, withSession({
    method: 'DELETE',
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function deleteProduct(productId: string, scope: 'pool' | 'all' = 'pool'): Promise<void> {
  const search = new URLSearchParams({ scope });
  const response = await fetch(`${API_BASE_URL}/api/products/${productId}?${search.toString()}`, withSession({
    method: 'DELETE',
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function prepareDianxiaomiProductAttributes(
  records: LinkListRecord[],
  processNow = false,
): Promise<DianxiaomiProductAttributeQueueSummary> {
  const response = await fetch(`${API_BASE_URL}/api/exports/dianxiaomi/product-attributes/prepare`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ records, process_now: processNow }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchDianxiaomiProductAttributeStatus(
  records?: LinkListRecord[],
): Promise<DianxiaomiProductAttributeQueueSummary> {
  const response = await fetch(`${API_BASE_URL}/api/exports/dianxiaomi/product-attributes/status`, withSession(
    records
      ? {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ records }),
        }
      : {
          headers: authHeaders(),
        },
  ));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function exportDianxiaomiTemuTemplate(
  records: LinkListRecord[],
  exportMode: DianxiaomiExportMode = 'curated',
): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/api/exports/dianxiaomi/temu-semi-managed`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ records, export_mode: exportMode }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.blob();
}

export async function createDianxiaomiExportTask(
  records: LinkListRecord[],
  exportMode: DianxiaomiExportMode = 'curated',
): Promise<DianxiaomiExportTask> {
  const response = await fetch(`${API_BASE_URL}/api/exports/dianxiaomi/temu-semi-managed/tasks`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ records, export_mode: exportMode }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.item;
}

export async function fetchDianxiaomiExportTask(taskId: string): Promise<DianxiaomiExportTask> {
  const response = await fetch(`${API_BASE_URL}/api/exports/dianxiaomi/temu-semi-managed/tasks/${encodeURIComponent(taskId)}`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.item;
}

export async function fetchDianxiaomiExportTasks(): Promise<DianxiaomiExportTask[]> {
  const response = await fetch(`${API_BASE_URL}/api/exports/dianxiaomi/temu-semi-managed/tasks`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items || [];
}

export async function downloadDianxiaomiExportTask(taskId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/api/exports/dianxiaomi/temu-semi-managed/tasks/${encodeURIComponent(taskId)}/download`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.blob();
}

export async function fetchLinkListRecords(): Promise<LinkListRecord[]> {
  const response = await fetch(`${API_BASE_URL}/api/link-records`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body: LinkListRecordsResponse = await response.json();
  return body.items;
}

export async function saveLinkListRecord(record: LinkListRecord): Promise<LinkListRecord> {
  const response = await fetch(`${API_BASE_URL}/api/link-records`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ record }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function saveLinkListRecords(records: LinkListRecord[]): Promise<LinkListRecord[]> {
  const response = await fetch(`${API_BASE_URL}/api/link-records/batch`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ records }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body: LinkListRecordsResponse = await response.json();
  return body.items;
}

export async function deleteLinkListRecord(recordId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/link-records/${encodeURIComponent(recordId)}`, withSession({
    method: 'DELETE',
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function generateChatgptListingPackage(
  record: LinkListRecord,
  generateImages = true,
): Promise<ChatgptListingPackageResponse> {
  const response = await fetch(`${API_BASE_URL}/api/creative/chatgpt/listing-package`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ record, generate_images: generateImages }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchSmart1688Recommendations(
  product: Product,
  limit = 6,
  keywords: Smart1688Keyword[] = [],
): Promise<Smart1688RecommendationsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/creative/1688-smart-recommendations`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ product, keywords, limit }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchSmart1688Keywords(product: Product): Promise<Omit<Smart1688RecommendationsResponse, 'items'>> {
  const response = await fetch(`${API_BASE_URL}/api/creative/1688-smart-keywords`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ product, limit: 6 }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function uploadDianxiaomiTemplateFile(file: File): Promise<DianxiaomiTemplateImportResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE_URL}/api/uploads/dianxiaomi-template`, withSession({
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  }));

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetch1688TitleKeywords(params: {
  title: string;
  category?: string;
}): Promise<Title1688KeywordsResponse> {
  const search = new URLSearchParams();
  search.set('title', params.title);
  if (params.category) search.set('category', params.category);

  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/title-keywords?${search.toString()}`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function search1688ByImage(
  imageUrl: string,
  keyword = '',
  limit = 20,
): Promise<ImageSearch1688Response> {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/image-search`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ image_url: imageUrl, keyword, limit }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function createPluginCreativeJobs(records: LinkListRecord[]): Promise<PluginCreativeJobsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/creative/plugin/jobs`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ records, provider: 'plugin_chatgpt_web' }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function syncPluginCreativeJobs(records: LinkListRecord[]): Promise<PluginCreativeSyncResponse> {
  const response = await fetch(`${API_BASE_URL}/api/creative/plugin/jobs/sync`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ records, provider: 'plugin_chatgpt_web' }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function regeneratePluginCreativeJob(
  record: LinkListRecord,
  imageKind: string,
): Promise<{ item: PluginCreativeJob }> {
  const response = await fetch(`${API_BASE_URL}/api/creative/plugin/jobs/regenerate`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ record, image_kind: imageKind, provider: 'plugin_chatgpt_web' }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchVisualGenerationTasks(status?: string): Promise<VisualGenerationTask[]> {
  const search = new URLSearchParams();
  if (status) search.set('status', status);
  const suffix = search.toString() ? `?${search}` : '';
  const response = await fetch(`${API_BASE_URL}/api/visual/tasks${suffix}`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items || [];
}

export async function fetchVisualQueueSummary(): Promise<VisualQueueSummary> {
  const response = await fetch(`${API_BASE_URL}/api/visual/queue/summary`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function createVisualGenerationTask(payload: VisualTaskCreatePayload): Promise<VisualGenerationTask> {
  const response = await fetch(`${API_BASE_URL}/api/visual/tasks`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.item;
}

export async function fetchVisualGenerationTask(taskId: string): Promise<VisualGenerationTask> {
  const response = await fetch(`${API_BASE_URL}/api/visual/tasks/${encodeURIComponent(taskId)}`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.item;
}

export async function deleteVisualGenerationTask(taskId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/visual/tasks/${encodeURIComponent(taskId)}`, withSession({
    method: 'DELETE',
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}
export async function planVisualGenerationTask(
  taskId: string,
  payload: VisualTaskPlanPayload = {},
): Promise<VisualGenerationTask> {
  const response = await fetch(`${API_BASE_URL}/api/visual/tasks/${encodeURIComponent(taskId)}/plan`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.item;
}

export async function generateVisualGenerationTask(
  taskId: string,
  payload: VisualTaskGeneratePayload = {},
): Promise<VisualGenerationTask> {
  const response = await fetch(`${API_BASE_URL}/api/visual/tasks/${encodeURIComponent(taskId)}/generate`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.item;
}

export async function runVisualGenerationTask(
  taskId: string,
  payload: VisualTaskRunPayload = {},
): Promise<VisualGenerationRunResponse> {
  const response = await fetch(`${API_BASE_URL}/api/visual/tasks/${encodeURIComponent(taskId)}/run`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body;
}

export async function splitVisualGenerationTask(
  taskId: string,
  payload: VisualTaskSplitPayload = {},
): Promise<VisualGenerationTask> {
  const response = await fetch(`${API_BASE_URL}/api/visual/tasks/${encodeURIComponent(taskId)}/split`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.item;
}

export async function splitVisualMotherImage(payload: VisualSplitPayload): Promise<VisualGenerationTask> {
  const response = await fetch(`${API_BASE_URL}/api/visual/split`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.item;
}

export async function fetchAdminUsers(): Promise<AdminUser[]> {
  const response = await fetch(`${API_BASE_URL}/api/admin/users`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items || [];
}

export async function createAdminUser(payload: {
  username: string;
  password: string;
  displayName?: string;
  role: 'admin' | 'user';
  status: 'active' | 'disabled';
  managerId?: string;
}): Promise<AdminUser> {
  const response = await fetch(`${API_BASE_URL}/api/admin/users`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.user;
}

export async function updateAdminUser(
  userId: string,
  payload: { displayName?: string; role?: 'admin' | 'user'; status?: 'active' | 'disabled'; managerId?: string },
): Promise<AdminUser> {
  const response = await fetch(`${API_BASE_URL}/api/admin/users/${encodeURIComponent(userId)}`, withSession({
    method: 'PATCH',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.user;
}

export async function resetAdminUserPassword(userId: string, password: string): Promise<AdminUser> {
  const response = await fetch(`${API_BASE_URL}/api/admin/users/${encodeURIComponent(userId)}/password`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ password }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.user;
}

export async function deleteAdminUsers(userIds: string[]): Promise<{ deletedCount: number; deletedIds: string[] }> {
  const response = await fetch(`${API_BASE_URL}/api/admin/users/batch-delete`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ userIds }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return {
    deletedCount: body.deletedCount || 0,
    deletedIds: body.deletedIds || [],
  };
}

export async function fetchAdminUserUsageLimit(userId: string): Promise<AdminUserUsageLimit> {
  const response = await fetch(`${API_BASE_URL}/api/admin/users/${encodeURIComponent(userId)}/usage-limit`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.limit;
}

export async function updateAdminUserUsageLimit(
  userId: string,
  monthlyApiCallLimit: number,
): Promise<AdminUserUsageLimit> {
  const response = await fetch(`${API_BASE_URL}/api/admin/users/${encodeURIComponent(userId)}/usage-limit`, withSession({
    method: 'PUT',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ monthlyApiCallLimit }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.limit;
}

export async function fetchAdminSettings(): Promise<AdminSetting[]> {
  const response = await fetch(`${API_BASE_URL}/api/admin/settings`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items || [];
}

export async function fetchAdminApiUsage(): Promise<AdminApiUsageSummary> {
  const response = await fetch(`${API_BASE_URL}/api/admin/api-usage`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return {
    items: body.items || [],
    totalCalls: body.totalCalls || 0,
    exactCalls: body.exactCalls || 0,
    inferredCalls: body.inferredCalls || 0,
    byUser: body.byUser || [],
    byTeam: body.byTeam || [],
    byChannel: body.byChannel || [],
  };
}

export async function fetchAdminApiChannels(): Promise<AdminApiChannelBundle> {
  const response = await fetch(`${API_BASE_URL}/api/admin/api-channels`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return {
    channels: body.channels || [],
    routes: body.routes || [],
  };
}

export async function fetchAdminPromptConfigs(): Promise<AdminPromptConfig[]> {
  const response = await fetch(`${API_BASE_URL}/api/admin/prompt-configs`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items || [];
}

export async function updateAdminApiChannels(items: AdminApiChannelUpdateItem[]): Promise<AdminApiChannelBundle> {
  const response = await fetch(`${API_BASE_URL}/api/admin/api-channels`, withSession({
    method: 'PUT',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ items }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return {
    channels: body.channels || [],
    routes: body.routes || [],
  };
}

export async function fetchAdminUserApiCredentials(userId: string): Promise<AdminUserApiCredential[]> {
  const response = await fetch(`${API_BASE_URL}/api/admin/users/${encodeURIComponent(userId)}/api-credentials`, withSession({
    headers: authHeaders(),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items || [];
}

export async function updateAdminUserApiCredentials(
  userId: string,
  items: AdminUserApiCredentialUpdateItem[],
): Promise<AdminUserApiCredential[]> {
  const response = await fetch(`${API_BASE_URL}/api/admin/users/${encodeURIComponent(userId)}/api-credentials`, withSession({
    method: 'PUT',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ items }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items || [];
}

export async function applyAdminApiRoute(payload: {
  stage: string;
  channelId: string;
  model?: string;
}): Promise<AdminApiChannelBundle> {
  const response = await fetch(`${API_BASE_URL}/api/admin/api-channels/apply`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return {
    channels: body.channels || [],
    routes: body.routes || [],
  };
}

export async function applyAdminApiRoutesToAll(payload: {
  channelId: string;
  textModel?: string;
  imageModel?: string;
}): Promise<AdminApiChannelBundle> {
  const response = await fetch(`${API_BASE_URL}/api/admin/api-channels/apply-all`, withSession({
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return {
    channels: body.channels || [],
    routes: body.routes || [],
  };
}

export async function updateAdminSettings(items: AdminSettingsUpdateItem[]): Promise<AdminSetting[]> {
  const response = await fetch(`${API_BASE_URL}/api/admin/settings`, withSession({
    method: 'PUT',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ items }),
  }));
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items || [];
}

export function mapBackendProduct(product: BackendProduct): Product {
  return {
    id: product.id,
    sourceType: product.source_type === '1688' || product.source_type === 'temu' || product.source_type === 'custom' ? product.source_type : 'yunqi',
    sourceProductId: product.source_product_id,
    title: product.title,
    titleEn: product.title_en || undefined,
    category: product.category_path || product.category_level1 || product.category_level2 || '未分类',
    categoryLevel1: product.category_level1 || undefined,
    categoryLevel2: product.category_level2 || undefined,
    categoryPath: product.category_path || undefined,
    price: product.price_usd,
    sales: product.weekly_sales || product.monthly_sales,
    weeklySales: product.weekly_sales,
    monthlySales: product.monthly_sales,
    gmv: product.gmv_usd,
    reviewCount: product.review_count,
    listedAt: product.listing_time ? product.listing_time.slice(0, 10) : '',
    selectedAt: product.pool_added_at ? product.pool_added_at.slice(0, 10) : undefined,
    growthRate: 0,
    sourceRow: product.source_row_index,
    period: product.weekly_sales > 0 ? '近7天' : '近30天',
    status: product.status,
    inProductPool: Boolean(product.in_product_pool),
    imageTone: pickImageTone(product.category_level1 || product.category_path || ''),
    mainImageUrl: product.main_image_url || undefined,
    sourceUrl: product.source_url || undefined,
  };
}

async function readErrorMessage(response: Response): Promise<string> {
  if (response.status === 401) {
    clearLegacyAuthToken();
  }
  try {
    const body = await response.json();
    return body.detail || response.statusText;
  } catch {
    return response.statusText;
  }
}

function pickImageTone(category: string): Product['imageTone'] {
  if (category.includes('厨房') || category.includes('家居')) return 'red';
  if (category.includes('宠物') || category.includes('珠宝')) return 'green';
  return 'blue';
}

function appendRangeParams(search: URLSearchParams, key: string, value?: string) {
  const range = parseRangeText(value);
  if (range.min !== undefined) search.set(`${key}_min`, String(range.min));
  if (range.max !== undefined) search.set(`${key}_max`, String(range.max));
}

function parseRangeText(value?: string): { min?: number; max?: number } {
  if (!value) return {};

  const normalized = value
    .replace(/[,$，￥¥]/g, '')
    .replace(/\s+/g, '')
    .replace(/[~～—至到]/g, '-');

  if (!normalized || normalized === '不限') return {};

  if (normalized.startsWith('>=')) return numberRange(normalized.slice(2), undefined);
  if (normalized.startsWith('>')) return numberRange(normalized.slice(1), undefined);
  if (normalized.startsWith('<=')) return numberRange(undefined, normalized.slice(2));
  if (normalized.startsWith('<')) return numberRange(undefined, normalized.slice(1));

  const [rawMin, rawMax] = normalized.split('-', 2);
  if (rawMax !== undefined) return numberRange(rawMin, rawMax);
  return numberRange(rawMin, undefined);
}

function numberRange(rawMin?: string, rawMax?: string): { min?: number; max?: number } {
  const min = toOptionalNumber(rawMin);
  const max = toOptionalNumber(rawMax);
  if (min !== undefined && max !== undefined && min > max) {
    return { min: max, max: min };
  }
  return { min, max };
}

function toOptionalNumber(value?: string): number | undefined {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}
