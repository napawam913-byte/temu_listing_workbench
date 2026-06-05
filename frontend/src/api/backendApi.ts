import type { Product } from '../types/product';
import type { LinkListRecord } from '../types/linkList';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

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
  scope?: 'pool' | 'all';
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
  level: 1 | 2;
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

export type Link1688ImportResponse = YunqiImportResponse;

export type DianxiaomiExportMode = 'distribution' | 'curated';

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

export async function uploadYunqiFile(file: File): Promise<YunqiImportResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE_URL}/api/uploads/yunqi`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function upload1688Links(productUrls: string[]): Promise<Link1688ImportResponse> {
  const response = await fetch(`${API_BASE_URL}/api/uploads/1688`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_urls: productUrls }),
  });

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
  appendRangeParams(search, 'price', params.priceRange);
  appendRangeParams(search, 'sales', params.salesRange);
  appendRangeParams(search, 'gmv', params.gmvRange);

  const response = await fetch(`${API_BASE_URL}/api/products?${search.toString()}`);
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchProductStats(scope: 'pool' | 'all' = 'pool'): Promise<ProductStats> {
  const search = new URLSearchParams({ scope });
  const response = await fetch(`${API_BASE_URL}/api/products/stats?${search.toString()}`);
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function addProductsToPool(productIds: string[]): Promise<AddProductsToPoolResponse> {
  const response = await fetch(`${API_BASE_URL}/api/products/pool`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_ids: productIds }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchProductCategories(): Promise<ProductCategoryOption[]> {
  const response = await fetch(`${API_BASE_URL}/api/products/categories`);
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function setActive1688CaptureSession(temuProductId: string) {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/active-session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ temu_product_id: temuProductId }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchCaptured1688Candidates(temuProductId: string): Promise<Captured1688Candidate[]> {
  const search = new URLSearchParams({ temu_product_id: temuProductId });
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/candidates?${search.toString()}`);
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items;
}

export async function deleteCaptured1688Candidate(candidateId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/candidates/${encodeURIComponent(candidateId)}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function fetchCaptured1688Materials(): Promise<Captured1688Material[]> {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/materials?limit=100`);
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body = await response.json();
  return body.items;
}

export async function assignCaptured1688Material(materialId: string, temuProductId: string): Promise<Captured1688Candidate> {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/materials/${encodeURIComponent(materialId)}/assign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ temu_product_id: temuProductId }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function addCaptured1688MaterialToProductList(materialId: string): Promise<BackendProduct> {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/materials/${encodeURIComponent(materialId)}/add-to-products`, {
    method: 'POST',
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function deleteCaptured1688Material(materialId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/materials/${encodeURIComponent(materialId)}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function deleteProduct(productId: string, scope: 'pool' | 'all' = 'pool'): Promise<void> {
  const search = new URLSearchParams({ scope });
  const response = await fetch(`${API_BASE_URL}/api/products/${productId}?${search.toString()}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function exportDianxiaomiTemuTemplate(
  records: LinkListRecord[],
  exportMode: DianxiaomiExportMode = 'curated',
): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/api/exports/dianxiaomi/temu-semi-managed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ records, export_mode: exportMode }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.blob();
}

export async function fetchLinkListRecords(): Promise<LinkListRecord[]> {
  const response = await fetch(`${API_BASE_URL}/api/link-records`);
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body: LinkListRecordsResponse = await response.json();
  return body.items;
}

export async function saveLinkListRecord(record: LinkListRecord): Promise<LinkListRecord> {
  const response = await fetch(`${API_BASE_URL}/api/link-records`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function saveLinkListRecords(records: LinkListRecord[]): Promise<LinkListRecord[]> {
  const response = await fetch(`${API_BASE_URL}/api/link-records/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ records }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const body: LinkListRecordsResponse = await response.json();
  return body.items;
}

export async function deleteLinkListRecord(recordId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/link-records/${encodeURIComponent(recordId)}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function generateChatgptListingPackage(
  record: LinkListRecord,
  generateImages = true,
): Promise<ChatgptListingPackageResponse> {
  const response = await fetch(`${API_BASE_URL}/api/creative/chatgpt/listing-package`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record, generate_images: generateImages }),
  });
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
  const response = await fetch(`${API_BASE_URL}/api/creative/1688-smart-recommendations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product, keywords, limit }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function fetchSmart1688Keywords(product: Product): Promise<Omit<Smart1688RecommendationsResponse, 'items'>> {
  const response = await fetch(`${API_BASE_URL}/api/creative/1688-smart-keywords`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product, limit: 6 }),
  });
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
  const response = await fetch(`${API_BASE_URL}/api/sourcing/1688/image-search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image_url: imageUrl, keyword, limit }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function createPluginCreativeJobs(records: LinkListRecord[]): Promise<PluginCreativeJobsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/creative/plugin/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ records, provider: 'plugin_chatgpt_web' }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

export async function syncPluginCreativeJobs(records: LinkListRecord[]): Promise<PluginCreativeSyncResponse> {
  const response = await fetch(`${API_BASE_URL}/api/creative/plugin/jobs/sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ records, provider: 'plugin_chatgpt_web' }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
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
