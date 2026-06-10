import {
  Button,
  Card,
  Drawer,
  Empty,
  Form,
  Image,
  Input,
  Layout,
  Modal,
  Popover,
  Select,
  Space,
  Statistic,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  AppstoreOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  EyeOutlined,
  HistoryOutlined,
  PictureOutlined,
  ReloadOutlined,
  SwapOutlined,
  SyncOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Key } from 'react';
import type { SortOrder } from 'antd/es/table/interface';
import {
  addProductsToPool,
  deleteProduct as deleteBackendProduct,
  deleteLinkListRecord,
  exportDianxiaomiTemuTemplate,
  fetchLinkListRecords,
  fetchProductCategories,
  fetchProductStats,
  fetchProducts,
  mapBackendProduct,
  saveLinkListRecord,
  saveLinkListRecords,
  regeneratePluginCreativeJob,
  syncPluginCreativeJobs,
  upload1688Links,
  uploadYunqiFile,
} from '../api/backendApi';
import type { CurrentUser, ProductCategoryOption, ProductStats } from '../api/backendApi';
import { DataImportModal } from '../components/DataImportModal';
import { ProductDetailDrawer } from '../components/ProductDetailDrawer';
import { ProductTable } from '../components/ProductTable';
import { AdminPage } from './AdminPage';
import { mockProducts } from '../mock/products';
import type { LinkListCreativeJobSummary, LinkListImageAsset, LinkListImageSlot, LinkListRecord } from '../types/linkList';
import type { Product, ProductSourceType, SourcingCandidate } from '../types/product';

const { Header, Content } = Layout;
const { Text } = Typography;
const ALL_CATEGORY_VALUE = '全部类目';

type Filters = {
  keyword?: string;
  period?: Product['period'] | '全部';
  category?: string;
  priceRange?: string;
  salesRange?: string;
  gmvRange?: string;
};

const defaultFilters: Filters = {
  period: '全部',
  category: ALL_CATEGORY_VALUE,
};

const PRODUCT_ROUTE_PREFIX = '#/products/';

type ProductRoute = {
  sourceType: ProductSourceType;
  sourceProductId: string;
};

type WorkbenchTab = 'data' | 'sourcing' | 'links' | 'admin';
type VisualPublishMode = 'main_multi' | 'sku_adapt' | 'single_refine';

type VisualQueueItem = {
  id: string;
  recordId: string;
  productTitle: string;
  taskId: string;
  taskName: string;
  typeLabel: string;
  mode: VisualPublishMode;
  modeLabel: string;
  generationMode: string;
  mixPolicy: string;
  requestedCount: number;
  moduleCount: number;
  completedCount: number;
  statusLabel: string;
  statusColor: string;
  styleProfileId: string;
  styleLockLabel: string;
  styleLockStatus: string;
  referenceImageUrl?: string;
  selectedSkuIds?: string[];
  selectedSlotIds?: string[];
  createdAt: string;
  modules: Array<{
    id: string;
    order: number;
    skuEntryId?: string;
    title: string;
    targetLabel: string;
    imageKind?: string;
    imageUrl?: string;
    sourceLabel: string;
    statusLabel: string;
    statusColor: string;
  }>;
};

const LINK_LIST_STORAGE_KEY = 'temuListingWorkbenchLinkListRecords';
const CURATED_EXPORT_IMAGE_COUNT = 8;
const MAX_EXPORT_CAROUSEL_IMAGE_COUNT = 10;
const PRODUCT_IMAGE_SLOT_ROLES = [
  { kind: '01-hero-main', label: '主图' },
  { kind: '02-effect', label: '效果图' },
  { kind: '03-person-use', label: '人物场景' },
  { kind: '04-room-scene', label: '场景图' },
  { kind: '05-detail-material', label: '细节图' },
  { kind: '06-detail-size', label: '尺寸结构' },
  { kind: '07-comparison', label: '对比图' },
  { kind: '08-package-lineup', label: '组合包装' },
];

function getLinkListStorageKey(userId: string) {
  return `${LINK_LIST_STORAGE_KEY}:${userId}`;
}

function readLinkListRecords(userId: string): LinkListRecord[] {
  try {
    const value = JSON.parse(localStorage.getItem(getLinkListStorageKey(userId)) || '[]');
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function writeLinkListRecords(records: LinkListRecord[], userId: string) {
  localStorage.setItem(getLinkListStorageKey(userId), JSON.stringify(records));
}

function formatRecordTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
}

function getProductSourceType(product: Product): ProductSourceType {
  return product.sourceType || 'yunqi';
}

function getProductSourceProductId(product: Product) {
  return product.sourceProductId || product.id;
}

function buildProductRoute(product: Product) {
  return `${PRODUCT_ROUTE_PREFIX}${encodeURIComponent(getProductSourceType(product))}/${encodeURIComponent(
    getProductSourceProductId(product),
  )}`;
}

function parseProductRoute(hash = window.location.hash): ProductRoute | undefined {
  if (!hash.startsWith(PRODUCT_ROUTE_PREFIX)) return undefined;

  const path = hash.slice(PRODUCT_ROUTE_PREFIX.length);
  const separatorIndex = path.indexOf('/');
  if (separatorIndex <= 0 || separatorIndex >= path.length - 1) return undefined;

  const sourceType = decodeURIComponent(path.slice(0, separatorIndex)) as ProductSourceType;
  const sourceProductId = decodeURIComponent(path.slice(separatorIndex + 1));
  if (!sourceType || !sourceProductId) return undefined;

  return { sourceType, sourceProductId };
}

function matchesProductRoute(product: Product, route: ProductRoute) {
  return (
    getProductSourceType(product) === route.sourceType &&
    getProductSourceProductId(product) === route.sourceProductId
  );
}

function syncProductRoute(product: Product) {
  const nextHash = buildProductRoute(product);
  if (window.location.hash === nextHash) return;
  window.history.pushState(null, '', `${window.location.pathname}${window.location.search}${nextHash}`);
}

function clearProductRoute() {
  if (!parseProductRoute()) return;
  window.history.pushState(null, '', `${window.location.pathname}${window.location.search}`);
}

const defaultStats: ProductStats = {
  active_count: mockProducts.filter((product) => product.status !== 'deleted').length,
  recent_7_count: mockProducts.filter((product) => product.period === '近7天').length,
  recent_30_count: mockProducts.filter((product) => product.period === '近30天').length,
  deleted_count: mockProducts.filter((product) => product.status === 'deleted').length,
};

function matchesRange(value: number, rangeText?: string) {
  const range = parseRangeText(rangeText);
  if (range.min !== undefined && value < range.min) return false;
  if (range.max !== undefined && value > range.max) return false;
  return true;
}

function parseRangeText(value?: string): { min?: number; max?: number } {
  if (!value) return {};
  const normalized = value
    .replace(/[,$，￥¥]/g, '')
    .replace(/\s+/g, '')
    .replace(/[~～—至到]/g, '-');
  if (!normalized || normalized === '不限') return {};
  const [rawMin, rawMax] = normalized.split('-', 2);
  const min = toOptionalNumber(rawMin);
  const max = toOptionalNumber(rawMax);
  if (min !== undefined && max !== undefined && min > max) return { min: max, max: min };
  return { min, max };
}

function toOptionalNumber(value?: string) {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function toBackendPriceSortOrder(order?: SortOrder) {
  if (order === 'ascend') return 'asc';
  if (order === 'descend') return 'desc';
  return undefined;
}

function matchesCategoryQuery(category: ProductCategoryOption, query: string, parentLabel = '') {
  if (!query) return true;
  const haystack = `${parentLabel} ${category.label} ${category.value}`.toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function getCategoryDisplayLabel(categories: ProductCategoryOption[], value?: string) {
  if (!value || value === ALL_CATEGORY_VALUE) return ALL_CATEGORY_VALUE;
  for (const category of categories) {
    if (category.value === value) return category.label;
    const child = (category.children || []).find((item) => item.value === value);
    if (child) return `${category.label} / ${child.label}`;
  }
  return value;
}

function getSelectedLevel1Value(categories: ProductCategoryOption[], value?: string) {
  if (!value || value === ALL_CATEGORY_VALUE) return undefined;
  const direct = categories.find((category) => category.value === value);
  if (direct) return direct.value;
  return categories.find((category) => (category.children || []).some((child) => child.value === value))?.value;
}

function CategoryCascaderFilter({
  categories,
  onChange,
  value,
}: {
  categories: ProductCategoryOption[];
  onChange?: (value?: string) => void;
  value?: string;
}) {
  const [open, setOpen] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [activeLevel1Value, setActiveLevel1Value] = useState<string>();
  const selectedLevel1Value = getSelectedLevel1Value(categories, value);
  const selectedDisplayLabel = getCategoryDisplayLabel(categories, value);
  const normalizedSearchText = searchText.trim();

  const filteredCategories = useMemo(() => {
    if (!normalizedSearchText) return categories;
    return categories
      .map((category) => {
        const children = (category.children || []).filter((child) =>
          matchesCategoryQuery(child, normalizedSearchText, category.label),
        );
        if (matchesCategoryQuery(category, normalizedSearchText) || children.length > 0) {
          return { ...category, children: children.length > 0 ? children : category.children };
        }
        return undefined;
      })
      .filter(Boolean) as ProductCategoryOption[];
  }, [categories, normalizedSearchText]);

  const activeLevel1 =
    filteredCategories.find((category) => category.value === activeLevel1Value) ||
    filteredCategories.find((category) => category.value === selectedLevel1Value) ||
    filteredCategories[0];

  useEffect(() => {
    const nextActiveValue =
      filteredCategories.find((category) => category.value === activeLevel1Value)?.value ||
      filteredCategories.find((category) => category.value === selectedLevel1Value)?.value ||
      filteredCategories[0]?.value;
    if (nextActiveValue && nextActiveValue !== activeLevel1Value) {
      setActiveLevel1Value(nextActiveValue);
    }
  }, [activeLevel1Value, filteredCategories, selectedLevel1Value]);

  const selectCategory = (nextValue?: string) => {
    onChange?.(nextValue || ALL_CATEGORY_VALUE);
    setOpen(false);
  };

  const panel = (
    <div className="category-cascader-panel">
      <div className="category-cascader-search">
        <Input
          allowClear
          placeholder="搜索一级/二级类目"
          size="small"
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
        />
      </div>
      <div className="category-cascader-body">
        <div className="category-cascader-column category-cascader-level1">
          <button
            className={`category-cascader-row ${!value || value === ALL_CATEGORY_VALUE ? 'category-cascader-selected' : ''}`}
            type="button"
            onClick={() => selectCategory(ALL_CATEGORY_VALUE)}
          >
            <span className="category-check" />
            <span className="category-cascader-name">全分类</span>
          </button>
          {filteredCategories.map((category) => {
            const active = activeLevel1?.value === category.value;
            const selected = value === category.value || selectedLevel1Value === category.value;
            return (
              <button
                className={`category-cascader-row ${active ? 'category-cascader-active' : ''} ${
                  selected ? 'category-cascader-selected' : ''
                }`}
                key={category.value}
                type="button"
                onClick={() => {
                  setActiveLevel1Value(category.value);
                }}
                onMouseEnter={() => setActiveLevel1Value(category.value)}
              >
                <span className="category-check" />
                <span className="category-cascader-name">{category.label}</span>
                <span className="category-cascader-count">{category.count}</span>
                <span className="category-cascader-arrow">›</span>
              </button>
            );
          })}
        </div>
        <div className="category-cascader-column">
          {activeLevel1 ? (
            <>
              <div className="category-cascader-group-title">{activeLevel1.label}</div>
              <button
                className={`category-cascader-row ${value === activeLevel1.value ? 'category-cascader-selected' : ''}`}
                type="button"
                onClick={() => selectCategory(activeLevel1.value)}
              >
                <span className="category-check" />
                <span className="category-cascader-name">全部 {activeLevel1.label}</span>
                <span className="category-cascader-count">{activeLevel1.count}</span>
              </button>
              {(activeLevel1.children || []).map((child) => (
                <button
                  className={`category-cascader-row ${value === child.value ? 'category-cascader-selected' : ''}`}
                  key={child.value}
                  type="button"
                  onClick={() => selectCategory(child.value)}
                >
                  <span className="category-check" />
                  <span className="category-cascader-name">{child.label}</span>
                  <span className="category-cascader-count">{child.count}</span>
                </button>
              ))}
              {(activeLevel1.children || []).length === 0 ? (
                <div className="category-cascader-empty">暂无二级类目</div>
              ) : null}
            </>
          ) : (
            <div className="category-cascader-empty">暂无匹配类目</div>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <Popover
      arrow={false}
      content={panel}
      open={open}
      overlayClassName="category-cascader-popover"
      placement="bottomLeft"
      trigger="click"
      onOpenChange={setOpen}
    >
      <button className="category-cascader-trigger" type="button">
        <span className={value && value !== ALL_CATEGORY_VALUE ? 'category-cascader-trigger-value' : 'category-cascader-placeholder'}>
          {selectedDisplayLabel}
        </span>
        {value && value !== ALL_CATEGORY_VALUE ? (
          <span
            className="category-cascader-clear"
            role="button"
            tabIndex={0}
            onClick={(event) => {
              event.stopPropagation();
              selectCategory(ALL_CATEGORY_VALUE);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                event.stopPropagation();
                selectCategory(ALL_CATEGORY_VALUE);
              }
            }}
          >
            ×
          </span>
        ) : null}
        <span className="category-cascader-trigger-arrow">▾</span>
      </button>
    </Popover>
  );
}

function getAssetDisplayUrl(asset?: LinkListRecord['mainImage']) {
  return (
    asset?.editedCloudUrl ||
    asset?.editedUrl ||
    asset?.displayCloudUrl ||
    asset?.displayUrl ||
    asset?.sourceCloudUrl ||
    asset?.sourceUrl
  );
}

function getRecordMainImageUrl(record?: LinkListRecord) {
  if (!record) return undefined;
  const mainSlot = getRecordImageSlots(record).find((slot) => slot.type === 'main');
  const mainSlotAsset = mainSlot?.assetId ? getRecordAssetMap(record).get(mainSlot.assetId) : undefined;
  const mainSlotUrl =
    mainSlotAsset?.role === 'product-main' || mainSlotAsset?.role === 'product-material'
      ? getAssetDisplayUrl(mainSlotAsset)
      : undefined;
  if (mainSlotUrl) return mainSlotUrl;

  const mainImage = record.mainImage;
  const curatedMainImage =
    mainImage?.editedCloudUrl || mainImage?.editedUrl || mainImage?.displayCloudUrl || mainImage?.displayUrl;
  const heroJobImage = record.creativeJobs?.find((job) => job.imageIndex === 1 && job.resultImageUrl)?.resultImageUrl;
  return curatedMainImage || heroJobImage || mainImage?.sourceCloudUrl || mainImage?.sourceUrl || record.productImageUrl;
}

function getSkuDisplayImageUrl(entry: LinkListRecord['skuEntries'][number]) {
  return getAssetDisplayUrl(entry.imageAsset) || entry.imageUrl;
}

function collectRecordImageAssets(record?: LinkListRecord): LinkListImageAsset[] {
  if (!record) return [];
  const assets: LinkListImageAsset[] = [];
  const seenIds = new Set<string>();
  const addAsset = (asset?: LinkListImageAsset) => {
    if (!asset?.id || seenIds.has(asset.id) || !getAssetDisplayUrl(asset)) return;
    seenIds.add(asset.id);
    assets.push(asset);
  };

  addAsset(record.mainImage);
  (record.productMaterialImages || []).forEach(addAsset);
  (record.sourceLinks || []).forEach((source, index) => {
    addAsset({
      id: `${record.id}-source-image-${source.id || index + 1}`,
      role: 'product-material',
      sourceUrl: source.imageUrl,
      displayUrl: source.imageUrl,
      alt: source.title,
    });
  });
  (record.skuEntries || []).forEach((entry) => {
    addAsset(entry.imageAsset);
    if (entry.imageUrl) {
      addAsset({
        id: `${record.id}-sku-url-${entry.id}`,
        role: 'sales-sku',
        sourceUrl: entry.imageUrl,
        displayUrl: entry.imageUrl,
        alt: entry.name,
      });
    }
  });
  (record.creativeJobs || []).forEach((job) => {
    if (!job.resultImageUrl) return;
    addAsset({
      id: `${record.id}-creative-job-${job.id}`,
      role: job.targetSkuEntryId ? 'sales-sku' : 'product-material',
      editedUrl: job.resultImageUrl,
      editedCloudUrl: job.resultImageUrl,
      alt: job.imageLabel,
    });
  });

  return assets;
}

function getRecordAssetMap(record?: LinkListRecord) {
  const assetMap = new Map<string, LinkListImageAsset>();
  collectRecordImageAssets(record).forEach((asset) => assetMap.set(asset.id, asset));
  return assetMap;
}

function getDefaultRecordImageSlots(record: LinkListRecord): LinkListImageSlot[] {
  const assets = collectRecordImageAssets(record).filter(
    (asset) => asset.role === 'product-main' || asset.role === 'product-material',
  );
  const mainAsset =
    (record.mainImage?.id ? assets.find((asset) => asset.id === record.mainImage?.id) : undefined) ||
    assets.find((asset) => asset.role === 'product-main') ||
    assets.find((asset) => asset.role === 'product-material');
  const carouselAssets = [
    mainAsset,
    ...assets.filter((asset) => asset.role === 'product-material' && asset.id !== mainAsset?.id),
  ].filter((asset): asset is LinkListImageAsset => Boolean(asset && getAssetDisplayUrl(asset)));
  const slots: LinkListImageSlot[] = [];

  slots.push({
    id: `${record.id}-slot-main`,
    type: 'main',
    order: 0,
    assetId: mainAsset?.id,
  });
  carouselAssets.slice(0, MAX_EXPORT_CAROUSEL_IMAGE_COUNT).forEach((asset, index) => {
    slots.push({
      id: `${record.id}-slot-carousel-${index + 1}`,
      type: 'carousel',
      order: index + 1,
      assetId: asset.id,
    });
  });

  return slots;
}

function getRecordImageSlots(record?: LinkListRecord): LinkListImageSlot[] {
  if (!record) return [];
  const savedSlots = (record.imageSlots || []).filter((slot) => slot && slot.id);
  const slots = savedSlots.length > 0 ? [...savedSlots] : getDefaultRecordImageSlots(record);
  if (!slots.some((slot) => slot.type === 'main')) {
    const defaultMainSlot = getDefaultRecordImageSlots(record).find((slot) => slot.type === 'main');
    if (defaultMainSlot) slots.unshift(defaultMainSlot);
  }
  return slots
    .map((slot, index) => ({
      ...slot,
      order: Number.isFinite(slot.order) ? slot.order : index,
    }))
    .sort((left, right) => left.order - right.order);
}

function getRecordPreviewGalleryItems(record?: LinkListRecord) {
  if (!record) return [];
  const assetMap = getRecordAssetMap(record);
  const seenUrls = new Set<string>();
  return getRecordImageSlots(record)
    .filter((slot) => slot.type === 'main' || slot.type === 'carousel')
    .map((slot) => {
      const asset = slot.assetId ? assetMap.get(slot.assetId) : undefined;
      if (asset?.role === 'sales-sku') return undefined;
      const imageUrl = getAssetDisplayUrl(asset);
      return imageUrl ? { slot, asset, imageUrl } : undefined;
    })
    .filter((item): item is { slot: LinkListImageSlot; asset: LinkListImageAsset | undefined; imageUrl: string } => {
      if (!item || seenUrls.has(item.imageUrl)) return false;
      seenUrls.add(item.imageUrl);
      return true;
    });
}

function getRecordProductImageGenerationCount(record?: LinkListRecord) {
  if (!record) return CURATED_EXPORT_IMAGE_COUNT;
  const count = Number(record.productImageGenerationCount);
  if (Number.isFinite(count) && count > 0) {
    return Math.max(1, Math.min(CURATED_EXPORT_IMAGE_COUNT, Math.floor(count)));
  }
  const carouselCount = getRecordImageSlots(record).filter((slot) => slot.type === 'carousel').length;
  return Math.max(1, Math.min(CURATED_EXPORT_IMAGE_COUNT, carouselCount || CURATED_EXPORT_IMAGE_COUNT));
}

function getProductImageKindByOrder(order: number) {
  return PRODUCT_IMAGE_SLOT_ROLES[Math.max(0, Math.min(PRODUCT_IMAGE_SLOT_ROLES.length - 1, order - 1))]?.kind;
}

function getProductImageSlotLabel(order: number) {
  return PRODUCT_IMAGE_SLOT_ROLES[Math.max(0, Math.min(PRODUCT_IMAGE_SLOT_ROLES.length - 1, order - 1))]?.label || `图 ${order}`;
}

function getProductImageKindForSlot(slot?: LinkListImageSlot) {
  if (!slot) return undefined;
  const order = slot.type === 'main' ? 1 : slot.order;
  return getProductImageKindByOrder(order);
}

function getProductSlotJob(record: LinkListRecord, imageKind?: string) {
  if (!imageKind) return undefined;
  return (record.creativeJobs || []).find((job) => job.imageKind === imageKind && !job.targetSkuEntryId);
}

function getRecordProductImageSlotItems(record: LinkListRecord) {
  const assetMap = getRecordAssetMap(record);
  const carouselSlots = getRecordImageSlots(record).filter((slot) => slot.type === 'carousel');
  const slotByOrder = new Map(carouselSlots.map((slot) => [slot.order, slot]));
  const count = getRecordProductImageGenerationCount(record);

  return Array.from({ length: count }, (_, index) => {
    const order = index + 1;
    const slot =
      slotByOrder.get(order) ||
      ({
        id: `${record.id}-slot-carousel-${order}`,
        type: 'carousel',
        order,
      } as LinkListImageSlot);
    const asset = slot.assetId ? assetMap.get(slot.assetId) : undefined;
    const imageUrl = asset?.role === 'sales-sku' ? undefined : getAssetDisplayUrl(asset);
    const imageKind = getProductImageKindByOrder(order);
    const job = getProductSlotJob(record, imageKind);
    return {
      slot,
      asset,
      imageUrl,
      order,
      imageKind,
      imageLabel: getProductImageSlotLabel(order),
      job,
    };
  });
}

function getImageAssetOptions(record?: LinkListRecord) {
  const seenUrls = new Set<string>();
  return collectRecordImageAssets(record)
    .filter((asset) => asset.role === 'product-main' || asset.role === 'product-material')
    .map((asset) => ({ asset, imageUrl: getAssetDisplayUrl(asset) }))
    .filter((item): item is { asset: LinkListImageAsset; imageUrl: string } => {
      if (!item.imageUrl || seenUrls.has(item.imageUrl)) return false;
      seenUrls.add(item.imageUrl);
      return true;
    });
}

function getVisualReferenceImageOptions(record?: LinkListRecord) {
  const seenUrls = new Set<string>();
  return collectRecordImageAssets(record)
    .map((asset) => ({ asset, imageUrl: getAssetDisplayUrl(asset) }))
    .filter((item): item is { asset: LinkListImageAsset; imageUrl: string } => {
      if (!item.imageUrl || seenUrls.has(item.imageUrl)) return false;
      seenUrls.add(item.imageUrl);
      return true;
    });
}

function updateRecordImageSlot(record: LinkListRecord, slotId: string, assetId: string): LinkListRecord {
  const imageSlots = getRecordImageSlots(record).map((slot) =>
    slot.id === slotId
      ? {
          ...slot,
          assetId,
        }
      : slot,
  );

  return {
    ...record,
    schemaVersion: 3,
    imageSlots,
  };
}

function getImageSlotLabel(slot?: LinkListImageSlot) {
  if (!slot) return '图片';
  if (slot.type === 'main') return '主图';
  if (slot.type === 'sku') return 'SKU 图';
  return `轮播图 ${slot.order}`;
}

function getRecordGeneratedImageUrls(record?: LinkListRecord) {
  return getRecordPreviewGalleryItems(record)
    .map((item) => item.imageUrl)
    .slice(0, MAX_EXPORT_CAROUSEL_IMAGE_COUNT);
}

function formatPreviewPrice(record?: LinkListRecord) {
  const prices = (record?.skuEntries || [])
    .map((entry) => entry.price)
    .filter((price): price is number => typeof price === 'number' && Number.isFinite(price) && price > 0);
  if (prices.length === 0) return 'CN¥--';

  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const format = (price: number) => `CN¥${price.toFixed(price % 1 === 0 ? 0 : 2)}`;
  return minPrice === maxPrice ? format(minPrice) : `${format(minPrice)} - ${format(maxPrice)}`;
}

function getCreativeJobSummary(record: LinkListRecord) {
  const jobs = record.creativeJobs || [];
  const completed = jobs.filter((job) => job.status === 'completed' && job.resultImageUrl).length;
  const running = jobs.filter((job) => job.status === 'running').length;
  const queued = jobs.filter((job) => job.status === 'queued').length;
  const failed = jobs.filter((job) => job.status === 'failed').length;
  return { total: jobs.length, completed, running, queued, failed };
}

function getImageTaskStatusText(status?: string) {
  if (status === 'queued') return '排队中';
  if (status === 'running') return '生成中';
  if (status === 'completed') return '已完成';
  if (status === 'done') return '已统一';
  if (status === 'failed') return '生成失败';
  return '待修图';
}

function getImageTaskStatusMeta(status?: string, hasImage = false) {
  if (status === 'queued') return { label: '队列中', color: 'blue', icon: <ClockCircleOutlined /> };
  if (status === 'running') return { label: '生成中', color: 'gold', icon: <SyncOutlined spin /> };
  if (status === 'completed') {
    return { label: hasImage ? '已完成' : '待同步', color: hasImage ? 'green' : 'gold', icon: <CheckCircleOutlined /> };
  }
  if (status === 'done') return { label: '已统一', color: 'green', icon: <CheckCircleOutlined /> };
  if (status === 'failed') return { label: '失败', color: 'red', icon: <WarningOutlined /> };
  if (hasImage) return { label: '可导出', color: 'green', icon: <CheckCircleOutlined /> };
  return { label: '未生成', color: 'default', icon: <ClockCircleOutlined /> };
}

function getImageAssetSourceMeta(asset?: LinkListImageAsset, job?: LinkListCreativeJobSummary) {
  if (job?.resultImageUrl || asset?.editedCloudUrl || asset?.editedUrl) {
    return { label: 'AI 结果', color: 'purple' };
  }
  if (asset?.displayCloudUrl || asset?.sourceCloudUrl) {
    return { label: '云端图', color: 'cyan' };
  }
  if (asset?.displayUrl || asset?.sourceUrl) {
    return { label: '采集图', color: 'blue' };
  }
  return { label: '待图片', color: 'default' };
}

function getRecordProductImageProgress(record: LinkListRecord) {
  const slots = getRecordProductImageSlotItems(record);
  const ready = slots.filter((item) => Boolean(item.imageUrl)).length;
  const queued = slots.filter((item) => item.job?.status === 'queued').length;
  const running = slots.filter((item) => item.job?.status === 'running').length;
  const failed = slots.filter((item) => item.job?.status === 'failed').length;
  return {
    total: slots.length,
    ready,
    queued,
    running,
    failed,
  };
}

function getVisualModuleStatusMeta(status: string) {
  if (status === 'queued') return { label: '待组批', color: 'blue', icon: <ClockCircleOutlined /> };
  if (status === 'running') return { label: '生成中', color: 'gold', icon: <SyncOutlined spin /> };
  if (status === 'failed') return { label: '失败', color: 'red', icon: <WarningOutlined /> };
  if (status === 'manual') return { label: '人工替换', color: 'purple', icon: <SwapOutlined /> };
  if (status === 'completed') return { label: '已完成', color: 'green', icon: <CheckCircleOutlined /> };
  return { label: '待配置', color: 'default', icon: <ClockCircleOutlined /> };
}

function getVisualPackageStatusMeta(modules: Array<{ status: string }>) {
  const total = modules.length;
  const completed = modules.filter((module) => module.status === 'completed' || module.status === 'manual').length;
  const running = modules.filter((module) => module.status === 'running').length;
  const queued = modules.filter((module) => module.status === 'queued').length;
  const failed = modules.filter((module) => module.status === 'failed').length;

  if (failed > 0) return { label: `有失败 ${failed}`, color: 'red', completed, total, running, queued, failed };
  if (running > 0) return { label: `生成中 ${running}`, color: 'gold', completed, total, running, queued, failed };
  if (queued > 0) return { label: `待组批 ${queued}`, color: 'blue', completed, total, running, queued, failed };
  if (total > 0 && completed >= total) return { label: '已完成', color: 'green', completed, total, running, queued, failed };
  if (completed > 0) return { label: `进行中 ${completed}/${total}`, color: 'cyan', completed, total, running, queued, failed };
  return { label: '待配置', color: 'default', completed, total, running, queued, failed };
}

function getModuleStatusFromImage(job?: LinkListCreativeJobSummary, imageUrl?: string, sourceLabel?: string) {
  if (job?.status === 'failed') return 'failed';
  if (job?.status === 'running') return 'running';
  if (job?.status === 'queued') return 'queued';
  if (imageUrl && sourceLabel === 'AI 结果') return 'completed';
  if (imageUrl && sourceLabel !== '采集图') return 'manual';
  if (imageUrl) return 'completed';
  return 'waiting';
}

function getGenerationModeLabel(moduleCount: number, includesSkuOrCombo = false) {
  if (includesSkuOrCombo) return moduleCount > 1 ? '四宫格/单张' : '单张精修';
  if (moduleCount >= 5) return '九宫格经济';
  if (moduleCount >= 2) return '四宫格质量';
  return '单张精修';
}

function getVisualPublishModeLabel(mode: VisualPublishMode) {
  if (mode === 'main_multi') return '主图多生';
  if (mode === 'sku_adapt') return 'SKU 适配';
  return '单图精修';
}

function getVisualPublishModeHint(mode: VisualPublishMode) {
  if (mode === 'main_multi') return '选择一张参考图，生成任意数量的商品主图模块，适合 1 生 5、1 生 8 或九宫格批量任务。';
  if (mode === 'sku_adapt') return '围绕销售 SKU 或组合 SKU 重新生图，组合出售时会把组件商品放进同一个模块任务。';
  return '只重做当前任务包里的单张图片，适合质量不满意、局部重画或人工精修。';
}

function getVisualStyleProfileId(record: LinkListRecord) {
  return record.styleProfile?.id || `pending-style-${record.id}`;
}

function getVisualStyleLockLabel(record: LinkListRecord) {
  return record.styleProfile ? record.styleProfile.name || '链接级统一画风' : '待生成画风锁';
}

function getQueueGenerationModeLabel(mode: VisualPublishMode, count: number) {
  if (mode === 'single_refine') return '单图精修';
  if (mode === 'sku_adapt') return count > 1 ? 'SKU 批量适配' : 'SKU 单张适配';
  if (count >= 9) return '九宫格批量';
  if (count >= 4) return '四宫格批量';
  return '主图多生';
}

function getQueueMixPolicyLabel(mode: VisualPublishMode, count: number) {
  if (mode === 'single_refine') return '单张独立生成，可进入候选队列凑批';
  if (mode === 'sku_adapt') return '同链接画风锁 + SKU 规格信息';
  if (count >= 9) return '同链接九宫格优先，按模块边界切图';
  if (count >= 4) return '同链接四宫格优先，数量不足可凑批';
  return '同链接主图批量生成';
}

function getRecordStyleLockView(record: LinkListRecord) {
  const referenceImageUrl = getRecordMainImageUrl(record);
  if (record.styleProfile) {
    return {
      status: 'locked',
      label: '已锁定',
      color: 'green',
      title: record.styleProfile.name || '链接级统一画风',
      description: '后续商品图、SKU 图和单张重生都会优先沿用这套画风要求。',
      providerLabel: record.styleProfile.provider === 'comfyui' ? 'ComfyUI' : record.styleProfile.provider === 'chatgpt' ? 'ChatGPT API' : 'GPT 插件',
      referenceLabel: record.styleProfile.referenceImageAssetId ? '指定参考图' : referenceImageUrl ? '当前主图' : '待补参考图',
      prompt: record.styleProfile.prompt,
    };
  }

  const hasCreativeJobs = (record.creativeJobs || []).length > 0;
  return {
    status: hasCreativeJobs ? 'draft' : 'missing',
    label: hasCreativeJobs ? '待补风格锁' : '未生成',
    color: hasCreativeJobs ? 'gold' : 'default',
    title: hasCreativeJobs ? '已有生图记录，建议补充风格锁' : '尚未建立链接级画风',
    description: '当前仅根据商品图槽位和生成记录推导展示。后端接入后会先分析参考图，再写入 StyleProfile。',
    providerLabel: '待配置',
    referenceLabel: referenceImageUrl ? '当前主图可作为参考' : '缺少参考图',
    prompt: '',
  };
}

function getRecordVisualTaskPackages(record: LinkListRecord) {
  const productModules = getRecordProductImageSlotItems(record).map((item) => {
    const sourceMeta = getImageAssetSourceMeta(item.asset, item.job);
    const status = getModuleStatusFromImage(item.job, item.imageUrl, sourceMeta.label);
    const statusMeta = getVisualModuleStatusMeta(status);
    return {
      id: `${record.id}-module-product-${item.order}`,
      order: item.order,
      title: item.imageLabel,
      targetLabel: `商品图槽位 ${item.order}`,
      imageKind: item.imageKind,
      imageUrl: item.imageUrl,
      sourceLabel: sourceMeta.label,
      sourceColor: sourceMeta.color,
      status,
      statusMeta,
      slotId: item.slot.id,
      skuEntryId: undefined,
      job: item.job,
      promptSummary: item.job?.analysisText || '后端接入后展示该模块的独立生图提示词。',
    };
  });

  const skuModules = record.skuEntries.map((entry) => {
    const imageUrl = getSkuDisplayImageUrl(entry);
    const status = imageUrl ? 'completed' : 'waiting';
    const statusMeta = getVisualModuleStatusMeta(status);
    return {
      id: `${record.id}-module-sku-${entry.id}`,
      order: entry.order,
      title: entry.name,
      targetLabel: `SKU 图 ${entry.order}`,
      imageKind: entry.kind === 'combo' ? 'sku-combo-image' : 'sku-single-image',
      imageUrl,
      sourceLabel: imageUrl ? 'SKU 预览图' : '待图片',
      sourceColor: imageUrl ? 'blue' : 'default',
      status,
      statusMeta,
      slotId: undefined,
      skuEntryId: entry.id,
      job: undefined,
      promptSummary: entry.kind === 'combo' ? '组合 SKU 后续会把所有组件输入同一个模块任务。' : '单 SKU 后续会绑定该 SKU 的规格信息生成。',
    };
  });

  const productStatus = getVisualPackageStatusMeta(productModules);
  const skuStatus = getVisualPackageStatusMeta(skuModules);

  return [
    {
      id: `${record.id}-visual-task-product-gallery`,
      name: '商品主图任务包',
      typeLabel: 'VisualTask · product_gallery',
      description: '管理轮播图、效果图、场景图、细节图等商品主图模块。',
      generationMode: getGenerationModeLabel(productModules.length),
      mixPolicy: productModules.length >= 5 ? '同链接九宫格优先' : '四宫格或单张',
      modules: productModules,
      statusMeta: productStatus,
    },
    {
      id: `${record.id}-visual-task-sku-gallery`,
      name: 'SKU 图片任务包',
      typeLabel: 'VisualTask · sku_gallery',
      description: '管理销售 SKU 的预览图。组合 SKU 后续会作为独立模块处理。',
      generationMode: getGenerationModeLabel(skuModules.length, true),
      mixPolicy: 'SKU/组合图默认不进入跨链接九宫格',
      modules: skuModules,
      statusMeta: skuStatus,
    },
  ].filter((task) => task.modules.length > 0);
}

function createVisualQueueItem(
  record: LinkListRecord,
  task: ReturnType<typeof getRecordVisualTaskPackages>[number],
  options: {
    mode: VisualPublishMode;
    count: number;
    referenceImageUrl?: string;
    selectedSkuIds?: string[];
    selectedSlotIds?: string[];
  },
): VisualQueueItem {
  const safeCount = Math.max(1, Math.min(30, Math.floor(options.count || 1)));
  const visualTasks = getRecordVisualTaskPackages(record);
  const productTask = visualTasks.find((item) => item.id.includes('product-gallery'));
  const skuTask = visualTasks.find((item) => item.id.includes('sku-gallery'));
  const sourceTask =
    options.mode === 'sku_adapt' ? skuTask || task : options.mode === 'main_multi' ? productTask || task : task;
  const selectedSkuSet = new Set(options.selectedSkuIds || []);
  const selectedSlotSet = new Set(options.selectedSlotIds || []);
  const sourceModules =
    options.mode === 'sku_adapt' && selectedSkuSet.size > 0
      ? sourceTask.modules.filter((module) => module.skuEntryId && selectedSkuSet.has(module.skuEntryId))
      : options.mode === 'single_refine' && selectedSlotSet.size > 0
        ? sourceTask.modules.filter((module) => module.slotId && selectedSlotSet.has(module.slotId))
      : sourceTask.modules;
  const fallbackSkuEntries =
    options.mode === 'sku_adapt' && selectedSkuSet.size > 0
      ? record.skuEntries.filter((entry) => selectedSkuSet.has(entry.id))
      : record.skuEntries;
  const selectedModules =
    options.mode === 'single_refine'
      ? sourceModules.slice(0, safeCount)
      : Array.from({ length: safeCount }, (_, index) => {
          const order = index + 1;
          const existing = sourceModules[index];
          if (existing) return existing;
          const skuEntry = fallbackSkuEntries[index];
          const isSkuMode = options.mode === 'sku_adapt';
          return {
            id: `${sourceTask.id}-module-${options.mode}-${order}`,
            order,
            skuEntryId: skuEntry?.id,
            title: isSkuMode ? skuEntry?.name || `SKU 适配 ${order}` : getProductImageSlotLabel(order),
            targetLabel: isSkuMode ? `SKU 适配槽位 ${order}` : `商品图生成槽位 ${order}`,
            imageKind: isSkuMode ? 'sku-adapt-image' : getProductImageKindByOrder(order),
            imageUrl: options.referenceImageUrl,
            sourceLabel: options.referenceImageUrl ? '参考图' : '待选图',
            sourceColor: options.referenceImageUrl ? 'blue' : 'default',
            status: 'waiting',
            statusMeta: getVisualModuleStatusMeta('waiting'),
            slotId: undefined,
            job: undefined,
            promptSummary: '发布任务时按当前模式临时生成的模块占位。',
          };
        });
  const modeLabel = getVisualPublishModeLabel(options.mode);
  return {
    id: `${task.id}-${Date.now()}`,
    recordId: record.id,
    productTitle: record.productTitle,
    taskId: task.id,
    taskName: `${task.name} · ${modeLabel}`,
    typeLabel: task.typeLabel,
    mode: options.mode,
    modeLabel,
    generationMode: getQueueGenerationModeLabel(options.mode, selectedModules.length),
    mixPolicy: getQueueMixPolicyLabel(options.mode, selectedModules.length),
    requestedCount: selectedModules.length,
    moduleCount: selectedModules.length,
    completedCount: 0,
    statusLabel: '待执行',
    statusColor: 'blue',
    styleProfileId: getVisualStyleProfileId(record),
    styleLockLabel: getVisualStyleLockLabel(record),
    styleLockStatus: record.styleProfile ? 'ready' : 'pending',
    referenceImageUrl: options.referenceImageUrl,
    selectedSkuIds: options.selectedSkuIds,
    selectedSlotIds: options.selectedSlotIds,
    createdAt: new Date().toISOString(),
    modules: selectedModules.map((module) => ({
      id: module.id,
      order: module.order,
      skuEntryId: module.skuEntryId,
      title: module.title,
      targetLabel: module.targetLabel,
      imageKind: module.imageKind,
      imageUrl: module.imageUrl || options.referenceImageUrl,
      sourceLabel: module.sourceLabel,
      statusLabel: '待执行',
      statusColor: 'blue',
    })),
  };
}

function getDefaultVisualPublishCount(
  mode: VisualPublishMode,
  record: LinkListRecord,
  task: ReturnType<typeof getRecordVisualTaskPackages>[number],
) {
  if (mode === 'single_refine') return 1;
  if (mode === 'sku_adapt') return Math.max(1, Math.min(8, record.skuEntries.length || task.modules.length || 1));
  return Math.max(1, Math.min(8, record.productImageGenerationCount || task.modules.length || 8));
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function LinkListPanel({
  records,
  onDelete,
  onUpdate,
}: {
  records: LinkListRecord[];
  onDelete: (recordId: string) => void;
  onUpdate: (record: LinkListRecord) => void;
}) {
  const [previewRecord, setPreviewRecord] = useState<LinkListRecord>();
  const [previewActiveImageSlotId, setPreviewActiveImageSlotId] = useState<string>();
  const [previewActiveSkuEntryId, setPreviewActiveSkuEntryId] = useState<string>();
  const [imageManagerRecord, setImageManagerRecord] = useState<LinkListRecord>();
  const [managerActiveSlotId, setManagerActiveSlotId] = useState<string>();
  const [imageManagerActiveSkuEntryId, setImageManagerActiveSkuEntryId] = useState<string>();
  const [imageManagerActiveTab, setImageManagerActiveTab] = useState('product');
  const [imageManagerSelectedSlotIds, setImageManagerSelectedSlotIds] = useState<string[]>([]);
  const [imageManagerSelectedSkuIds, setImageManagerSelectedSkuIds] = useState<string[]>([]);
  const [imageSlotPickerOpen, setImageSlotPickerOpen] = useState(false);
  const [imageSlotPickerContext, setImageSlotPickerContext] = useState<'preview' | 'manager'>('preview');
  const [syncingRecordId, setSyncingRecordId] = useState<string>();
  const [syncingAll, setSyncingAll] = useState(false);
  const [regeneratingSlotKey, setRegeneratingSlotKey] = useState<string>();
  const [visualQueueOpen, setVisualQueueOpen] = useState(false);
  const [visualQueueItems, setVisualQueueItems] = useState<VisualQueueItem[]>([]);
  const [visualPublishModalOpen, setVisualPublishModalOpen] = useState(false);
  const [visualPublishRecord, setVisualPublishRecord] = useState<LinkListRecord>();
  const [visualPublishTask, setVisualPublishTask] = useState<ReturnType<typeof getRecordVisualTaskPackages>[number]>();
  const [visualPublishMode, setVisualPublishMode] = useState<VisualPublishMode>('main_multi');
  const [visualPublishCount, setVisualPublishCount] = useState(8);
  const [visualPublishReferenceUrl, setVisualPublishReferenceUrl] = useState<string>();
  const [visualPublishSelectedSkuIds, setVisualPublishSelectedSkuIds] = useState<string[]>([]);
  const previewGalleryItems = useMemo(() => getRecordPreviewGalleryItems(previewRecord), [previewRecord]);
  const previewImageAssetOptions = useMemo(() => getImageAssetOptions(previewRecord), [previewRecord]);
  const imageManagerSlotItems = useMemo(
    () => (imageManagerRecord ? getRecordProductImageSlotItems(imageManagerRecord) : []),
    [imageManagerRecord],
  );
  const imageManagerAssetOptions = useMemo(() => getImageAssetOptions(imageManagerRecord), [imageManagerRecord]);
  const imageManagerStyleLock = useMemo(
    () => (imageManagerRecord ? getRecordStyleLockView(imageManagerRecord) : undefined),
    [imageManagerRecord],
  );
  const imageManagerVisualTasks = useMemo(
    () => (imageManagerRecord ? getRecordVisualTaskPackages(imageManagerRecord) : []),
    [imageManagerRecord],
  );
  const imageManagerProductTask = useMemo(
    () => imageManagerVisualTasks.find((task) => task.id.includes('product-gallery')),
    [imageManagerVisualTasks],
  );
  const imageManagerSkuTask = useMemo(
    () => imageManagerVisualTasks.find((task) => task.id.includes('sku-gallery')),
    [imageManagerVisualTasks],
  );
  const imageManagerGalleryOptions = useMemo(() => getVisualReferenceImageOptions(imageManagerRecord), [imageManagerRecord]);
  const visualPublishAssetOptions = useMemo(() => getVisualReferenceImageOptions(visualPublishRecord), [visualPublishRecord]);
  const imageManagerPreviewGalleryItems = useMemo(
    () => getRecordPreviewGalleryItems(imageManagerRecord),
    [imageManagerRecord],
  );
  const previewActiveGalleryItem =
    previewGalleryItems.find((item) => item.slot.id === previewActiveImageSlotId) || previewGalleryItems[0];
  const previewDisplayedImageUrl = previewActiveGalleryItem?.imageUrl || getRecordMainImageUrl(previewRecord);
  const previewActiveSlot = previewActiveGalleryItem?.slot;
  const previewActiveImageKind = getProductImageKindForSlot(previewActiveSlot);
  const imageManagerActiveGalleryItem =
    imageManagerPreviewGalleryItems.find((item) => item.slot.id === managerActiveSlotId) || imageManagerPreviewGalleryItems[0];
  const imageManagerDisplayedImageUrl = imageManagerActiveGalleryItem?.imageUrl || getRecordMainImageUrl(imageManagerRecord);
  const imageManagerPreviewActiveSlot = imageManagerActiveGalleryItem?.slot;
  const managerActiveSlotItem =
    imageManagerSlotItems.find((item) => item.slot.id === managerActiveSlotId) || imageManagerSlotItems[0];
  const managerActiveSlot = managerActiveSlotItem?.slot;
  const imageManagerSelectedSlotItems = imageManagerSlotItems.filter((item) =>
    imageManagerSelectedSlotIds.includes(item.slot.id),
  );
  const activeSlotPickerRecord = imageSlotPickerContext === 'manager' ? imageManagerRecord : previewRecord;
  const activeSlotPickerSlot = imageSlotPickerContext === 'manager' ? managerActiveSlot : previewActiveSlot;
  const activeSlotPickerOptions = imageSlotPickerContext === 'manager' ? imageManagerAssetOptions : previewImageAssetOptions;
  const activePreviewSkuEntry =
    previewRecord?.skuEntries.find((entry) => entry.id === previewActiveSkuEntryId) || previewRecord?.skuEntries[0];
  const previewPriceText = formatPreviewPrice(previewRecord);
  const imageManagerActiveSkuEntry =
    imageManagerRecord?.skuEntries.find((entry) => entry.id === imageManagerActiveSkuEntryId) ||
    imageManagerRecord?.skuEntries[0];
  const imageManagerPriceText = formatPreviewPrice(imageManagerRecord);
  const imageManagerProgress = imageManagerRecord ? getRecordProductImageProgress(imageManagerRecord) : undefined;
  const hasPendingCreativeJobs = records.some((record) =>
    (record.creativeJobs || []).some((job) => job.status === 'queued' || job.status === 'running'),
  );

  const applySyncedRecords = useCallback(
    (nextRecords: LinkListRecord[]) => {
      nextRecords.forEach(onUpdate);
      setPreviewRecord((current) => {
        if (!current) return current;
        return nextRecords.find((record) => record.id === current.id) || current;
      });
      setImageManagerRecord((current) => {
        if (!current) return current;
        return nextRecords.find((record) => record.id === current.id) || current;
      });
    },
    [onUpdate],
  );

  const syncRecordCreative = async (record: LinkListRecord, silent = false) => {
    setSyncingRecordId(record.id);
    try {
      const synced = await syncPluginCreativeJobs([record]);
      const nextRecord = synced.records[0] || record;
      applySyncedRecords([nextRecord]);
      if (!silent) {
        const summary = getCreativeJobSummary(nextRecord);
        message.success(`已同步：完成 ${summary.completed}/${summary.total || 0} 张`);
      }
    } catch (error) {
      if (!silent) message.error(error instanceof Error ? error.message : '同步生成结果失败');
    } finally {
      setSyncingRecordId(undefined);
    }
  };

  const syncAllCreative = useCallback(
    async (silent = false) => {
      if (records.length === 0) return;
      if (!silent) setSyncingAll(true);
      try {
        const synced = await syncPluginCreativeJobs(records);
        applySyncedRecords(synced.records);
        if (!silent) {
          const completed = synced.jobs.filter((job) => job.status === 'completed' && job.resultImageUrl).length;
          message.success(`已同步生成结果：完成 ${completed}/${synced.jobs.length} 张`);
        }
      } catch (error) {
        if (!silent) message.error(error instanceof Error ? error.message : '同步生成结果失败');
      } finally {
        if (!silent) setSyncingAll(false);
      }
    },
    [applySyncedRecords, records],
  );

  useEffect(() => {
    if (!hasPendingCreativeJobs || records.length === 0) return undefined;
    const timer = window.setInterval(() => {
      void syncAllCreative(true);
    }, 8000);
    return () => window.clearInterval(timer);
  }, [hasPendingCreativeJobs, records.length, syncAllCreative]);

  useEffect(() => {
    if (!previewRecord) {
      setPreviewActiveImageSlotId(undefined);
      setPreviewActiveSkuEntryId(undefined);
      setImageSlotPickerOpen(false);
      return;
    }

    const galleryItems = getRecordPreviewGalleryItems(previewRecord);
    setPreviewActiveImageSlotId(galleryItems[0]?.slot.id);
    setPreviewActiveSkuEntryId(previewRecord.skuEntries[0]?.id);
  }, [previewRecord]);

  useEffect(() => {
    if (!imageManagerRecord) {
      setManagerActiveSlotId(undefined);
      setImageManagerActiveSkuEntryId(undefined);
      setImageManagerSelectedSlotIds([]);
      setImageManagerSelectedSkuIds([]);
      return;
    }

    const slots = getRecordProductImageSlotItems(imageManagerRecord);
    if (!slots.some((item) => item.slot.id === managerActiveSlotId)) {
      setManagerActiveSlotId(slots[0]?.slot.id);
    }
    if (!imageManagerRecord.skuEntries.some((entry) => entry.id === imageManagerActiveSkuEntryId)) {
      setImageManagerActiveSkuEntryId(imageManagerRecord.skuEntries[0]?.id);
    }
  }, [imageManagerRecord, managerActiveSlotId, imageManagerActiveSkuEntryId]);

  useEffect(() => {
    setImageManagerSelectedSlotIds([]);
    setImageManagerSelectedSkuIds([]);
  }, [imageManagerRecord?.id]);

  const openImageManager = (record: LinkListRecord, slotId?: string) => {
    const firstSlotId = getRecordProductImageSlotItems(record)[0]?.slot.id;
    setImageManagerRecord(record);
    setManagerActiveSlotId(slotId || firstSlotId);
    setImageManagerActiveSkuEntryId(record.skuEntries[0]?.id);
    setImageManagerActiveTab('product');
  };

  const replaceImageSlot = (record: LinkListRecord, slot: LinkListImageSlot, assetId: string) => {
    const nextRecord = updateRecordImageSlot(record, slot.id, assetId);
    onUpdate(nextRecord);
    setPreviewRecord((current) => (current?.id === nextRecord.id ? nextRecord : current));
    setImageManagerRecord((current) => (current?.id === nextRecord.id ? nextRecord : current));
    if (previewRecord?.id === nextRecord.id && previewActiveSlot?.id === slot.id) {
      setPreviewActiveImageSlotId(slot.id);
    }
    if (imageManagerRecord?.id === nextRecord.id && managerActiveSlot?.id === slot.id) {
      setManagerActiveSlotId(slot.id);
    }
    setImageSlotPickerOpen(false);
    message.success('已替换当前图片');
  };

  const replaceActiveImageSlot = (assetId: string) => {
    if (!activeSlotPickerRecord || !activeSlotPickerSlot) return;
    replaceImageSlot(activeSlotPickerRecord, activeSlotPickerSlot, assetId);
  };

  const replacePreviewImageSlot = (assetId: string) => {
    if (!previewRecord || !previewActiveSlot) return;
    const nextRecord = updateRecordImageSlot(previewRecord, previewActiveSlot.id, assetId);
    onUpdate(nextRecord);
    setPreviewRecord(nextRecord);
    setPreviewActiveImageSlotId(previewActiveSlot.id);
    setImageSlotPickerOpen(false);
    message.success('已替换当前图片');
  };

  const regenerateRecordImageSlot = async (record: LinkListRecord, imageKind?: string) => {
    if (!imageKind) {
      message.warning('当前槽位没有对应的生图任务');
      return;
    }
    const slotKey = `${record.id}:${imageKind}`;
    setRegeneratingSlotKey(slotKey);
    try {
      await regeneratePluginCreativeJob(record, imageKind);
      const synced = await syncPluginCreativeJobs([record]);
      const nextRecord = synced.records[0] || record;
      applySyncedRecords([nextRecord]);
      setPreviewRecord((current) => (current?.id === record.id ? nextRecord : current));
      setImageManagerRecord((current) => (current?.id === record.id ? nextRecord : current));
      message.success('已重新创建该槽位生图任务');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '重新生成任务创建失败');
    } finally {
      setRegeneratingSlotKey(undefined);
    }
  };

  const openVisualPublishModal = (
    record: LinkListRecord,
    task: ReturnType<typeof getRecordVisualTaskPackages>[number],
    modeOverride?: VisualPublishMode,
    referenceUrlOverride?: string,
    selectedSkuIds: string[] = [],
  ) => {
    const defaultMode: VisualPublishMode = modeOverride || (task.id.includes('sku-gallery') ? 'sku_adapt' : 'main_multi');
    const defaultReferenceUrl = referenceUrlOverride || getRecordMainImageUrl(record) || getVisualReferenceImageOptions(record)[0]?.imageUrl;
    setVisualPublishRecord(record);
    setVisualPublishTask(task);
    setVisualPublishMode(defaultMode);
    setVisualPublishCount(
      defaultMode === 'sku_adapt' && selectedSkuIds.length > 0
        ? selectedSkuIds.length
        : getDefaultVisualPublishCount(defaultMode, record, task),
    );
    setVisualPublishReferenceUrl(defaultReferenceUrl);
    setVisualPublishSelectedSkuIds(selectedSkuIds);
    setVisualPublishModalOpen(true);
  };

  const changeVisualPublishMode = (mode: VisualPublishMode) => {
    setVisualPublishMode(mode);
    if (visualPublishRecord && visualPublishTask) {
      setVisualPublishCount(getDefaultVisualPublishCount(mode, visualPublishRecord, visualPublishTask));
    } else if (mode === 'single_refine') {
      setVisualPublishCount(1);
    }
  };

  const publishVisualTaskToQueue = () => {
    if (!visualPublishRecord || !visualPublishTask) return;
    if (!visualPublishReferenceUrl) {
      message.warning('请先选择一张参考图');
      return;
    }
    const item = createVisualQueueItem(visualPublishRecord, visualPublishTask, {
      mode: visualPublishMode,
      count: visualPublishMode === 'single_refine' ? 1 : visualPublishCount,
      referenceImageUrl: visualPublishReferenceUrl,
      selectedSkuIds: visualPublishSelectedSkuIds,
    });
    setVisualQueueItems((current) => [item, ...current]);
    setVisualPublishModalOpen(false);
    setVisualQueueOpen(true);
    message.success('已发布到统一任务队列');
  };

  const enqueueVisualTask = (
    record: LinkListRecord,
    task: ReturnType<typeof getRecordVisualTaskPackages>[number],
    options: {
      mode: VisualPublishMode;
      count: number;
      referenceImageUrl?: string;
      selectedSkuIds?: string[];
      selectedSlotIds?: string[];
    },
  ) => {
    const referenceImageUrl = options.referenceImageUrl || getRecordMainImageUrl(record);
    if (!referenceImageUrl) {
      message.warning('请先选择一张参考图');
      return;
    }
    const item = createVisualQueueItem(record, task, {
      ...options,
      referenceImageUrl,
    });
    setVisualQueueItems((current) => [item, ...current]);
    setVisualQueueOpen(true);
    message.success('已加入统一任务队列');
  };

  const removeVisualQueueItem = (queueItemId: string) => {
    setVisualQueueItems((current) => current.filter((item) => item.id !== queueItemId));
  };

  return (
    <>
      {records.length === 0 ? (
        <Card className="link-list-empty-card">
          <Empty description="还没有录入链接。请在商品池中选择 SKU 后点击“录入链接列表”。" />
        </Card>
      ) : (
        <div className="link-list-wrap">
          <div className="link-list-toolbar">
            <div>
              <Text strong>链接列表</Text>
              <Text className="link-list-toolbar-sub" type="secondary">
                生成结果同步后会回显到这里
              </Text>
            </div>
            <Space>
              <Button icon={<ClockCircleOutlined />} onClick={() => setVisualQueueOpen(true)}>
                任务队列
                {visualQueueItems.length > 0 ? ` ${visualQueueItems.length}` : ''}
              </Button>
              <Button loading={syncingAll} onClick={() => void syncAllCreative(false)}>
                同步生成结果
              </Button>
            </Space>
          </div>
          <div className="link-list">
            {records.map((record) => {
              const jobSummary = getCreativeJobSummary(record);
              const productImageCount = getRecordProductImageGenerationCount(record);
              const productImageProgress = getRecordProductImageProgress(record);
              return (
            <Card
              className="link-record-card"
              hoverable
              key={record.id}
              tabIndex={0}
              onClick={() => openImageManager(record)}
              onKeyDown={(event) => {
                if (event.key !== 'Enter' && event.key !== ' ') return;
                event.preventDefault();
                openImageManager(record);
              }}
            >
              <div className="link-record-row">
                <div className="link-record-image">
                  {getRecordMainImageUrl(record) ? (
                    <Image
                      alt={record.productTitle}
                      height={56}
                      preview={false}
                      referrerPolicy="no-referrer"
                      src={getRecordMainImageUrl(record)}
                      width={56}
                    />
                  ) : (
                    <span>商品</span>
                  )}
                </div>

                <div className="link-record-summary">
                  <div className="link-record-title-line">
                    <Text className="link-record-title" strong>
                      {record.productTitle}
                    </Text>
                    <div className="link-record-tags">
                      <Tag color="blue">{record.skuEntries.length} 销售 SKU</Tag>
                      <Tag>{record.sourceLinks.length} 货源</Tag>
                      <Tag>{productImageCount} 商品图</Tag>
                      <Tag color={productImageProgress.ready >= productImageProgress.total ? 'green' : 'blue'}>
                        就绪 {productImageProgress.ready}/{productImageProgress.total}
                      </Tag>
                      {record.styleProfile ? <Tag color="purple">{record.styleProfile.provider === 'comfyui' ? 'ComfyUI' : 'ChatGPT'}</Tag> : null}
                      {jobSummary.total > 0 ? (
                        <Tag color={jobSummary.completed >= productImageCount ? 'green' : 'gold'}>
                          生图 {jobSummary.completed}/{jobSummary.total}
                        </Tag>
                      ) : null}
                      {jobSummary.failed > 0 ? <Tag color="red">失败 {jobSummary.failed}</Tag> : null}
                    </div>
                  </div>
                  <Text className="link-record-subline" type="secondary">
                    录入：{formatRecordTime(record.createdAt)} · 组件 SKU：{record.componentSkuCount}
                  </Text>
                  <div className="link-source-strip">
                    {record.sourceLinks.slice(0, 3).map((source) => (
                      <a
                        className="link-source-pill"
                        href={source.productUrl}
                        key={source.id}
                        rel="noreferrer"
                        target="_blank"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {source.shopName || source.title || '1688 货源'}
                      </a>
                    ))}
                  </div>
                </div>

                <div className="link-record-sku-preview" aria-label="SKU 顺序预览">
                  {record.skuEntries.slice(0, 4).map((entry) => (
                    <span className="link-sku-mini" key={entry.id} title={entry.name}>
                      <span className="link-sku-mini-order">{entry.order}</span>
                      {getSkuDisplayImageUrl(entry) ? (
                        <Image
                          alt={entry.name}
                          height={30}
                          preview={false}
                          referrerPolicy="no-referrer"
                          src={getSkuDisplayImageUrl(entry)}
                          width={30}
                        />
                      ) : (
                        <span>SKU</span>
                      )}
                    </span>
                  ))}
                </div>

                <div className="link-record-actions">
                  <Button
                    icon={<PictureOutlined />}
                    size="small"
                    onClick={(event) => {
                      event.stopPropagation();
                      openImageManager(record);
                    }}
                  >
                    图片管理
                  </Button>

                  <Button
                    icon={<SyncOutlined />}
                    loading={syncingRecordId === record.id}
                    size="small"
                    onClick={(event) => {
                      event.stopPropagation();
                      void syncRecordCreative(record);
                    }}
                  >
                    同步
                  </Button>

                  <Button
                    className="link-record-delete"
                    danger
                    size="small"
                    type="text"
                    onClick={(event) => {
                      event.stopPropagation();
                      onDelete(record.id);
                    }}
                  >
                    删除
                  </Button>
                </div>
              </div>
            </Card>
              );
            })}
          </div>
        </div>
      )}

      <Modal
        className="link-preview-modal link-temu-preview-modal"
        footer={null}
        open={Boolean(previewRecord)}
        title="Temu 商品详情预览"
        width={1240}
        onCancel={() => setPreviewRecord(undefined)}
      >
        {previewRecord ? (
          <div className="temu-preview-page">
            <div className="temu-preview-shell link-temu-preview-shell">
              <div className="temu-preview-gallery">
                <div className="temu-preview-thumbs">
                  {previewGalleryItems.map((item, index) => (
                    <button
                      aria-label={`商品图 ${index + 1}`}
                      className={`temu-preview-thumb ${
                        item.slot.id === previewActiveGalleryItem?.slot.id ? 'temu-preview-thumb-active' : ''
                      }`}
                      key={item.slot.id}
                      type="button"
                      onClick={() => setPreviewActiveImageSlotId(item.slot.id)}
                    >
                      <Image
                        alt={`${previewRecord.productTitle} 商品图 ${index + 1}`}
                        height={62}
                        preview={false}
                        referrerPolicy="no-referrer"
                        src={item.imageUrl}
                        width={62}
                      />
                    </button>
                  ))}
                </div>
                <div className="temu-preview-main-wrap">
                  <div className="temu-preview-main-image">
                  {previewDisplayedImageUrl ? (
                    <Image
                      alt={previewRecord.productTitle}
                      height="100%"
                      preview={false}
                      referrerPolicy="no-referrer"
                      src={previewDisplayedImageUrl}
                      width="100%"
                    />
                  ) : (
                    <span>商品主图</span>
                  )}
                  </div>
                  <div className="link-image-slot-actions">
                    <Text type="secondary">{getImageSlotLabel(previewActiveSlot)}</Text>
                    <Space size={8}>
                      <Button
                        disabled={!previewRecord || !previewActiveImageKind}
                        icon={<ReloadOutlined />}
                        loading={
                          Boolean(previewRecord && previewActiveImageKind) &&
                          regeneratingSlotKey === `${previewRecord?.id}:${previewActiveImageKind}`
                        }
                        size="small"
                        onClick={() => {
                          if (previewRecord) void regenerateRecordImageSlot(previewRecord, previewActiveImageKind);
                        }}
                      >
                        重新生成这张
                      </Button>
                      <Button
                        disabled={!previewActiveSlot || previewImageAssetOptions.length === 0}
                        icon={<SwapOutlined />}
                        size="small"
                        onClick={() => {
                          setImageSlotPickerContext('preview');
                          setImageSlotPickerOpen(true);
                        }}
                      >
                        替换当前图
                      </Button>
                      <Button
                        icon={<PictureOutlined />}
                        size="small"
                        onClick={() => {
                          if (!previewRecord) return;
                          const record = previewRecord;
                          const slotId = previewActiveSlot?.id;
                          setPreviewRecord(undefined);
                          openImageManager(record, slotId);
                        }}
                      >
                        图片管理
                      </Button>
                    </Space>
                  </div>
                </div>
              </div>

              <div className="temu-preview-info">
                <Space className="link-temu-preview-breadcrumb" size={6} wrap>
                  <Text type="secondary">Home</Text>
                  <Text type="secondary">›</Text>
                  <Text type="secondary">Accessories</Text>
                  <Text type="secondary">›</Text>
                  <Text>{previewRecord.productTitle.slice(0, 34)}...</Text>
                </Space>

                <Typography.Title className="temu-preview-title" level={3}>
                  {previewRecord.productTitle}
                </Typography.Title>

                <div className="temu-preview-rating">
                  <span>4.7 ★★★★★</span>
                  <Text type="secondary">{previewRecord.skuEntries.length} SKU · {previewRecord.sourceLinks.length} sources</Text>
                </div>

                <div className="temu-preview-price-band">
                  <strong>{previewPriceText}</strong>
                  <Text type="secondary">Estimated price preview after SKU selection</Text>
                </div>

                <div className="link-temu-preview-promo">
                  <span>✓ Free shipping</span>
                  <span>✓ $5.00 Credit for delay</span>
                </div>

                <div className="temu-preview-section">
                  <div className="temu-preview-section-head">
                    <Text strong className="temu-preview-section-title">
                      SKU
                    </Text>
                    {activePreviewSkuEntry ? <Text type="secondary">Selected: {activePreviewSkuEntry.name}</Text> : null}
                  </div>
                  <div className="temu-preview-sku-grid">
                    {previewRecord.skuEntries.map((entry) => {
                      const skuImageUrl = getSkuDisplayImageUrl(entry);
                      const active = activePreviewSkuEntry?.id === entry.id;

                      return (
                        <button
                          className={`temu-preview-sku-option ${active ? 'temu-preview-sku-option-active' : ''}`}
                          key={entry.id}
                          type="button"
                          onClick={() => setPreviewActiveSkuEntryId(entry.id)}
                        >
                          <span className="temu-preview-sku-image">
                            {skuImageUrl ? (
                              <Image
                                alt={entry.name}
                                height={44}
                                preview={false}
                                referrerPolicy="no-referrer"
                                src={skuImageUrl}
                                width={44}
                              />
                            ) : (
                              'SKU'
                            )}
                          </span>
                          <span className="temu-preview-sku-name">
                            <span>{entry.name}</span>
                            {entry.price ? <span className="temu-preview-sku-price">CN¥{entry.price}</span> : null}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="temu-preview-section">
                  <div className="temu-preview-section-head">
                    <Text strong className="temu-preview-section-title">
                      Quantity
                    </Text>
                    <Text type="secondary">1 piece · ready to export</Text>
                  </div>
                  <div className="temu-preview-actions">
                    <Button>Add to cart</Button>
                    <Button type="primary">Buy now</Button>
                  </div>
                </div>

                <div className="temu-preview-order">
                  <div className="temu-preview-order-head">
                    <Text strong>Source links</Text>
                    <Tag>{previewRecord.sourceLinks.length}</Tag>
                  </div>
                  <div className="temu-preview-order-list">
                    {previewRecord.sourceLinks.slice(0, 3).map((source, index) => (
                      <a
                        className="temu-preview-order-row link-temu-preview-source-row"
                        href={source.productUrl}
                        key={source.id}
                        rel="noreferrer"
                        target="_blank"
                      >
                        <span className="temu-preview-order-index">{index + 1}</span>
                        <div>
                          <Text strong ellipsis>
                            {source.title}
                          </Text>
                          <Text type="secondary">{source.shopName || '1688 source'}</Text>
                        </div>
                        <Text type="secondary">Open</Text>
                      </a>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </Modal>
      <Modal
        className="visual-queue-modal"
        footer={
          <Space>
            <Button disabled={visualQueueItems.length === 0} onClick={() => setVisualQueueItems([])}>
              清空队列
            </Button>
            <Button type="primary" onClick={() => setVisualQueueOpen(false)}>
              知道了
            </Button>
          </Space>
        }
        open={visualQueueOpen}
        title="统一任务队列"
        width={920}
        onCancel={() => setVisualQueueOpen(false)}
      >
        <div className="visual-queue-shell">
          <div className="visual-queue-summary">
            <div>
              <span>队列任务</span>
              <strong>{visualQueueItems.length}</strong>
            </div>
            <div>
              <span>模块总数</span>
              <strong>{visualQueueItems.reduce((sum, item) => sum + item.moduleCount, 0)}</strong>
            </div>
            <div>
              <span>执行状态</span>
              <strong>前端待接入</strong>
            </div>
          </div>
          {visualQueueItems.length > 0 ? (
            <div className="visual-queue-list">
              {visualQueueItems.map((item) => (
                <div className="visual-queue-card" key={item.id}>
                  <div className="visual-queue-card-head">
                    <div>
                      <Space size={6} wrap>
                        <Tag color={item.statusColor}>{item.statusLabel}</Tag>
                        <Tag color="purple">{item.modeLabel}</Tag>
                        <Tag>{item.typeLabel}</Tag>
                        <Tag color="blue">{item.generationMode}</Tag>
                        <Tag color={item.styleLockStatus === 'ready' ? 'green' : 'gold'}>{item.styleLockLabel}</Tag>
                      </Space>
                      <Typography.Title level={5}>{item.taskName}</Typography.Title>
                      <Text type="secondary" ellipsis>
                        {item.productTitle}
                      </Text>
                    </div>
                    <div className="visual-queue-card-side">
                      <span>{formatRecordTime(item.createdAt)}</span>
                      <Button danger size="small" type="text" onClick={() => removeVisualQueueItem(item.id)}>
                        移除
                      </Button>
                    </div>
                  </div>
                  <div className="visual-queue-meta">
                    <div>
                      <span>组批策略</span>
                      <strong>{item.mixPolicy}</strong>
                    </div>
                    <div>
                      <span>模块完成</span>
                      <strong>
                        {item.completedCount}/{item.moduleCount}
                      </strong>
                    </div>
                    <div>
                      <span>请求数量</span>
                      <strong>{item.requestedCount}</strong>
                    </div>
                    <div>
                      <span>画风 ID</span>
                      <strong>{item.styleProfileId}</strong>
                    </div>
                    <div>
                      <span>后端执行</span>
                      <strong>待实现</strong>
                    </div>
                  </div>
                  <div className="visual-queue-module-strip">
                    {item.modules.map((module) => (
                      <div className="visual-queue-module" key={module.id}>
                        <div className="visual-queue-module-thumb">
                          {module.imageUrl ? (
                            <Image
                              alt={module.title}
                              height={42}
                              preview={false}
                              referrerPolicy="no-referrer"
                              src={module.imageUrl}
                              width={42}
                            />
                          ) : (
                            <PictureOutlined />
                          )}
                        </div>
                        <div>
                          <Text strong ellipsis>
                            {module.title}
                          </Text>
                          <Text type="secondary" ellipsis>
                            {module.targetLabel}
                          </Text>
                        </div>
                        <Tag color={module.statusColor}>{module.statusLabel}</Tag>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty description="暂无任务。请在某个商品链接的图片管理中发布任务包。" />
          )}
        </div>
      </Modal>
      <Modal
        className="visual-publish-modal"
        footer={
          <Space>
            <Button onClick={() => setVisualPublishModalOpen(false)}>取消</Button>
            <Button type="primary" onClick={publishVisualTaskToQueue}>
              发布到任务队列
            </Button>
          </Space>
        }
        open={visualPublishModalOpen}
        title="发布图片任务"
        width={780}
        onCancel={() => setVisualPublishModalOpen(false)}
      >
        {visualPublishRecord && visualPublishTask ? (
          <div className="visual-publish-shell">
            <div className="visual-publish-product">
              <div className="visual-publish-thumb">
                {getRecordMainImageUrl(visualPublishRecord) ? (
                  <Image
                    alt={visualPublishRecord.productTitle}
                    height={64}
                    preview={false}
                    referrerPolicy="no-referrer"
                    src={getRecordMainImageUrl(visualPublishRecord)}
                    width={64}
                  />
                ) : (
                  <PictureOutlined />
                )}
              </div>
              <div>
                <Typography.Title level={5}>{visualPublishRecord.productTitle}</Typography.Title>
                <Space size={6} wrap>
                  <Tag>{visualPublishTask.name}</Tag>
                  <Tag color={visualPublishRecord.styleProfile ? 'green' : 'gold'}>
                    {getVisualStyleLockLabel(visualPublishRecord)}
                  </Tag>
                  <Tag>{getVisualStyleProfileId(visualPublishRecord)}</Tag>
                </Space>
              </div>
            </div>

            <div className="visual-publish-section">
              <Text strong>生成模式</Text>
              <div className="visual-publish-mode-grid">
                {(['main_multi', 'sku_adapt', 'single_refine'] as VisualPublishMode[]).map((mode) => (
                  <button
                    className={visualPublishMode === mode ? 'is-active' : ''}
                    key={mode}
                    type="button"
                    onClick={() => changeVisualPublishMode(mode)}
                  >
                    <strong>{getVisualPublishModeLabel(mode)}</strong>
                    <span>{getVisualPublishModeHint(mode)}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="visual-publish-form-grid">
              <label>
                <span>参考图</span>
                <Select
                  showSearch
                  value={visualPublishReferenceUrl}
                  optionFilterProp="label"
                  options={visualPublishAssetOptions.map((option, index) => ({
                    label: `${index + 1}. ${option.asset.alt || option.asset.role}`,
                    value: option.imageUrl,
                  }))}
                  placeholder="选择一张参考图"
                  onChange={setVisualPublishReferenceUrl}
                />
              </label>
              <label>
                <span>生成数量</span>
                <Input
                  disabled={visualPublishMode === 'single_refine'}
                  max={30}
                  min={1}
                  type="number"
                  value={visualPublishMode === 'single_refine' ? 1 : visualPublishCount}
                  onChange={(event) => {
                    const nextValue = Math.max(1, Math.min(30, Number(event.target.value) || 1));
                    setVisualPublishCount(nextValue);
                  }}
                />
              </label>
            </div>

            <div className="visual-publish-reference">
              <div className="visual-publish-reference-preview">
                {visualPublishReferenceUrl ? (
                  <Image
                    alt="参考图"
                    height={96}
                    preview
                    referrerPolicy="no-referrer"
                    src={visualPublishReferenceUrl}
                    width={96}
                  />
                ) : (
                  <PictureOutlined />
                )}
              </div>
              <div>
                <Text strong>将写入队列的任务信息</Text>
                <div className="visual-publish-facts">
                  <div>
                    <span>模式</span>
                    <strong>{getVisualPublishModeLabel(visualPublishMode)}</strong>
                  </div>
                  <div>
                    <span>预计模块</span>
                    <strong>{visualPublishMode === 'single_refine' ? 1 : visualPublishCount}</strong>
                  </div>
                  <div>
                    <span>画风锁</span>
                    <strong>{visualPublishRecord.styleProfile ? 'ready' : 'pending'}</strong>
                  </div>
                  <div>
                    <span>组批策略</span>
                    <strong>
                      {getQueueMixPolicyLabel(
                        visualPublishMode,
                        visualPublishMode === 'single_refine' ? 1 : visualPublishCount,
                      )}
                    </strong>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <Empty description="请先在图片管理中选择一个任务包。" />
        )}
      </Modal>
      <Drawer
        className="image-manager-drawer"
        destroyOnClose={false}
        open={Boolean(imageManagerRecord)}
        title="图片管理"
        width={1280}
        onClose={() => setImageManagerRecord(undefined)}
      >
        {imageManagerRecord ? (
          <div className="image-manager-shell">
            <div className="image-manager-head">
              <div className="image-manager-cover">
                {getRecordMainImageUrl(imageManagerRecord) ? (
                  <Image
                    alt={imageManagerRecord.productTitle}
                    height={72}
                    preview={false}
                    referrerPolicy="no-referrer"
                    src={getRecordMainImageUrl(imageManagerRecord)}
                    width={72}
                  />
                ) : (
                  <PictureOutlined />
                )}
              </div>
              <div className="image-manager-title">
                <Typography.Title level={4}>{imageManagerRecord.productTitle}</Typography.Title>
                <Space size={6} wrap>
                  <Tag color="blue">{imageManagerRecord.skuEntries.length} SKU</Tag>
                  <Tag>{imageManagerRecord.sourceLinks.length} 货源</Tag>
                  <Tag color={imageManagerProgress && imageManagerProgress.ready >= imageManagerProgress.total ? 'green' : 'blue'}>
                    商品图 {imageManagerProgress?.ready || 0}/{imageManagerProgress?.total || 0}
                  </Tag>
                  {imageManagerProgress?.queued ? <Tag color="blue">队列 {imageManagerProgress.queued}</Tag> : null}
                  {imageManagerProgress?.running ? <Tag color="gold">生成中 {imageManagerProgress.running}</Tag> : null}
                  {imageManagerProgress?.failed ? <Tag color="red">失败 {imageManagerProgress.failed}</Tag> : null}
                </Space>
              </div>
              <Space className="image-manager-head-actions">
                <Button
                  icon={<EyeOutlined />}
                  onClick={() => {
                    setPreviewRecord(imageManagerRecord);
                    if (managerActiveSlot) setPreviewActiveImageSlotId(managerActiveSlot.id);
                  }}
                >
                  Temu 预览
                </Button>
                <Button
                  icon={<SyncOutlined />}
                  loading={syncingRecordId === imageManagerRecord.id}
                  onClick={() => void syncRecordCreative(imageManagerRecord)}
                >
                  同步结果
                </Button>
              </Space>
            </div>

            <div className="image-manager-temu-preview">
              <div className="image-manager-temu-gallery">
                <div className="temu-preview-thumbs image-manager-temu-thumbs">
                  {imageManagerPreviewGalleryItems.map((item, index) => {
                    const selected = imageManagerSelectedSlotIds.includes(item.slot.id);
                    const active = item.slot.id === imageManagerActiveGalleryItem?.slot.id;
                    return (
                      <button
                        aria-label={`商品图 ${index + 1}`}
                        className={[
                          'temu-preview-thumb',
                          active ? 'temu-preview-thumb-active' : '',
                          selected ? 'image-manager-preview-thumb-selected' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        key={item.slot.id}
                        type="button"
                        onClick={() => {
                          setManagerActiveSlotId(item.slot.id);
                          setImageManagerSelectedSlotIds((current) =>
                            current.includes(item.slot.id)
                              ? current.filter((slotId) => slotId !== item.slot.id)
                              : [...current, item.slot.id],
                          );
                        }}
                      >
                        <span className="image-manager-preview-thumb-index">{index + 1}</span>
                        {selected ? <span className="image-manager-preview-thumb-check">✓</span> : null}
                        <Image
                          alt={`${imageManagerRecord.productTitle} 商品图 ${index + 1}`}
                          height={64}
                          preview={false}
                          referrerPolicy="no-referrer"
                          src={item.imageUrl}
                          width={64}
                        />
                      </button>
                    );
                  })}
                </div>
                <div className="image-manager-temu-main">
                  <div className="temu-preview-main-image image-manager-temu-main-image">
                    {imageManagerDisplayedImageUrl ? (
                      <Image
                        alt={imageManagerRecord.productTitle}
                        height="100%"
                        preview
                        referrerPolicy="no-referrer"
                        src={imageManagerDisplayedImageUrl}
                        width="100%"
                      />
                    ) : (
                      <span>商品主图</span>
                    )}
                  </div>
                  <div className="image-manager-temu-actions">
                    <div>
                      <Text type="secondary">当前槽位</Text>
                      <Text strong>{getImageSlotLabel(imageManagerPreviewActiveSlot || managerActiveSlot)}</Text>
                      <Tag color="blue">已选 {imageManagerSelectedSlotIds.length}</Tag>
                    </div>
                    <Space size={8} wrap>
                      <Button
                        size="small"
                        onClick={() => setImageManagerSelectedSlotIds(imageManagerPreviewGalleryItems.map((item) => item.slot.id))}
                      >
                        全选图片
                      </Button>
                      <Button size="small" onClick={() => setImageManagerSelectedSlotIds([])}>
                        清空
                      </Button>
                      <Button
                        icon={<SwapOutlined />}
                        size="small"
                        disabled={!imageManagerPreviewActiveSlot && !managerActiveSlot}
                        onClick={() => {
                          setImageSlotPickerContext('manager');
                          setImageSlotPickerOpen(true);
                        }}
                      >
                        替换当前图
                      </Button>
                      <Button
                        icon={<ReloadOutlined />}
                        size="small"
                        disabled={!imageManagerProductTask || !imageManagerDisplayedImageUrl}
                        onClick={() => {
                          if (!imageManagerProductTask || !(imageManagerPreviewActiveSlot || managerActiveSlot)) return;
                          enqueueVisualTask(imageManagerRecord, imageManagerProductTask, {
                            mode: 'single_refine',
                            count: 1,
                            referenceImageUrl: imageManagerDisplayedImageUrl,
                            selectedSlotIds: [(imageManagerPreviewActiveSlot || managerActiveSlot)!.id],
                          });
                        }}
                      >
                        当前图精修
                      </Button>
                      <Button
                        type="primary"
                        disabled={!imageManagerProductTask}
                        onClick={() => {
                          if (!imageManagerProductTask) return;
                          enqueueVisualTask(imageManagerRecord, imageManagerProductTask, {
                            mode: 'main_multi',
                            count: getRecordProductImageGenerationCount(imageManagerRecord),
                            referenceImageUrl: imageManagerDisplayedImageUrl,
                          });
                        }}
                      >
                        主图全量生成
                      </Button>
                      <Button icon={<ClockCircleOutlined />} onClick={() => setVisualQueueOpen(true)}>
                        任务队列
                        {visualQueueItems.length > 0 ? ` ${visualQueueItems.length}` : ''}
                      </Button>
                    </Space>
                  </div>
                </div>
              </div>

              <div className="image-manager-temu-info">
                <Space className="link-temu-preview-breadcrumb" size={6} wrap>
                  <Text type="secondary">Home</Text>
                  <Text type="secondary">›</Text>
                  <Text type="secondary">Accessories</Text>
                  <Text type="secondary">›</Text>
                  <Text>{imageManagerRecord.productTitle.slice(0, 34)}...</Text>
                </Space>

                <Typography.Title className="temu-preview-title" level={3}>
                  {imageManagerRecord.productTitle}
                </Typography.Title>

                <div className="temu-preview-rating">
                  <span>4.7 ★★★★★</span>
                  <Text type="secondary">
                    {imageManagerRecord.skuEntries.length} SKU · {imageManagerRecord.sourceLinks.length} sources
                  </Text>
                </div>

                <div className="temu-preview-price-band">
                  <strong>{imageManagerPriceText}</strong>
                  <Text type="secondary">Estimated price preview after SKU selection</Text>
                </div>

                <div className="link-temu-preview-promo">
                  <span>✓ Free shipping</span>
                  <span>✓ $5.00 Credit for delay</span>
                </div>

                <div className="temu-preview-section">
                  <div className="temu-preview-section-head">
                    <Text strong className="temu-preview-section-title">
                      SKU
                    </Text>
                    {imageManagerActiveSkuEntry ? (
                      <Text type="secondary">Selected: {imageManagerActiveSkuEntry.name}</Text>
                    ) : null}
                  </div>
                  <div className="temu-preview-sku-grid image-manager-temu-sku-grid">
                    {imageManagerRecord.skuEntries.map((entry) => {
                      const skuImageUrl = getSkuDisplayImageUrl(entry);
                      const active = imageManagerActiveSkuEntry?.id === entry.id;
                      const selected = imageManagerSelectedSkuIds.includes(entry.id);

                      return (
                        <button
                          className={[
                            'temu-preview-sku-option',
                            active ? 'temu-preview-sku-option-active' : '',
                            selected ? 'image-manager-sku-option-selected' : '',
                          ]
                            .filter(Boolean)
                            .join(' ')}
                          key={entry.id}
                          type="button"
                          onClick={() => {
                            setImageManagerActiveSkuEntryId(entry.id);
                            setImageManagerSelectedSkuIds((current) =>
                              current.includes(entry.id)
                                ? current.filter((id) => id !== entry.id)
                                : [...current, entry.id],
                            );
                          }}
                        >
                          <span className="temu-preview-sku-image">
                            {skuImageUrl ? (
                              <Image
                                alt={entry.name}
                                height={44}
                                preview={false}
                                referrerPolicy="no-referrer"
                                src={skuImageUrl}
                                width={44}
                              />
                            ) : (
                              'SKU'
                            )}
                          </span>
                          <span className="temu-preview-sku-name">
                            <span>{entry.name}</span>
                            {entry.price ? <span className="temu-preview-sku-price">CN¥{entry.price}</span> : null}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <Space size={8} wrap>
                    <Button
                      size="small"
                      onClick={() => setImageManagerSelectedSkuIds(imageManagerRecord.skuEntries.map((entry) => entry.id))}
                    >
                      全选 SKU
                    </Button>
                    <Button size="small" onClick={() => setImageManagerSelectedSkuIds([])}>
                      清空 SKU
                    </Button>
                    <Button
                      size="small"
                      type="primary"
                      disabled={!imageManagerSkuTask || imageManagerRecord.skuEntries.length === 0}
                      onClick={() => {
                        if (!imageManagerSkuTask) return;
                        const selectedSkuIds =
                          imageManagerSelectedSkuIds.length > 0
                            ? imageManagerSelectedSkuIds
                            : imageManagerActiveSkuEntry
                              ? [imageManagerActiveSkuEntry.id]
                              : imageManagerRecord.skuEntries.map((entry) => entry.id);
                        enqueueVisualTask(imageManagerRecord, imageManagerSkuTask, {
                          mode: 'sku_adapt',
                          count: selectedSkuIds.length,
                          referenceImageUrl: imageManagerDisplayedImageUrl,
                          selectedSkuIds,
                        });
                      }}
                    >
                      SKU 精修入队
                    </Button>
                    <Button
                      size="small"
                      disabled={!imageManagerProductTask || imageManagerSelectedSlotIds.length === 0}
                      onClick={() => {
                        if (!imageManagerProductTask) return;
                        enqueueVisualTask(imageManagerRecord, imageManagerProductTask, {
                          mode: 'single_refine',
                          count: imageManagerSelectedSlotIds.length,
                          referenceImageUrl: imageManagerDisplayedImageUrl,
                          selectedSlotIds: imageManagerSelectedSlotIds,
                        });
                      }}
                    >
                      批量精修入队
                    </Button>
                  </Space>
                </div>

                <div className="temu-preview-section">
                  <div className="temu-preview-section-head">
                    <Text strong className="temu-preview-section-title">
                      Quantity
                    </Text>
                    <Text type="secondary">1 piece · ready to export</Text>
                  </div>
                  <div className="temu-preview-actions">
                    <Button>Add to cart</Button>
                    <Button type="primary">Buy now</Button>
                  </div>
                </div>

                <div className="temu-preview-order">
                  <div className="temu-preview-order-head">
                    <Text strong>Source links</Text>
                    <Tag>{imageManagerRecord.sourceLinks.length}</Tag>
                  </div>
                  <div className="temu-preview-order-list">
                    {imageManagerRecord.sourceLinks.slice(0, 3).map((source, index) => (
                      <a
                        className="temu-preview-order-row link-temu-preview-source-row"
                        href={source.productUrl}
                        key={source.id}
                        rel="noreferrer"
                        target="_blank"
                      >
                        <span className="temu-preview-order-index">{index + 1}</span>
                        <div>
                          <Text strong ellipsis>
                            {source.title}
                          </Text>
                          <Text type="secondary">{source.shopName || '1688 source'}</Text>
                        </div>
                        <Text type="secondary">Open</Text>
                      </a>
                    ))}
                  </div>
                </div>

                <section className="image-manager-temu-library">
                  <div className="image-manager-library-head">
                    <div>
                      <Text strong>统一图库</Text>
                      <Text type="secondary">点击图片可替换当前预览槽位。</Text>
                    </div>
                    <Tag>{imageManagerGalleryOptions.length} 张</Tag>
                  </div>
                  {imageManagerGalleryOptions.length > 0 ? (
                    <div className="image-manager-temu-library-grid">
                      {imageManagerGalleryOptions.map((option, index) => {
                        const canUseForProduct = option.asset.role === 'product-main' || option.asset.role === 'product-material';
                        return (
                          <button
                            className="image-manager-temu-library-card"
                            disabled={!canUseForProduct || !(imageManagerPreviewActiveSlot || managerActiveSlot)}
                            key={option.asset.id}
                            type="button"
                            onClick={() => {
                              const targetSlot = imageManagerPreviewActiveSlot || managerActiveSlot;
                              if (!targetSlot || !canUseForProduct) return;
                              replaceImageSlot(imageManagerRecord, targetSlot, option.asset.id);
                            }}
                          >
                            <Image
                              alt={option.asset.alt || `图库图片 ${index + 1}`}
                              height={54}
                              preview={false}
                              referrerPolicy="no-referrer"
                              src={option.imageUrl}
                              width={54}
                            />
                            <span>
                              <strong>{option.asset.alt || `图片 ${index + 1}`}</strong>
                              <Text type="secondary">
                                {option.asset.role === 'sales-sku' ? 'SKU 图' : getImageAssetSourceMeta(option.asset).label}
                              </Text>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <Empty description="暂无图库图片" />
                  )}
                </section>
              </div>
            </div>

            <div className="image-manager-flow">
              <section className={`image-manager-style-strip image-manager-style-${imageManagerStyleLock?.status || 'missing'}`}>
                <div>
                  <Space size={6} wrap>
                    <Tag
                      color={imageManagerStyleLock?.color || 'default'}
                      icon={imageManagerStyleLock?.status === 'locked' ? <CheckCircleOutlined /> : <ClockCircleOutlined />}
                    >
                      风格锁：{imageManagerStyleLock?.label || '待生成'}
                    </Tag>
                    <Tag>{imageManagerStyleLock?.providerLabel || '待配置'}</Tag>
                    <Tag>{imageManagerStyleLock?.referenceLabel || '当前主图'}</Tag>
                  </Space>
                  <Typography.Title level={5}>{imageManagerStyleLock?.title || '先分析商品统一风格'}</Typography.Title>
                  <Text type="secondary">
                    发布任何生图任务前，后续后端会先为当前链接建立统一画风，再按主图多生、SKU 适配或单图精修执行。
                  </Text>
                </div>
                <Button disabled>分析统一风格</Button>
              </section>

              <section className="image-manager-preview-strip" aria-label="商品详情预览图">
                {imageManagerSlotItems.map((item) => (
                  <button
                    className={[
                      managerActiveSlotItem?.slot.id === item.slot.id ? 'is-active' : '',
                      imageManagerSelectedSlotIds.includes(item.slot.id) ? 'is-selected' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    key={item.slot.id}
                    type="button"
                    onClick={() => {
                      setManagerActiveSlotId(item.slot.id);
                      setImageManagerSelectedSlotIds((current) =>
                        current.includes(item.slot.id)
                          ? current.filter((slotId) => slotId !== item.slot.id)
                          : [...current, item.slot.id],
                      );
                    }}
                  >
                    <span>{item.order}</span>
                    {imageManagerSelectedSlotIds.includes(item.slot.id) ? <i>✓</i> : null}
                    {item.imageUrl ? (
                      <Image
                        alt={item.imageLabel}
                        height={48}
                        preview={false}
                        referrerPolicy="no-referrer"
                        src={item.imageUrl}
                        width={48}
                      />
                    ) : (
                      <PictureOutlined />
                    )}
                  </button>
                ))}
              </section>

              <section className="image-manager-mode-panel">
                <div className="image-manager-mode-head">
                  <div>
                    <Text strong>生成模式</Text>
                    <Text type="secondary">
                      已选商品图 {imageManagerSelectedSlotItems.length} 张。点击上方预览图可以单选或多选。
                    </Text>
                  </div>
                  <Space size={6} wrap>
                    <Button size="small" onClick={() => setImageManagerSelectedSlotIds(imageManagerSlotItems.map((item) => item.slot.id))}>
                      全选商品图
                    </Button>
                    <Button size="small" onClick={() => setImageManagerSelectedSlotIds([])}>
                      清空
                    </Button>
                    <Tag color="blue">前端队列</Tag>
                  </Space>
                </div>
                <div className="image-manager-mode-actions">
                  <Button
                    disabled={!imageManagerProductTask}
                    type="primary"
                    onClick={() => {
                      if (!imageManagerProductTask) return;
                      enqueueVisualTask(imageManagerRecord, imageManagerProductTask, {
                        mode: 'main_multi',
                        count: getRecordProductImageGenerationCount(imageManagerRecord),
                        referenceImageUrl: managerActiveSlotItem?.imageUrl || getRecordMainImageUrl(imageManagerRecord),
                      });
                    }}
                  >
                    主图全量生成
                  </Button>
                  <Button
                    disabled={!imageManagerProductTask || !managerActiveSlotItem?.imageUrl}
                    onClick={() => {
                      if (!imageManagerProductTask || !managerActiveSlot) return;
                      enqueueVisualTask(imageManagerRecord, imageManagerProductTask, {
                        mode: 'single_refine',
                        count: 1,
                        referenceImageUrl: managerActiveSlotItem?.imageUrl || getRecordMainImageUrl(imageManagerRecord),
                        selectedSlotIds: [managerActiveSlot.id],
                      });
                    }}
                  >
                    当前图精修
                  </Button>
                  <Button
                    disabled={!imageManagerProductTask || imageManagerSelectedSlotIds.length === 0}
                    onClick={() => {
                      if (!imageManagerProductTask) return;
                      enqueueVisualTask(imageManagerRecord, imageManagerProductTask, {
                        mode: 'single_refine',
                        count: imageManagerSelectedSlotIds.length,
                        referenceImageUrl: managerActiveSlotItem?.imageUrl || getRecordMainImageUrl(imageManagerRecord),
                        selectedSlotIds: imageManagerSelectedSlotIds,
                      });
                    }}
                  >
                    批量精修入队
                  </Button>
                  <Button
                    disabled={!imageManagerSkuTask || imageManagerRecord.skuEntries.length === 0}
                    onClick={() => {
                      if (!imageManagerSkuTask) return;
                      const selectedSkuIds =
                        imageManagerSelectedSkuIds.length > 0
                          ? imageManagerSelectedSkuIds
                          : imageManagerRecord.skuEntries.map((entry) => entry.id);
                      enqueueVisualTask(imageManagerRecord, imageManagerSkuTask, {
                        mode: 'sku_adapt',
                        count: selectedSkuIds.length,
                        referenceImageUrl: managerActiveSlotItem?.imageUrl || getRecordMainImageUrl(imageManagerRecord),
                        selectedSkuIds,
                      });
                    }}
                  >
                    SKU 精修入队
                  </Button>
                </div>

                <div className="image-manager-sku-picker">
                  <div>
                    <Text strong>SKU 精修范围</Text>
                    <Text type="secondary">不选择时默认处理全部 SKU。</Text>
                  </div>
                  <div className="image-manager-sku-chip-grid">
                    {imageManagerRecord.skuEntries.map((entry) => {
                      const active = imageManagerSelectedSkuIds.includes(entry.id);
                      return (
                        <button
                          className={active ? 'is-active' : ''}
                          key={entry.id}
                          type="button"
                          onClick={() => {
                            setImageManagerSelectedSkuIds((current) =>
                              current.includes(entry.id) ? current.filter((id) => id !== entry.id) : [...current, entry.id],
                            );
                          }}
                        >
                          {getSkuDisplayImageUrl(entry) ? (
                            <Image
                              alt={entry.name}
                              height={28}
                              preview={false}
                              referrerPolicy="no-referrer"
                              src={getSkuDisplayImageUrl(entry)}
                              width={28}
                            />
                          ) : null}
                          <span>{entry.name}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </section>
            </div>

            <Tabs
              activeKey={imageManagerActiveTab}
              className="image-manager-tabs"
              onChange={setImageManagerActiveTab}
              items={[
                {
                  key: 'product',
                  label: (
                    <span>
                      <PictureOutlined /> 商品图
                    </span>
                  ),
                  children: (
                    <div className="image-manager-product-layout">
                      <div className="image-manager-slot-grid">
                        {imageManagerSlotItems.map((item) => {
                          const active = managerActiveSlotItem?.slot.id === item.slot.id;
                          const statusMeta = getImageTaskStatusMeta(item.job?.status, Boolean(item.imageUrl));
                          const sourceMeta = getImageAssetSourceMeta(item.asset, item.job);
                          return (
                            <div
                              className={`image-manager-slot-card ${active ? 'image-manager-slot-card-active' : ''}`}
                              key={item.slot.id}
                              role="button"
                              tabIndex={0}
                              onClick={() => setManagerActiveSlotId(item.slot.id)}
                              onKeyDown={(event) => {
                                if (event.key !== 'Enter' && event.key !== ' ') return;
                                event.preventDefault();
                                setManagerActiveSlotId(item.slot.id);
                              }}
                            >
                              <div className="image-manager-slot-thumb">
                                <span className="image-manager-slot-index">{item.order}</span>
                                {item.imageUrl ? (
                                  <Image
                                    alt={`${imageManagerRecord.productTitle} ${item.imageLabel}`}
                                    height={72}
                                    preview={false}
                                    referrerPolicy="no-referrer"
                                    src={item.imageUrl}
                                    width={72}
                                  />
                                ) : (
                                  <PictureOutlined />
                                )}
                              </div>
                              <div className="image-manager-slot-copy">
                                <Text strong ellipsis>
                                  {item.imageLabel}
                                </Text>
                                <Space size={4} wrap>
                                  <Tag color={statusMeta.color} icon={statusMeta.icon}>
                                    {statusMeta.label}
                                  </Tag>
                                  <Tag color={sourceMeta.color}>{sourceMeta.label}</Tag>
                                </Space>
                              </div>
                            </div>
                          );
                        })}
                      </div>

                      <div className="image-manager-detail">
                        {managerActiveSlotItem ? (
                          <>
                            <div className="image-manager-detail-preview">
                              {managerActiveSlotItem.imageUrl ? (
                                <Image
                                  alt={`${imageManagerRecord.productTitle} ${managerActiveSlotItem.imageLabel}`}
                                  preview
                                  referrerPolicy="no-referrer"
                                  src={managerActiveSlotItem.imageUrl}
                                />
                              ) : (
                                <div className="image-manager-detail-empty">
                                  <PictureOutlined />
                                  <Text type="secondary">这个槽位还没有图片</Text>
                                </div>
                              )}
                            </div>
                            <div className="image-manager-detail-body">
                              <div>
                                <Text type="secondary">当前槽位</Text>
                                <Typography.Title level={5}>{managerActiveSlotItem.order}. {managerActiveSlotItem.imageLabel}</Typography.Title>
                              </div>
                              <Space size={8} wrap>
                                <Tag color={getImageTaskStatusMeta(managerActiveSlotItem.job?.status, Boolean(managerActiveSlotItem.imageUrl)).color}>
                                  {getImageTaskStatusMeta(managerActiveSlotItem.job?.status, Boolean(managerActiveSlotItem.imageUrl)).label}
                                </Tag>
                                <Tag color={getImageAssetSourceMeta(managerActiveSlotItem.asset, managerActiveSlotItem.job).color}>
                                  {getImageAssetSourceMeta(managerActiveSlotItem.asset, managerActiveSlotItem.job).label}
                                </Tag>
                                <Tag>{managerActiveSlotItem.imageKind}</Tag>
                              </Space>
                              <div className="image-manager-facts">
                                <div>
                                  <span>导出位置</span>
                                  <strong>轮播图 / 产品描述图</strong>
                                </div>
                                <div>
                                  <span>生成任务</span>
                                  <strong>{managerActiveSlotItem.job?.id || '暂无任务'}</strong>
                                </div>
                                <div>
                                  <span>图片来源</span>
                                  <strong>{managerActiveSlotItem.asset?.id || '未绑定图片'}</strong>
                                </div>
                              </div>
                              {managerActiveSlotItem.imageUrl ? (
                                <Text className="image-manager-url" copyable={{ text: managerActiveSlotItem.imageUrl }} ellipsis>
                                  {managerActiveSlotItem.imageUrl}
                                </Text>
                              ) : null}
                              <Space className="image-manager-detail-actions" wrap>
                                <Button
                                  icon={<EyeOutlined />}
                                  onClick={() => {
                                    setPreviewRecord(imageManagerRecord);
                                    setPreviewActiveImageSlotId(managerActiveSlotItem.slot.id);
                                  }}
                                >
                                  商品预览
                                </Button>
                                <Button
                                  disabled={imageManagerAssetOptions.length === 0}
                                  icon={<SwapOutlined />}
                                  onClick={() => {
                                    setImageSlotPickerContext('manager');
                                    setImageSlotPickerOpen(true);
                                  }}
                                >
                                  替换图片
                                </Button>
                                <Button
                                  icon={<ReloadOutlined />}
                                  type="primary"
                                  onClick={() => {
                                    if (!imageManagerProductTask) return;
                                    openVisualPublishModal(
                                      imageManagerRecord,
                                      imageManagerProductTask,
                                      'single_refine',
                                      managerActiveSlotItem.imageUrl || getRecordMainImageUrl(imageManagerRecord),
                                    );
                                  }}
                                >
                                  单图精修入队
                                </Button>
                              </Space>
                            </div>
                          </>
                        ) : (
                          <Empty description="暂无商品图槽位" />
                        )}
                      </div>
                    </div>
                  ),
                },
                {
                  key: 'tasks',
                  label: (
                    <span>
                      <AppstoreOutlined /> 任务包
                    </span>
                  ),
                  children: (
                    <div className="image-manager-task-workbench">
                      {imageManagerStyleLock ? (
                        <div className={`style-lock-card style-lock-${imageManagerStyleLock.status}`}>
                          <div className="style-lock-main">
                            <Space size={6} wrap>
                              <Tag color={imageManagerStyleLock.color} icon={imageManagerStyleLock.status === 'locked' ? <CheckCircleOutlined /> : <ClockCircleOutlined />}>
                                风格锁：{imageManagerStyleLock.label}
                              </Tag>
                              <Tag>{imageManagerStyleLock.providerLabel}</Tag>
                              <Tag>{imageManagerStyleLock.referenceLabel}</Tag>
                            </Space>
                            <Typography.Title level={5}>{imageManagerStyleLock.title}</Typography.Title>
                            <Text type="secondary">{imageManagerStyleLock.description}</Text>
                          </div>
                          <div className="style-lock-side">
                            <div>
                              <span>StyleProfile</span>
                              <strong>{imageManagerStyleLock.status === 'locked' ? 'ready' : 'pending'}</strong>
                            </div>
                            <div>
                              <span>统一画风</span>
                              <strong>{imageManagerStyleLock.prompt ? '已写入' : '待生成'}</strong>
                            </div>
                            <Space wrap>
                              <Button disabled size="small">
                                分析风格
                              </Button>
                              <Button disabled size="small" type="primary">
                                确认锁定
                              </Button>
                            </Space>
                          </div>
                        </div>
                      ) : null}

                      <div className="visual-task-list">
                        {imageManagerVisualTasks.map((task) => {
                          const completion =
                            task.statusMeta.total > 0 ? Math.round((task.statusMeta.completed / task.statusMeta.total) * 100) : 0;
                          return (
                            <div className="visual-task-card" key={task.id}>
                              <div className="visual-task-head">
                                <div>
                                  <Space size={6} wrap>
                                    <Tag color={task.statusMeta.color}>{task.statusMeta.label}</Tag>
                                    <Tag>{task.typeLabel}</Tag>
                                    <Tag color="blue">{task.generationMode}</Tag>
                                  </Space>
                                  <Typography.Title level={5}>{task.name}</Typography.Title>
                                  <Text type="secondary">{task.description}</Text>
                                </div>
                                <div className="visual-task-side">
                                  <div className="visual-task-stat">
                                    <strong>
                                      {task.statusMeta.completed}/{task.statusMeta.total}
                                    </strong>
                                    <span>模块完成</span>
                                  </div>
                                  <Button
                                    block
                                    size="small"
                                    type="primary"
                                    onClick={() => openVisualPublishModal(imageManagerRecord, task)}
                                  >
                                    发布任务
                                  </Button>
                                </div>
                              </div>
                              <div className="visual-task-progress" aria-label={`${task.name} 完成度 ${completion}%`}>
                                <span style={{ width: `${completion}%` }} />
                              </div>
                              <div className="visual-task-meta">
                                <div>
                                  <span>组批策略</span>
                                  <strong>{task.mixPolicy}</strong>
                                </div>
                                <div>
                                  <span>模块数量</span>
                                  <strong>{task.modules.length}</strong>
                                </div>
                                <div>
                                  <span>后端状态</span>
                                  <strong>展示占位</strong>
                                </div>
                              </div>
                              <div className="visual-module-grid">
                                {task.modules.map((module) => (
                                  <div className="visual-module-card" key={module.id}>
                                    <div className="visual-module-thumb">
                                      <span>{module.order}</span>
                                      {module.imageUrl ? (
                                        <Image
                                          alt={module.title}
                                          height={54}
                                          preview={false}
                                          referrerPolicy="no-referrer"
                                          src={module.imageUrl}
                                          width={54}
                                        />
                                      ) : (
                                        <PictureOutlined />
                                      )}
                                    </div>
                                    <div className="visual-module-copy">
                                      <Text strong ellipsis>
                                        {module.title}
                                      </Text>
                                      <Text type="secondary" ellipsis>
                                        {module.targetLabel}
                                      </Text>
                                      <Space size={4} wrap>
                                        <Tag color={module.statusMeta.color} icon={module.statusMeta.icon}>
                                          {module.statusMeta.label}
                                        </Tag>
                                        <Tag color={module.sourceColor}>{module.sourceLabel}</Tag>
                                      </Space>
                                    </div>
                                    <div className="visual-module-actions">
                                      {module.slotId ? (
                                        <Button
                                          size="small"
                                          onClick={() => {
                                            setManagerActiveSlotId(module.slotId);
                                            setImageManagerActiveTab('product');
                                          }}
                                        >
                                          查看槽位
                                        </Button>
                                      ) : (
                                        <Button disabled size="small">
                                          SKU 槽位
                                        </Button>
                                      )}
                                      {module.imageKind && task.id.includes('product-gallery') ? (
                                        <Button
                                          icon={<ReloadOutlined />}
                                          loading={regeneratingSlotKey === `${imageManagerRecord.id}:${module.imageKind}`}
                                          size="small"
                                          onClick={() => void regenerateRecordImageSlot(imageManagerRecord, module.imageKind)}
                                        >
                                          单张重生
                                        </Button>
                                      ) : null}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ),
                },
                {
                  key: 'sku',
                  label: (
                    <span>
                      <AppstoreOutlined /> SKU 图
                    </span>
                  ),
                  children: (
                    <div className="image-manager-sku-list">
                      {imageManagerRecord.skuEntries.map((entry) => {
                        const skuImageUrl = getSkuDisplayImageUrl(entry);
                        return (
                          <div className="image-manager-sku-row" key={entry.id}>
                            <span className="image-manager-sku-order">{entry.order}</span>
                            <span className="image-manager-sku-thumb">
                              {skuImageUrl ? (
                                <Image
                                  alt={entry.name}
                                  height={48}
                                  preview={false}
                                  referrerPolicy="no-referrer"
                                  src={skuImageUrl}
                                  width={48}
                                />
                              ) : (
                                'SKU'
                              )}
                            </span>
                            <div className="image-manager-sku-copy">
                              <Text strong>{entry.name}</Text>
                              <Text type="secondary">{entry.kind === 'combo' ? '组合 SKU' : '单 SKU'} · {entry.componentSkus.length || 1} 个组件</Text>
                            </div>
                            <Tag color={skuImageUrl ? 'green' : 'default'}>{skuImageUrl ? '有预览图' : '待图片'}</Tag>
                          </div>
                        );
                      })}
                    </div>
                  ),
                },
                {
                  key: 'history',
                  label: (
                    <span>
                      <HistoryOutlined /> 候选图片
                    </span>
                  ),
                  children: (
                    <div className="image-manager-history-grid">
                      {imageManagerAssetOptions.length > 0 ? (
                        imageManagerAssetOptions.map((option, index) => (
                          <button
                            className="image-manager-history-card"
                            key={option.asset.id}
                            type="button"
                            onClick={() => {
                              if (!managerActiveSlot) return;
                              replaceImageSlot(imageManagerRecord, managerActiveSlot, option.asset.id);
                            }}
                          >
                            <Image
                              alt={option.asset.alt || `候选图片 ${index + 1}`}
                              height={92}
                              preview={false}
                              referrerPolicy="no-referrer"
                              src={option.imageUrl}
                              width={92}
                            />
                            <span>
                              <strong>{option.asset.alt || `图片 ${index + 1}`}</strong>
                              <Text type="secondary">{getImageAssetSourceMeta(option.asset).label}</Text>
                            </span>
                          </button>
                        ))
                      ) : (
                        <Empty description="暂无候选图片" />
                      )}
                    </div>
                  ),
                },
                {
                  key: 'jobs',
                  label: (
                    <span>
                      <ClockCircleOutlined /> 生成记录
                    </span>
                  ),
                  children: (
                    <div className="image-manager-job-list">
                      {(imageManagerRecord.creativeJobs || []).length > 0 ? (
                        (imageManagerRecord.creativeJobs || []).map((job) => {
                          const statusMeta = getImageTaskStatusMeta(job.status, Boolean(job.resultImageUrl));
                          return (
                            <div className="image-manager-job-row" key={job.id}>
                              <Tag color={statusMeta.color} icon={statusMeta.icon}>
                                {statusMeta.label}
                              </Tag>
                              <div>
                                <Text strong>{job.imageLabel}</Text>
                                <Text type="secondary">{job.imageKind} · {formatRecordTime(job.updatedAt)}</Text>
                              </div>
                              {job.resultImageUrl ? (
                                <Text copyable={{ text: job.resultImageUrl }} type="secondary">
                                  OSS
                                </Text>
                              ) : null}
                            </div>
                          );
                        })
                      ) : (
                        <Empty description="暂无生成任务" />
                      )}
                    </div>
                  ),
                },
              ]}
            />

            <section className="image-manager-library-panel">
              <div className="image-manager-library-head">
                <div>
                  <Text strong>统一图库</Text>
                  <Text type="secondary">原图、SKU 图和生成图统一放在这里。需要回退时可以直接使用原图替换当前预览图。</Text>
                </div>
                <Tag>{imageManagerGalleryOptions.length} 张</Tag>
              </div>
              {imageManagerGalleryOptions.length > 0 ? (
                <div className="image-manager-library-grid">
                  {imageManagerGalleryOptions.map((option, index) => {
                    const canUseForProduct = option.asset.role === 'product-main' || option.asset.role === 'product-material';
                    return (
                      <button
                        className="image-manager-library-card"
                        disabled={!canUseForProduct || !managerActiveSlot}
                        key={option.asset.id}
                        type="button"
                        onClick={() => {
                          if (!managerActiveSlot || !canUseForProduct) return;
                          replaceImageSlot(imageManagerRecord, managerActiveSlot, option.asset.id);
                        }}
                      >
                        <Image
                          alt={option.asset.alt || `图库图片 ${index + 1}`}
                          height={72}
                          preview={false}
                          referrerPolicy="no-referrer"
                          src={option.imageUrl}
                          width={72}
                        />
                        <span>
                          <strong>{option.asset.alt || `图片 ${index + 1}`}</strong>
                          <Text type="secondary">{option.asset.role === 'sales-sku' ? 'SKU 图' : getImageAssetSourceMeta(option.asset).label}</Text>
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <Empty description="暂无图库图片" />
              )}
            </section>
          </div>
        ) : null}
      </Drawer>
      <Modal
        footer={null}
        open={imageSlotPickerOpen}
        title={`替换${getImageSlotLabel(activeSlotPickerSlot)}`}
        width={760}
        onCancel={() => setImageSlotPickerOpen(false)}
      >
        {activeSlotPickerOptions.length > 0 ? (
          <div className="link-image-slot-picker">
            {activeSlotPickerOptions.map((option, index) => {
              const active = option.asset.id === activeSlotPickerSlot?.assetId;
              return (
                <button
                  className={`link-image-slot-option ${active ? 'link-image-slot-option-active' : ''}`}
                  key={option.asset.id}
                  type="button"
                  onClick={() => replaceActiveImageSlot(option.asset.id)}
                >
                  <Image
                    alt={option.asset.alt || `候选图片 ${index + 1}`}
                    height={92}
                    preview={false}
                    referrerPolicy="no-referrer"
                    src={option.imageUrl}
                    width={92}
                  />
                  <span>
                    <strong>{option.asset.alt || `图片 ${index + 1}`}</strong>
                    <Text type="secondary">{option.asset.role}</Text>
                  </span>
                  <Tag color={active ? 'blue' : 'default'}>{active ? '当前使用' : '使用这张'}</Tag>
                </button>
              );
            })}
          </div>
        ) : (
          <Empty description="暂无可替换图片" />
        )}
      </Modal>
    </>
  );
}

function DataDeskPanel({
  onViewProduct,
  onProductsAddedToPool,
}: {
  onViewProduct: (product: Product) => void;
  onProductsAddedToPool: () => void;
}) {
  const [form] = Form.useForm<Filters>();
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [products, setProducts] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [productStats, setProductStats] = useState<ProductStats>(defaultStats);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);
  const [priceSortOrder, setPriceSortOrder] = useState<SortOrder>();
  const [gmvSortOrder, setGmvSortOrder] = useState<SortOrder>();
  const [categories, setCategories] = useState<ProductCategoryOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [addingToPool, setAddingToPool] = useState(false);

  const loadDataDeskProducts = useCallback(
    async (
      nextPage = page,
      nextPageSize = pageSize,
      nextFilters: Filters | string = filters,
      nextPriceSortOrder = priceSortOrder,
      nextGmvSortOrder = gmvSortOrder,
    ) => {
      const normalizedFilters = typeof nextFilters === 'string' ? { keyword: nextFilters } : nextFilters;
      setLoading(true);
      try {
        const response = await fetchProducts({
          page: nextPage,
          pageSize: nextPageSize,
          scope: 'all',
          sortBy: nextPriceSortOrder ? 'price' : nextGmvSortOrder ? 'gmv' : undefined,
          sortOrder: toBackendPriceSortOrder(nextPriceSortOrder || nextGmvSortOrder),
          ...normalizedFilters,
          keyword: normalizedFilters.keyword?.trim() || undefined,
        });
        setProducts(response.items.map(mapBackendProduct));
        setTotal(response.total);
      } catch (error) {
        message.error(error instanceof Error ? error.message : '数据台读取失败');
      } finally {
        setLoading(false);
      }
    },
    [filters, gmvSortOrder, page, pageSize, priceSortOrder],
  );

  const loadDataDeskStats = useCallback(async () => {
    try {
      setProductStats(await fetchProductStats('all'));
    } catch {
      setProductStats(defaultStats);
    }
  }, []);

  useEffect(() => {
    void loadDataDeskProducts(1, pageSize, filters);
    void loadDataDeskStats();
    fetchProductCategories()
      .then(setCategories)
      .catch(() => setCategories([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addSelectedToPool = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要加入商品池的商品');
      return;
    }

    setAddingToPool(true);
    try {
      const result = await addProductsToPool(selectedRowKeys.map(String));
      setSelectedRowKeys([]);
      await Promise.all([loadDataDeskProducts(page, pageSize, filters), loadDataDeskStats()]);
      onProductsAddedToPool();
      message.success(`已加入商品池：${result.added_count} 个商品`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加入商品池失败');
    } finally {
      setAddingToPool(false);
    }
  };

  return (
    <div className="data-desk-page">
      <div className="stats-grid data-desk-stats-grid">
        <Card className="metric-card metric-card-blue">
          <Statistic title="当前批次商品" value={productStats.active_count} />
        </Card>
        <Card className="metric-card metric-card-red">
          <Statistic title="近 7 天高销量" value={productStats.recent_7_count} />
        </Card>
        <Card className="metric-card metric-card-yellow">
          <Statistic title="近 30 天高销量" value={productStats.recent_30_count} />
        </Card>
        <Card className="metric-card metric-card-gray">
          <Statistic title="已删除" value={productStats.deleted_count} />
        </Card>
      </div>

      <Card className="filter-card data-desk-filter-card" title="筛选器">
        <Form
          form={form}
          initialValues={defaultFilters}
          layout="inline"
          onFinish={(values) => {
            setFilters(values);
            setPage(1);
            void loadDataDeskProducts(1, pageSize, values);
          }}
        >
          <Form.Item label="关键词" name="keyword">
            <Input allowClear placeholder="搜索商品标题 / ID" />
          </Form.Item>
          <Form.Item label="类目" name="category">
            <CategoryCascaderFilter categories={categories} />
          </Form.Item>
          <Form.Item label="时间范围" name="period">
            <Select
              style={{ width: 130 }}
              options={[
                { value: '全部', label: '全部' },
                { value: '近7天', label: '近 7 天' },
                { value: '近30天', label: '近 30 天' },
              ]}
            />
          </Form.Item>
          <Form.Item label="价格区间" name="priceRange">
            <Input allowClear placeholder="¥0 - ¥999" />
          </Form.Item>
          <Form.Item label="销量区间" name="salesRange">
            <Input allowClear placeholder="不限" />
          </Form.Item>
          <Form.Item label="GMV 区间" name="gmvRange">
            <Input allowClear placeholder="不限" />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button htmlType="submit" type="primary">
                筛选
              </Button>
              <Button
                onClick={() => {
                  form.setFieldsValue(defaultFilters);
                  setFilters(defaultFilters);
                  setPage(1);
                  void loadDataDeskProducts(1, pageSize, defaultFilters);
                  void loadDataDeskStats();
                }}
              >
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      <Card
        className="table-card data-desk-table-card"
        loading={loading}
        extra={
          <Button
            disabled={selectedRowKeys.length === 0}
            loading={addingToPool}
            type="primary"
            onClick={addSelectedToPool}
          >
            加入商品池
          </Button>
        }
        title={
          <Space>
            <span>商品列表</span>
            <Text type="secondary">已选择 {selectedRowKeys.length} 条</Text>
          </Space>
        }
      >
        <ProductTable
          products={products}
          total={total}
          currentPage={page}
          pageSize={pageSize}
          selectedRowKeys={selectedRowKeys}
          onSelectedRowKeysChange={setSelectedRowKeys}
          onPageChange={(nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
            void loadDataDeskProducts(nextPage, nextPageSize, filters);
          }}
          priceSortOrder={priceSortOrder}
          onPriceSortChange={(order) => {
            setPriceSortOrder(order);
            setGmvSortOrder(undefined);
            setPage(1);
            void loadDataDeskProducts(1, pageSize, filters, order, undefined);
          }}
          gmvSortOrder={gmvSortOrder}
          onGmvSortChange={(order) => {
            setGmvSortOrder(order);
            setPriceSortOrder(undefined);
            setPage(1);
            void loadDataDeskProducts(1, pageSize, filters, undefined, order);
          }}
          onView={onViewProduct}
          onDelete={(product) => {
            deleteBackendProduct(product.id, 'all')
              .then(() => loadDataDeskProducts(page, pageSize, filters))
              .then(() => loadDataDeskStats())
              .then(() => {
                setSelectedRowKeys((keys) => keys.filter((key) => key !== product.id));
                message.success('商品已删除');
              })
              .catch((error) => message.error(error.message || '删除失败'));
          }}
        />
      </Card>
    </div>
  );
}

export function SelectProductPage({
  currentUser,
  onLogout,
}: {
  currentUser: CurrentUser;
  onLogout: () => void;
}) {
  const isAdminUser = currentUser.role === 'admin';
  const [form] = Form.useForm<Filters>();
  const [products, setProducts] = useState<Product[]>(mockProducts);
  const [productTotal, setProductTotal] = useState(mockProducts.length);
  const [productStats, setProductStats] = useState<ProductStats>(defaultStats);
  const [backendReady, setBackendReady] = useState(false);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [priceSortOrder, setPriceSortOrder] = useState<SortOrder>();
  const [gmvSortOrder, setGmvSortOrder] = useState<SortOrder>();
  const [categories, setCategories] = useState<ProductCategoryOption[]>([]);
  const [importOpen, setImportOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportingTemplate, setExportingTemplate] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMode, setDrawerMode] = useState<'sourcing' | 'sales'>('sourcing');
  const [activeProduct, setActiveProduct] = useState<Product | undefined>();
  const [sourcingSearched, setSourcingSearched] = useState(false);
  const [activeCandidate, setActiveCandidate] = useState<SourcingCandidate | undefined>();
  const [activeTab, setActiveTab] = useState<'search' | 'detail'>('search');
  const [activeWorkbenchTab, setActiveWorkbenchTab] = useState<WorkbenchTab>(() =>
    isAdminUser ? 'admin' : 'sourcing',
  );
  const [linkListRecords, setLinkListRecords] = useState<LinkListRecord[]>(() => readLinkListRecords(currentUser.id));

  const loadProducts = useCallback(
    async (
      nextPage = currentPage,
      nextPageSize = pageSize,
      nextFilters = filters,
      nextPriceSortOrder = priceSortOrder,
      nextGmvSortOrder = gmvSortOrder,
    ) => {
      setLoadingProducts(true);
      try {
        const response = await fetchProducts({
          page: nextPage,
          pageSize: nextPageSize,
          sortBy: nextPriceSortOrder ? 'price' : nextGmvSortOrder ? 'gmv' : undefined,
          sortOrder: toBackendPriceSortOrder(nextPriceSortOrder || nextGmvSortOrder),
          ...nextFilters,
        });
        setProducts(response.items.map(mapBackendProduct));
        setProductTotal(response.total);
        setBackendReady(true);
      } catch {
        setBackendReady(false);
        const fallbackProducts = mockProducts.filter((product) => {
          if (nextFilters.period && nextFilters.period !== '全部' && product.period !== nextFilters.period) {
            return false;
          }
          if (
            nextFilters.category &&
            nextFilters.category !== ALL_CATEGORY_VALUE &&
            product.category !== nextFilters.category &&
            product.categoryLevel1 !== nextFilters.category &&
            product.categoryLevel2 !== nextFilters.category &&
            product.categoryPath !== nextFilters.category
          ) {
            return false;
          }
          if (
            nextFilters.keyword &&
            !product.title.toLowerCase().includes(nextFilters.keyword.toLowerCase()) &&
            !(product.titleEn || '').toLowerCase().includes(nextFilters.keyword.toLowerCase()) &&
            !product.id.toLowerCase().includes(nextFilters.keyword.toLowerCase())
          ) {
            return false;
          }
          if (!matchesRange(product.price, nextFilters.priceRange)) return false;
          if (!matchesRange(product.sales, nextFilters.salesRange)) return false;
          if (!matchesRange(product.gmv, nextFilters.gmvRange)) return false;
          return product.status !== 'deleted';
        });
        const sortedFallbackProducts = nextPriceSortOrder || nextGmvSortOrder
          ? [...fallbackProducts].sort((left, right) =>
              nextPriceSortOrder
                ? nextPriceSortOrder === 'ascend'
                  ? left.price - right.price
                  : right.price - left.price
                : nextGmvSortOrder === 'ascend'
                  ? left.gmv - right.gmv
                  : right.gmv - left.gmv,
            )
          : fallbackProducts;
        setProducts(sortedFallbackProducts.slice((nextPage - 1) * nextPageSize, nextPage * nextPageSize));
        setProductTotal(fallbackProducts.length);
      } finally {
        setLoadingProducts(false);
      }
    },
    [currentPage, filters, gmvSortOrder, pageSize, priceSortOrder],
  );

  const loadStats = useCallback(async () => {
    try {
      const stats = await fetchProductStats();
      setProductStats(stats);
      setBackendReady(true);
    } catch {
      setProductStats(defaultStats);
    }
  }, []);

  const warnLinkPersistenceFailure = useCallback((error: unknown) => {
    console.error(error);
    message.warning('链接列表已先保存在本地，后端持久化失败，请确认后端已启动');
  }, []);

  useEffect(() => {
    if (isAdminUser) return;
    void loadProducts(1, pageSize, filters);
    void loadStats();
    fetchProductCategories()
      .then(setCategories)
      .catch(() => setCategories([]));
    setCurrentPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (isAdminUser) return undefined;
    let active = true;

    const loadLinkRecords = async () => {
      const localRecords = readLinkListRecords(currentUser.id);
      try {
        const backendRecords = await fetchLinkListRecords();
        if (!active) return;

        if (backendRecords.length > 0 || localRecords.length === 0) {
          setLinkListRecords(backendRecords);
          writeLinkListRecords(backendRecords, currentUser.id);
          return;
        }

        await saveLinkListRecords(localRecords);
        if (!active) return;
        setLinkListRecords(localRecords);
        writeLinkListRecords(localRecords, currentUser.id);
      } catch (error) {
        if (!active) return;
        if (localRecords.length > 0) {
          setLinkListRecords(localRecords);
        }
        console.error(error);
        message.warning('链接列表后端读取失败，当前使用本地缓存');
      }
    };

    void loadLinkRecords();

    return () => {
      active = false;
    };
  }, [currentUser.id, isAdminUser]);

  const activeCount = productStats.active_count;
  const deletedCount = productStats.deleted_count;

  const openProduct = useCallback((product: Product, options: { syncUrl?: boolean; drawerMode?: 'sourcing' | 'sales' } = {}) => {
    setActiveProduct(product);
    setDrawerMode(options.drawerMode || 'sourcing');
    setSourcingSearched(product.status === 'sourced');
    setActiveCandidate(undefined);
    setActiveTab('search');
    setDrawerOpen(true);
    if (options.syncUrl !== false) syncProductRoute(product);
  }, []);

  const closeProduct = useCallback(() => {
    setDrawerOpen(false);
    clearProductRoute();
  }, []);

  const recordLinkEntry = useCallback(
    (record: LinkListRecord) => {
      setLinkListRecords((current) => {
        const next = [record, ...current.filter((item) => item.id !== record.id)].slice(0, 200);
        writeLinkListRecords(next, currentUser.id);
        return next;
      });
      void saveLinkListRecord(record).catch(warnLinkPersistenceFailure);
      closeProduct();
      setActiveWorkbenchTab('links');
      message.success('已录入链接列表');
    },
    [closeProduct, currentUser.id, warnLinkPersistenceFailure],
  );

  const deleteLinkEntry = useCallback((recordId: string) => {
    setLinkListRecords((current) => {
      const next = current.filter((record) => record.id !== recordId);
      writeLinkListRecords(next, currentUser.id);
      return next;
    });
    void deleteLinkListRecord(recordId).catch(warnLinkPersistenceFailure);
    message.success('已删除链接记录');
  }, [warnLinkPersistenceFailure]);

  const updateLinkEntry = useCallback((record: LinkListRecord) => {
    setLinkListRecords((current) => {
      const next = current.map((item) => (item.id === record.id ? record : item));
      writeLinkListRecords(next, currentUser.id);
      return next;
    });
    void saveLinkListRecord(record).catch(warnLinkPersistenceFailure);
  }, [currentUser.id, warnLinkPersistenceFailure]);

  const exportTemplate = useCallback(async () => {
    if (linkListRecords.length === 0) {
      message.warning('请先在商品池中录入链接列表，再导出 Excel');
      return;
    }

    setExportingTemplate(true);
    try {
      const syncResult = await syncPluginCreativeJobs(linkListRecords);
      const recordsForExport = syncResult.records;
      if (syncResult.records.length > 0) {
        setLinkListRecords(syncResult.records);
        writeLinkListRecords(syncResult.records, currentUser.id);
        void saveLinkListRecords(syncResult.records).catch(warnLinkPersistenceFailure);
      }

      const blob = await exportDianxiaomiTemuTemplate(recordsForExport);
      downloadBlob(blob, `店小秘_TEMU半托管_${new Date().toISOString().slice(0, 10)}.xlsx`);
      setExportOpen(false);
      message.success('Excel 已生成，请手动导入店小秘');
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Excel 导出失败');
    } finally {
      setExportingTemplate(false);
    }
  }, [currentUser.id, linkListRecords, warnLinkPersistenceFailure]);

  const openProductFromRoute = useCallback(async () => {
    if (isAdminUser) {
      setDrawerOpen(false);
      clearProductRoute();
      return;
    }

    const route = parseProductRoute();
    if (!route) {
      setDrawerOpen(false);
      return;
    }

    const visibleProduct = products.find((product) => matchesProductRoute(product, route));
    if (visibleProduct) {
      openProduct(visibleProduct, { syncUrl: false });
      return;
    }

    try {
      const response = await fetchProducts({
        page: 1,
        pageSize,
        keyword: route.sourceProductId,
      });
      const routedProducts = response.items.map(mapBackendProduct);
      const routedProduct = routedProducts.find((product) => matchesProductRoute(product, route));
      if (!routedProduct) return;

      setProducts(routedProducts);
      setProductTotal(response.total);
      setCurrentPage(1);
      setBackendReady(true);
      openProduct(routedProduct, { syncUrl: false });
    } catch {
      const fallbackProduct = mockProducts.find((product) => matchesProductRoute(product, route));
      if (fallbackProduct) openProduct(fallbackProduct, { syncUrl: false });
    }
  }, [isAdminUser, openProduct, pageSize, products]);

  useEffect(() => {
    void openProductFromRoute();
    window.addEventListener('hashchange', openProductFromRoute);
    return () => window.removeEventListener('hashchange', openProductFromRoute);
  }, [openProductFromRoute]);

  const deleteProduct = (product: Product) => {
    const applyLocalDelete = () => {
      setProducts((current) =>
        current.map((item) => (item.id === product.id ? { ...item, status: 'deleted' } : item)),
      );
      setProductStats((current) => ({
        ...current,
        active_count: Math.max(0, current.active_count - 1),
        deleted_count: current.deleted_count + 1,
      }));
      setSelectedRowKeys((keys) => keys.filter((key) => key !== product.id));
      if (activeProduct?.id === product.id) closeProduct();
      message.success('商品已删除');
    };

    if (!backendReady) {
      applyLocalDelete();
      return;
    }

    deleteBackendProduct(product.id)
      .then(() => loadProducts(currentPage, pageSize, filters))
      .then(() => loadStats())
      .then(() => {
        if (activeProduct?.id === product.id) closeProduct();
        message.success('商品已删除');
      })
      .catch((error) => message.error(error.message || '删除失败'));
  };

  const selectCandidate = (product: Product, candidate: SourcingCandidate) => {
    setProducts((current) =>
      current.map((item) => (item.id === product.id ? { ...item, status: 'sourced' } : item)),
    );
    setActiveProduct({ ...product, status: 'sourced' });
    setActiveCandidate(candidate);
    message.success('已选为候选货源');
  };

  const resetFilters = () => {
    form.setFieldsValue(defaultFilters);
    setFilters(defaultFilters);
    setCurrentPage(1);
    void loadProducts(1, pageSize, defaultFilters);
  };

  return (
    <Layout className={`app-layout ${isAdminUser ? 'admin-layout' : ''}`}>
      <Header className={`app-header ${isAdminUser ? 'admin-app-header' : ''}`}>
        <div className="app-header-inner">
          <div className="brand">Temu 选品上架工作台</div>
          <nav aria-label="主导航" className={`main-nav ${isAdminUser ? 'admin-main-nav' : ''}`}>
            {!isAdminUser ? (
              <>
                <button
                  className={`main-nav-item ${activeWorkbenchTab === 'data' ? 'main-nav-active' : ''}`}
                  type="button"
                  onClick={() => setActiveWorkbenchTab('data')}
                >
                  数据台
                </button>
                <button
                  className={`main-nav-item ${activeWorkbenchTab === 'sourcing' ? 'main-nav-active' : ''}`}
                  type="button"
                  onClick={() => setActiveWorkbenchTab('sourcing')}
                >
                  商品池
                </button>
                <button
                  className={`main-nav-item ${activeWorkbenchTab === 'links' ? 'main-nav-active' : ''}`}
                  type="button"
                  onClick={() => setActiveWorkbenchTab('links')}
                >
                  链接列表
                </button>
              </>
            ) : null}
            {isAdminUser ? (
              <button
                className={`main-nav-item ${activeWorkbenchTab === 'admin' ? 'main-nav-active' : ''}`}
                type="button"
                onClick={() => setActiveWorkbenchTab('admin')}
              >
                管理员后台
              </button>
            ) : null}
          </nav>
          <Space className="header-actions">
            {!isAdminUser ? <span className="batch-pill">当前批次：云启 0522</span> : null}
            <span className="user-pill">{currentUser.displayName || currentUser.username}</span>
            {!isAdminUser ? (
              <>
                <Button className="header-button" type="primary" onClick={() => setImportOpen(true)}>
                  数据导入
                </Button>
                <Button className="header-button" onClick={() => setExportOpen(true)}>
                  清单导出
                </Button>
              </>
            ) : null}
            <Button className="header-button" onClick={onLogout}>
              退出
            </Button>
          </Space>
        </div>
      </Header>

      <Content className="page-content">
        <div className="page-shell">
          {isAdminUser ? (
            <AdminPage />
          ) : activeWorkbenchTab === 'links' ? (
            <LinkListPanel
              records={linkListRecords}
              onDelete={deleteLinkEntry}
              onUpdate={updateLinkEntry}
            />
          ) : activeWorkbenchTab === 'admin' ? (
            <AdminPage />
          ) : activeWorkbenchTab === 'data' ? (
            <DataDeskPanel
              onProductsAddedToPool={() => {
                void loadProducts(currentPage, pageSize, filters);
                void loadStats();
              }}
              onViewProduct={(product) => openProduct(product, { drawerMode: 'sales', syncUrl: false })}
            />
          ) : (
            <>
          <div className="stats-grid">
            <Card className="metric-card metric-card-blue">
              <Statistic title={backendReady ? '当前批次商品' : '演示商品'} value={activeCount} />
            </Card>
            <Card className="metric-card metric-card-red">
              <Statistic title="近 7 天高销量" value={productStats.recent_7_count} />
            </Card>
            <Card className="metric-card metric-card-yellow">
              <Statistic title="近 30 天高销量" value={productStats.recent_30_count} />
            </Card>
            <Card className="metric-card metric-card-gray">
              <Statistic title="已删除" value={deletedCount} />
            </Card>
          </div>

          <Card className="filter-card" title="筛选器">
            <Form
              form={form}
              layout="inline"
              onFinish={(values) => {
                setFilters(values);
                setCurrentPage(1);
                void loadProducts(1, pageSize, values);
              }}
              initialValues={defaultFilters}
            >
              <Form.Item label="关键词" name="keyword">
                <Input allowClear placeholder="搜索商品标题 / ID" />
              </Form.Item>
              <Form.Item label="类目" name="category">
                <CategoryCascaderFilter categories={categories} />
              </Form.Item>
              <Form.Item label="时间范围" name="period">
                <Select
                  style={{ width: 130 }}
                  options={[
                    { value: '全部', label: '全部' },
                    { value: '近7天', label: '近 7 天' },
                    { value: '近30天', label: '近 30 天' },
                  ]}
                />
              </Form.Item>
              <Form.Item label="价格区间" name="priceRange">
                <Input allowClear placeholder="¥0 - ¥999" />
              </Form.Item>
              <Form.Item label="销量区间" name="salesRange">
                <Input allowClear placeholder="不限" />
              </Form.Item>
              <Form.Item label="GMV 区间" name="gmvRange">
                <Input allowClear placeholder="不限" />
              </Form.Item>
              <Form.Item>
                <Space>
                  <Button htmlType="submit" type="primary">
                    筛选
                  </Button>
                  <Button onClick={resetFilters}>重置</Button>
                </Space>
              </Form.Item>
            </Form>
          </Card>

          <Card
            className="table-card"
            title={
              <Space>
                <span>商品列表</span>
                <Text type="secondary">已选择 {selectedRowKeys.length} 条</Text>
              </Space>
            }
          >
            <ProductTable
              products={products}
              total={productTotal}
              currentPage={currentPage}
              pageSize={pageSize}
              selectedRowKeys={selectedRowKeys}
              onSelectedRowKeysChange={setSelectedRowKeys}
              onPageChange={(page, nextPageSize) => {
                setCurrentPage(page);
                setPageSize(nextPageSize);
                void loadProducts(page, nextPageSize, filters);
              }}
              priceSortOrder={priceSortOrder}
              onPriceSortChange={(order) => {
                setPriceSortOrder(order);
                setGmvSortOrder(undefined);
                setCurrentPage(1);
                void loadProducts(1, pageSize, filters, order, undefined);
              }}
              gmvSortOrder={gmvSortOrder}
              onGmvSortChange={(order) => {
                setGmvSortOrder(order);
                setPriceSortOrder(undefined);
                setCurrentPage(1);
                void loadProducts(1, pageSize, filters, undefined, order);
              }}
              onView={openProduct}
              onDelete={deleteProduct}
            />
          </Card>
            </>
          )}
        </div>
      </Content>

      <DataImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImport={async (file) => {
          const result = await uploadYunqiFile(file);
          setImportOpen(false);
          message.success(`导入完成：${result.imported_count} 条商品`);
          setCurrentPage(1);
          await Promise.all([loadProducts(1, pageSize, filters), loadStats()]);
        }}
        onImport1688Links={async (productUrls) => {
          const result = await upload1688Links(productUrls);
          setImportOpen(false);
          message.success(`1688 采集完成：${result.imported_count} 条商品`);
          if (result.errors.length > 0) {
            message.warning(`有 ${result.errors.length} 条使用链接兜底导入`);
          }
          setCurrentPage(1);
          await Promise.all([loadProducts(1, pageSize, filters), loadStats()]);
        }}
      />

      <ProductDetailDrawer
        open={drawerOpen}
        product={activeProduct}
        mode={drawerMode}
        searched={sourcingSearched}
        activeCandidate={activeCandidate}
        activeTab={activeTab}
        onClose={closeProduct}
        onSearch={() => {
          setSourcingSearched(true);
          setActiveTab('search');
        }}
        onOpenCandidateDetail={(candidate) => {
          setActiveCandidate(candidate);
          setActiveTab('detail');
        }}
        onBackToSearch={() => setActiveTab('search')}
        onSelectCandidate={selectCandidate}
        onRecordLinkEntry={recordLinkEntry}
      />

      <Modal
        title="店小秘 TEMU 半托管 Excel 导出"
        open={exportOpen}
        confirmLoading={exportingTemplate}
        onCancel={() => setExportOpen(false)}
        onOk={exportTemplate}
        okText="导出 Excel"
        cancelText="取消"
      >
        <Space direction="vertical" size={16} className="export-modal-content">
          <Text type="secondary">
            这里只生成店小秘 TEMU 半托管 Excel 文件；导出后请手动进入店小秘后台上传导入。
          </Text>
          <Card size="small" title="导出范围">
            <Space direction="vertical">
              <Text strong>链接列表商品：{linkListRecords.length} 个</Text>
              <Text>销售 SKU：{linkListRecords.reduce((total, record) => total + record.skuEntries.length, 0)} 个</Text>
              <Text>图片策略：优先使用改图后的云端图片；没有改图时使用采集到的原图。轮播图最多 10 张，产品描述同步写入轮播图 URL。</Text>
            </Space>
          </Card>
          <Card size="small" title="默认字段">
            <Space direction="vertical">
              <Text>变种属性：按店小秘下拉枚举自动匹配（颜色/风格/材质/数量/型号等）</Text>
              <Text>包装：不规则 / 硬包装</Text>
              <Text>尺寸重量缺失时：10 × 10 × 5 cm，200 g</Text>
              <Text>库存：0；发货时效：空</Text>
            </Space>
          </Card>
        </Space>
      </Modal>
    </Layout>
  );
}
