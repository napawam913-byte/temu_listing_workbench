import {
  Alert,
  Button,
  Card,
  Checkbox,
  DatePicker,
  Drawer,
  Empty,
  Form,
  Image,
  Input,
  Layout,
  Modal,
  Popover,
  Progress,
  Select,
  Segmented,
  Space,
  Statistic,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  FileExcelOutlined,
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
  cancelDianxiaomiExportTask,
  addProductsToPool,
  createDianxiaomiExportTask,
  deleteDianxiaomiExportTask,
  createVisualGenerationTask,
  deleteVisualGenerationTask,
  deleteProduct as deleteBackendProduct,
  deleteLinkListRecord,
  downloadDianxiaomiExportTask,
  fetchDianxiaomiExportTasks,
  fetchVisualGenerationTask,
  fetchVisualGenerationTasks,
  fetchVisualQueueSummary,
  fetchLinkListRecords,
  fetchProductCategories,
  fetchProductStats,
  fetchProducts,
  mapBackendProduct,
  runVisualGenerationTask,
  saveLinkListRecord,
  saveLinkListRecords,
  regeneratePluginCreativeJob,
  syncPluginCreativeJobs,
  uploadDianxiaomiTemplateFile,
} from '../api/backendApi';
import type {
  CurrentUser,
  DianxiaomiExportTask,
  ProductCategoryOption,
  ProductStats,
  VisualGenerationTask,
  VisualQueueSummary,
} from '../api/backendApi';
import { DataImportModal } from '../components/DataImportModal';
import { ProductDetailDrawer } from '../components/ProductDetailDrawer';
import { ProductTable } from '../components/ProductTable';
import { AdminPage } from './AdminPage';
import { mockProducts } from '../mock/products';
import type { LinkListCreativeJobSummary, LinkListImageAsset, LinkListImageSlot, LinkListRecord } from '../types/linkList';
import type { Product, ProductSourceType, SourcingCandidate } from '../types/product';

const { Header, Content } = Layout;
const { Text } = Typography;
const { RangePicker } = DatePicker;
const EXPORT_TEMPLATE_MESSAGE_KEY = 'dianxiaomi-temu-template-export';
const ALL_CATEGORY_VALUE = '全部类目';

type DateRangeDate = {
  format: (template: string) => string;
};

type DateRangeValue = Array<DateRangeDate | null>;

type Filters = {
  keyword?: string;
  period?: Product['period'] | '全部';
  category?: string;
  priceRange?: string;
  salesRange?: string;
  gmvRange?: string;
};

type ProductPoolFilters = {
  keyword?: string;
  selectedDateRange?: DateRangeValue;
  priceRange?: string;
};

const defaultFilters: Filters = {
  period: '全部',
  category: ALL_CATEGORY_VALUE,
};

const defaultProductPoolFilters: ProductPoolFilters = {};

const PRODUCT_ROUTE_PREFIX = '#/products/';

type ProductRoute = {
  sourceType: ProductSourceType;
  sourceProductId: string;
};

type WorkbenchTab = 'data' | 'sourcing' | 'links' | 'admin';
type VisualPublishMode = 'main_multi' | 'sku_adapt' | 'single_refine';
type QueueTaskFilter = 'all' | 'visual' | 'excel';

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
  backendTaskId?: string;
  backendStatus?: string;
  errorMessage?: string;
  analysis?: Record<string, unknown>;
  promptText?: string;
  motherImageUrl?: string;
  motherImagePath?: string;
  manifest?: Record<string, unknown>;
  styleProfileId: string;
  styleLockLabel: string;
  styleLockStatus: string;
  referenceImageUrl?: string;
  referenceImageUrls?: string[];
  referenceImageLabels?: string[];
  selectedSkuIds?: string[];
  selectedSlotIds?: string[];
  createdAt: string;
  modules: Array<{
    id: string;
    order: number;
    slotId?: string;
    skuEntryId?: string;
    title: string;
    targetLabel: string;
    imageKind?: string;
    imageUrl?: string;
    outputUrl?: string;
    outputPath?: string;
    sourceLabel: string;
    statusLabel: string;
    statusColor: string;
  }>;
};

type ImageManagerGalleryOption = {
  asset: LinkListImageAsset;
  imageUrl: string;
};

type ImageManagerBindingImageOption = ImageManagerGalleryOption & {
  label: string;
  sourceLabel: string;
};

const ACTIVE_VISUAL_BACKEND_STATUSES = new Set(['creating', 'queued', 'running', 'retry_waiting']);
const LOCAL_VISUAL_QUEUE_FALLBACK_WORKERS = 5;
const LOCAL_VISUAL_QUEUE_MAX_ATTEMPTS_PER_CLICK = 2;

type SkuImageBindingTarget = {
  key: string;
  subjectKey: string;
  mode: 'sku' | 'component';
  skuEntryId: string;
  skuName: string;
  componentIndex?: number;
  componentName: string;
};

type SkuImageBindingSubject = {
  key: string;
  label: string;
  targets: SkuImageBindingTarget[];
};

const LINK_LIST_STORAGE_KEY = 'temuListingWorkbenchLinkListRecords';
const CURATED_EXPORT_IMAGE_COUNT = 8;
const FULL_MAIN_GALLERY_IMAGE_COUNT = 9;
const COMPACT_MAIN_GALLERY_IMAGE_COUNT = 4;
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
  { kind: '09-selling-point', label: '卖点图' },
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
  const cleanValue = String(value || '').trim();
  const normalizedValue = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(cleanValue)
    ? `${cleanValue.replace(' ', 'T')}Z`
    : cleanValue;
  const date = new Date(normalizedValue);
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

function getProductPoolRequestFilters(filters: ProductPoolFilters) {
  const [start, end] = filters.selectedDateRange || [];
  return {
    keyword: filters.keyword?.trim() || undefined,
    priceRange: filters.priceRange,
    poolAddedStart: start?.format('YYYY-MM-DD'),
    poolAddedEnd: end?.format('YYYY-MM-DD'),
  };
}

function matchesProductPoolDateRange(product: Product, range?: DateRangeValue) {
  const [start, end] = range || [];
  if (!start && !end) return true;
  const dateValue = product.selectedAt || product.listedAt;
  if (!dateValue) return false;
  const normalizedDate = dateValue.slice(0, 10);
  if (start && normalizedDate < start.format('YYYY-MM-DD')) return false;
  if (end && normalizedDate > end.format('YYYY-MM-DD')) return false;
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

const MAX_CATEGORY_DEPTH = 4;
const CATEGORY_LEVEL_LABELS = ['一级类目', '二级类目', '三级类目', '四级类目'];

type CategoryCascaderColumn = {
  key: string;
  level: number;
  title: string;
  items: ProductCategoryOption[];
  parent?: ProductCategoryOption;
};

function filterCategoryTree(categories: ProductCategoryOption[], query: string, parentLabel = ''): ProductCategoryOption[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return categories;

  const results: ProductCategoryOption[] = [];
  categories.forEach((category) => {
    const pathLabel = [parentLabel, category.label, category.value].filter(Boolean).join(' ');
    const categoryMatches = pathLabel.toLowerCase().includes(normalizedQuery);
    const children = filterCategoryTree(category.children || [], normalizedQuery, pathLabel);
    if (categoryMatches) {
      results.push({ ...category, children: category.children || [] });
      return;
    }
    if (children.length > 0) {
      results.push({ ...category, children });
    }
  });

  return results;
}

function findCategoryPath(
  categories: ProductCategoryOption[],
  value?: string,
  trail: ProductCategoryOption[] = [],
): ProductCategoryOption[] {
  if (!value || value === ALL_CATEGORY_VALUE) return [];

  for (const category of categories) {
    const nextTrail = [...trail, category];
    if (category.value === value) return nextTrail;
    if (nextTrail.length < MAX_CATEGORY_DEPTH) {
      const childTrail = findCategoryPath(category.children || [], value, nextTrail);
      if (childTrail.length > 0) return childTrail;
    }
  }

  return [];
}

function getCategoryDisplayLabelV2(categories: ProductCategoryOption[], value?: string) {
  if (!value || value === ALL_CATEGORY_VALUE) return ALL_CATEGORY_VALUE;
  const path = findCategoryPath(categories, value);
  return path.length > 0 ? path.map((category) => category.label).join(' / ') : value;
}

function buildCategoryColumns(categories: ProductCategoryOption[], activePath: ProductCategoryOption[]): CategoryCascaderColumn[] {
  const columns: CategoryCascaderColumn[] = [
    {
      key: 'level-1',
      level: 1,
      title: CATEGORY_LEVEL_LABELS[0],
      items: categories,
    },
  ];

  activePath.slice(0, MAX_CATEGORY_DEPTH - 1).forEach((category, index) => {
    const children = category.children || [];
    if (children.length === 0) return;
    columns.push({
      key: category.value,
      level: index + 2,
      title: category.label,
      items: children,
      parent: category,
    });
  });

  return columns.slice(0, MAX_CATEGORY_DEPTH);
}

function CategoryCascaderFilterV2({
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
  const [activeCategoryValue, setActiveCategoryValue] = useState<string>();
  const normalizedSearchText = searchText.trim();

  const filteredCategories = useMemo(
    () => filterCategoryTree(categories, normalizedSearchText),
    [categories, normalizedSearchText],
  );
  const selectedPath = useMemo(() => findCategoryPath(filteredCategories, value), [filteredCategories, value]);
  const activePath = useMemo(() => {
    const hoveredPath = findCategoryPath(filteredCategories, activeCategoryValue);
    return hoveredPath.length > 0 ? hoveredPath : selectedPath;
  }, [activeCategoryValue, filteredCategories, selectedPath]);
  const columns = useMemo(() => buildCategoryColumns(filteredCategories, activePath), [activePath, filteredCategories]);
  const selectedDisplayLabel = getCategoryDisplayLabelV2(categories, value);

  useEffect(() => {
    if (activeCategoryValue && findCategoryPath(filteredCategories, activeCategoryValue).length === 0) {
      setActiveCategoryValue(undefined);
    }
  }, [activeCategoryValue, filteredCategories]);

  const selectCategory = (nextValue?: string) => {
    const finalValue = nextValue || ALL_CATEGORY_VALUE;
    onChange?.(finalValue);
    setActiveCategoryValue(finalValue === ALL_CATEGORY_VALUE ? undefined : finalValue);
    setOpen(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setSearchText('');
      setActiveCategoryValue(undefined);
    }
  };

  const panel = (
    <div className="category-cascader-panel">
      <div className="category-cascader-search">
        <Input
          allowClear
          placeholder="搜索一级 / 二级 / 三级 / 四级类目"
          size="small"
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
        />
      </div>
      <div
        className="category-cascader-body"
        style={{ gridTemplateColumns: `repeat(${Math.max(columns.length, 1)}, minmax(230px, 1fr))` }}
      >
        {columns.map((column) => {
          const levelLabel = CATEGORY_LEVEL_LABELS[column.level - 1] || `${column.level}级类目`;
          const columnTitle = `${column.parent ? column.title : levelLabel}（${column.items.length}）`;
          return (
            <div className="category-cascader-column" key={column.key}>
              <div className="category-cascader-group-title">{columnTitle}</div>
              {column.parent ? (
                <button
                  className={`category-cascader-row ${
                    value === column.parent.value ? 'category-cascader-selected' : ''
                  }`}
                  title={`全部 ${column.parent.label}`}
                  type="button"
                  onClick={() => selectCategory(column.parent?.value)}
                >
                  <span className="category-check" />
                  <span className="category-cascader-name">全部 {column.parent.label}</span>
                  <span className="category-cascader-count">{column.parent.count}</span>
                </button>
              ) : (
                <button
                  className={`category-cascader-row ${
                    !value || value === ALL_CATEGORY_VALUE ? 'category-cascader-selected' : ''
                  }`}
                  type="button"
                  onClick={() => selectCategory(ALL_CATEGORY_VALUE)}
                >
                  <span className="category-check" />
                  <span className="category-cascader-name">全部类目</span>
                </button>
              )}

              {column.items.map((category) => {
                const hasChildren = Boolean(category.children?.length) && (category.level || column.level) < MAX_CATEGORY_DEPTH;
                const isActive = activePath.some((item) => item.value === category.value);
                const isSelected = selectedPath.some((item) => item.value === category.value);
                const pathTitle = findCategoryPath(filteredCategories, category.value)
                  .map((item) => item.label)
                  .join(' / ');
                return (
                  <button
                    className={`category-cascader-row ${isActive ? 'category-cascader-active' : ''} ${
                      isSelected ? 'category-cascader-selected' : ''
                    }`}
                    key={category.value}
                    title={pathTitle || category.label}
                    type="button"
                    onClick={() => {
                      if (hasChildren) {
                        setActiveCategoryValue(category.value);
                        return;
                      }
                      selectCategory(category.value);
                    }}
                  >
                    <span className="category-check" />
                    <span className="category-cascader-name">{category.label}</span>
                    <span className="category-cascader-count">{category.count}</span>
                    {hasChildren ? <span className="category-cascader-arrow">›</span> : <span />}
                  </button>
                );
              })}
              {column.items.length === 0 ? <div className="category-cascader-empty">暂无匹配类目</div> : null}
            </div>
          );
        })}
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
      onOpenChange={handleOpenChange}
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

function normalizeRecordTitleDisplayText(value?: string) {
  return String(value || '').trim().replace(/\s+/g, ' ');
}

function getRecordDisplayTitle(record?: LinkListRecord) {
  if (!record) return '';
  return (
    normalizeRecordTitleDisplayText(record.visualGeneratedTitleEn) ||
    normalizeRecordTitleDisplayText(record.visualGeneratedTitleCn) ||
    normalizeRecordTitleDisplayText(record.attributeTitleEn) ||
    normalizeRecordTitleDisplayText(record.productTitleEn) ||
    normalizeRecordTitleDisplayText(record.attributeTitle) ||
    normalizeRecordTitleDisplayText(record.productTitle) ||
    'Untitled product'
  );
}

function normalizeSkuDisplayText(value?: string) {
  return String(value || '').trim().replace(/\s+/g, ' ');
}

function getSkuEntryDisplayName(entry: LinkListRecord['skuEntries'][number]) {
  const visualName = normalizeSkuDisplayText(entry.visualGeneratedName);
  if (visualName) return visualName;

  const componentNames = (entry.componentSkus || [])
    .map((component) => normalizeSkuDisplayText(component.visualGeneratedName || component.name || component.specText))
    .filter(Boolean);
  if (entry.kind === 'combo' && componentNames.length > 0) return componentNames.join(' + ');
  if (componentNames.length === 1) return componentNames[0];

  const sourceSkuNames = (entry.sourceSkuLinks || [])
    .map((link) => normalizeSkuDisplayText(link.optionText || link.specText))
    .filter(Boolean);
  if (entry.kind === 'combo' && sourceSkuNames.length > 0) return sourceSkuNames.join(' + ');
  if (sourceSkuNames.length === 1) return sourceSkuNames[0];

  return normalizeSkuDisplayText(entry.name) || `SKU ${entry.order || ''}`.trim();
}

function getRecordSourceTitle(record: LinkListRecord, sourceId?: string, fallback?: string) {
  const source = sourceId ? record.sourceLinks.find((item) => item.id === sourceId) : undefined;
  return String(source?.title || fallback || '').trim();
}

function getSelectedSkuImageRefDescriptors(record: LinkListRecord, selectedSkuIds?: string[]) {
  const selectedSet = new Set(selectedSkuIds || []);
  const entries =
    selectedSet.size > 0 ? record.skuEntries.filter((entry) => selectedSet.has(entry.id)) : record.skuEntries;
  const refs: Array<{ url: string; label: string }> = [];
  const seenUrls = new Set<string>();
  const seenSubjects = new Set<string>();
  const subjectKey = (value: string | undefined) => String(value || '').trim().toLowerCase().replace(/\s+/g, '');
  const addRef = (value: string | undefined, label: string, subject?: string) => {
    const clean = String(value || '').trim();
    const key = subjectKey(subject || label);
    if (!clean || seenUrls.has(clean) || seenSubjects.has(key)) return false;
    seenUrls.add(clean);
    seenSubjects.add(key);
    refs.push({ url: clean, label });
    return true;
  };

  entries.forEach((entry) => {
    const skuName = getSkuEntryDisplayName(entry);
    const components = entry.componentSkus || [];
    const primarySourceLink = (entry.sourceSkuLinks || [])[0];
    const primaryComponent = components[0];
    const entrySourceTitle =
      getRecordSourceTitle(record, primarySourceLink?.sourceId, primarySourceLink?.sourceTitle) ||
      getRecordSourceTitle(record, primaryComponent?.sourceId, primaryComponent?.sourceTitle) ||
      record.productTitle;
    const skuLabel = `Selected SKU: ${skuName} / Product title: ${entrySourceTitle}`;

    if (entry.kind === 'combo' && components.length > 0) {
      const addedComponentRef = components.reduce((added, component) => {
        const componentName = String(component.name || component.specText || component.sourceTitle || skuName).trim();
        const sourceTitle = getRecordSourceTitle(record, component.sourceId, component.sourceTitle);
        const componentLabel = [sourceTitle, componentName].filter(Boolean).join(' / ');
        const componentSubject = [
          component.sourceId,
          component.sourceSkuKey,
          sourceTitle,
          componentName,
        ]
          .filter(Boolean)
          .join('|');
        return (
          addRef(
            component.imageUrl || component.sourceImageUrl,
            `Selected SKU component: ${componentLabel || componentName}`,
            componentSubject || componentName,
          ) || added
        );
      }, false);
      if (!addedComponentRef) {
        addRef(getSkuDisplayImageUrl(entry), skuLabel, [skuName, entrySourceTitle].filter(Boolean).join('|'));
      }
      return;
    }

    const addedEntryRef = addRef(
      getSkuDisplayImageUrl(entry),
      skuLabel,
      [entry.id, skuName, entrySourceTitle].filter(Boolean).join('|'),
    );
    if (!addedEntryRef) {
      (entry.sourceSkuLinks || []).some((link) => {
        const sourceTitle = getRecordSourceTitle(record, link.sourceId, link.sourceTitle);
        const sourceLabel = [sourceTitle, skuName].filter(Boolean).join(' / ');
        const sourceSubject = [link.sourceId, link.sourceSkuKey, sourceTitle, skuName].filter(Boolean).join('|');
        return addRef(link.imageUrl, `Selected SKU: ${sourceLabel || skuName}`, sourceSubject || skuName);
      });
    }
  });

  return refs;
}

function getSelectedSkuImageRefs(record: LinkListRecord, selectedSkuIds?: string[]) {
  return getSelectedSkuImageRefDescriptors(record, selectedSkuIds).map((item) => item.url);
}

function cleanReferenceTitle(value?: string, fallback?: string) {
  const text = String(value || '').trim();
  const cleaned = text
    .replace(/\s*(主图|素材图|效果图|场景图|细节图|尺寸结构|对比图|组合包装|卖点图)\s*\d*$/u, '')
    .trim();
  return cleaned || String(fallback || '').trim();
}

function getSelectedGalleryImageRefDescriptors(
  selectedAssets: Array<{ asset: LinkListImageAsset; imageUrl: string }>,
  record?: LinkListRecord,
) {
  const seenUrls = new Set<string>();
  return selectedAssets
    .map((item, index) => ({
      url: String(item.imageUrl || '').trim(),
      label: `Product reference image ${index + 1}: ${cleanReferenceTitle(item.asset.alt, record?.productTitle)}`,
    }))
    .filter((item) => {
      if (!item.url || seenUrls.has(item.url)) return false;
      seenUrls.add(item.url);
      return true;
    });
}

function mergeImageRefDescriptors(...groups: Array<Array<{ url: string; label: string }>>) {
  const seenUrls = new Set<string>();
  const merged: Array<{ url: string; label: string }> = [];
  groups.flat().forEach((item) => {
    const url = String(item.url || '').trim();
    if (!url || seenUrls.has(url)) return;
    seenUrls.add(url);
    merged.push({ url, label: String(item.label || `Reference image ${merged.length + 1}`).trim() });
  });
  return merged;
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
        alt: getSkuEntryDisplayName(entry),
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
  const maxProductImageCount = Math.max(CURATED_EXPORT_IMAGE_COUNT, FULL_MAIN_GALLERY_IMAGE_COUNT);
  if (Number.isFinite(count) && count > 0) {
    return Math.max(1, Math.min(maxProductImageCount, Math.floor(count)));
  }
  const carouselCount = getRecordImageSlots(record).filter((slot) => slot.type === 'carousel').length;
  return Math.max(1, Math.min(maxProductImageCount, carouselCount || CURATED_EXPORT_IMAGE_COUNT));
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

function getSelectedSkuImageBindingOptions(
  record: LinkListRecord | undefined,
  selectedSkuIds: string[],
): ImageManagerBindingImageOption[] {
  if (!record || selectedSkuIds.length === 0) return [];
  const selectedSet = new Set(selectedSkuIds);
  return record.skuEntries
    .filter((entry) => selectedSet.has(entry.id))
    .map((entry) => {
      const sourceAsset = entry.imageAsset && getAssetDisplayUrl(entry.imageAsset) ? entry.imageAsset : undefined;
      const fallbackSourceLink = (entry.sourceSkuLinks || []).find((link) => link.imageUrl);
      const fallbackComponent = (entry.componentSkus || []).find((component) => component.imageUrl || component.sourceImageUrl);
      const imageUrl =
        getAssetDisplayUrl(sourceAsset) ||
        entry.imageUrl ||
        fallbackSourceLink?.imageUrl ||
        fallbackComponent?.imageUrl ||
        fallbackComponent?.sourceImageUrl;
      if (!imageUrl) return undefined;
      const label = getSkuEntryDisplayName(entry);
      const asset: LinkListImageAsset = {
        ...(sourceAsset || {}),
        id: sourceAsset?.id || `${record.id}-sku-binding-${entry.id}`,
        role: 'sales-sku',
        sourceUrl: sourceAsset?.sourceUrl || imageUrl,
        displayUrl: sourceAsset?.displayUrl || imageUrl,
        displayCloudUrl: sourceAsset?.displayCloudUrl || sourceAsset?.editedCloudUrl || sourceAsset?.sourceCloudUrl,
        editedUrl: sourceAsset?.editedUrl,
        editedCloudUrl: sourceAsset?.editedCloudUrl,
        alt: sourceAsset?.alt || label,
      };
      return {
        asset,
        imageUrl,
        label,
        sourceLabel: 'SKU 图',
      };
    })
    .filter((item): item is ImageManagerBindingImageOption => Boolean(item));
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

function createProductCarouselSlot(record: LinkListRecord, assetId: string, order: number): LinkListImageSlot {
  const assetKey = assetId.replace(/[^a-zA-Z0-9_-]/g, '').slice(-24) || `${order}`;
  return {
    id: `${record.id}-slot-carousel-${Date.now()}-${order}-${assetKey}`,
    type: 'carousel',
    order,
    assetId,
  };
}

function syncRecordProductSlots(record: LinkListRecord, carouselSlots: LinkListImageSlot[]): LinkListRecord {
  const normalizedCarouselSlots = carouselSlots
    .filter((slot) => slot.assetId)
    .slice(0, MAX_EXPORT_CAROUSEL_IMAGE_COUNT)
    .map((slot, index) => ({
      ...slot,
      type: 'carousel' as const,
      order: index + 1,
    }));
  const firstAssetId = normalizedCarouselSlots[0]?.assetId;
  const otherSlots = getRecordImageSlots(record).filter((slot) => slot.type !== 'main' && slot.type !== 'carousel');
  const mainSlot: LinkListImageSlot = {
    id: `${record.id}-slot-main`,
    type: 'main',
    order: 0,
    assetId: firstAssetId,
  };

  return {
    ...record,
    schemaVersion: 3,
    productImageGenerationCount: normalizedCarouselSlots.length,
    imageSlots: [mainSlot, ...normalizedCarouselSlots, ...otherSlots].sort((left, right) => left.order - right.order),
  };
}

function getEditableProductImageSlotItems(record?: LinkListRecord) {
  if (!record) return [];
  const assetMap = getRecordAssetMap(record);
  return getRecordImageSlots(record)
    .filter((slot) => slot.type === 'carousel' && slot.assetId)
    .map((slot, index) => {
      const asset = slot.assetId ? assetMap.get(slot.assetId) : undefined;
      const imageUrl = getAssetDisplayUrl(asset);
      const order = index + 1;
      return {
        slot: {
          ...slot,
          order,
        },
        asset,
        imageUrl,
        order,
        imageKind: getProductImageKindByOrder(order),
        imageLabel: `图片 ${order}`,
        job: getProductSlotJob(record, getProductImageKindByOrder(order)),
      };
    })
    .filter((item) => item.imageUrl);
}

function addProductImageAssets(record: LinkListRecord, assetIds: string[]): LinkListRecord {
  const assetMap = getRecordAssetMap(record);
  const currentSlots = getRecordImageSlots(record).filter((slot) => slot.type === 'carousel' && slot.assetId);
  const existingAssetIds = new Set(currentSlots.map((slot) => slot.assetId).filter(Boolean));
  const nextSlots = [...currentSlots];

  assetIds.forEach((assetId) => {
    const asset = assetMap.get(assetId);
    if (!asset || asset.role === 'sales-sku' || existingAssetIds.has(assetId)) return;
    if (nextSlots.length >= MAX_EXPORT_CAROUSEL_IMAGE_COUNT) return;
    existingAssetIds.add(assetId);
    nextSlots.push(createProductCarouselSlot(record, assetId, nextSlots.length + 1));
  });

  return syncRecordProductSlots(record, nextSlots);
}

function removeProductImageSlot(record: LinkListRecord, slotId: string): LinkListRecord {
  const nextSlots = getRecordImageSlots(record).filter((slot) => slot.type === 'carousel' && slot.id !== slotId);
  return syncRecordProductSlots(record, nextSlots);
}

function reorderProductImageSlot(record: LinkListRecord, sourceSlotId: string, targetSlotId: string): LinkListRecord {
  if (sourceSlotId === targetSlotId) return record;
  const slots = getRecordImageSlots(record).filter((slot) => slot.type === 'carousel' && slot.assetId);
  const sourceIndex = slots.findIndex((slot) => slot.id === sourceSlotId);
  const targetIndex = slots.findIndex((slot) => slot.id === targetSlotId);
  if (sourceIndex < 0 || targetIndex < 0) return record;
  const nextSlots = [...slots];
  const [moved] = nextSlots.splice(sourceIndex, 1);
  nextSlots.splice(targetIndex, 0, moved);
  return syncRecordProductSlots(record, nextSlots);
}

function buildSkuImageAsset(record: LinkListRecord, entryId: string, asset: LinkListImageAsset, entryName: string): LinkListImageAsset {
  const displayUrl = getAssetDisplayUrl(asset);
  return {
    ...asset,
    id: `${record.id}-sku-image-${entryId}-${asset.id.replace(/[^a-zA-Z0-9_-]/g, '').slice(-24)}`,
    role: 'sales-sku',
    sourceUrl: asset.sourceUrl || displayUrl,
    displayUrl,
    displayCloudUrl: asset.displayCloudUrl || asset.editedCloudUrl || asset.sourceCloudUrl,
    editedUrl: asset.editedUrl,
    editedCloudUrl: asset.editedCloudUrl,
    alt: entryName,
  };
}

function getTargetSkuEntries(record: LinkListRecord, selectedSkuIds: string[] = []) {
  const selectedSet = new Set(selectedSkuIds);
  return selectedSet.size > 0 ? record.skuEntries.filter((entry) => selectedSet.has(entry.id)) : record.skuEntries;
}

function getSkuComponentSourceIdentity(component: LinkListRecord['skuEntries'][number]['componentSkus'][number]) {
  return normalizeSkuBindingText(component.sourceId || component.sourceUrl || component.sourceTitle);
}

function getSkuEntrySourceIdentities(entry: LinkListRecord['skuEntries'][number]) {
  const sourceKeys = (entry.componentSkus || [])
    .map(getSkuComponentSourceIdentity)
    .filter(Boolean);
  for (const link of entry.sourceSkuLinks || []) {
    const key = normalizeSkuBindingText(link.sourceId || link.sourceProductUrl || link.sourceTitle);
    if (key) sourceKeys.push(key);
  }
  return [...new Set(sourceKeys)];
}

function isComboLikeSkuEntry(entry: LinkListRecord['skuEntries'][number]) {
  return (
    entry.kind === 'combo' ||
    (entry.componentSkus || []).length > 1 ||
    splitSkuComboName(getSkuEntryDisplayName(entry)).length > 1
  );
}

function needsSkuImageBindingDialogEntry(record: LinkListRecord, entry: LinkListRecord['skuEntries'][number]) {
  if (!isComboLikeSkuEntry(entry)) return false;
  const sourceKeys = getSkuEntrySourceIdentities(entry);
  if (sourceKeys.length > 1) return true;
  const recordSourceCount = new Set(
    (record.sourceLinks || [])
      .map((source) => normalizeSkuBindingText(source.id || source.productUrl || source.title))
      .filter(Boolean),
  ).size;
  return recordSourceCount > 1;
}

function requiresSkuImageBindingDialog(record: LinkListRecord, selectedSkuIds: string[] = []) {
  return getTargetSkuEntries(record, selectedSkuIds).some((entry) => needsSkuImageBindingDialogEntry(record, entry));
}

function addSkuImageAssetsDirect(record: LinkListRecord, assetIds: string[], selectedSkuIds: string[]): LinkListRecord {
  const assetMap = getRecordAssetMap(record);
  const assets = assetIds.map((assetId) => assetMap.get(assetId)).filter((asset): asset is LinkListImageAsset => Boolean(asset));
  if (assets.length === 0) return record;
  const scopedEntries = getTargetSkuEntries(record, selectedSkuIds);
  const emptyEntries = scopedEntries.filter((entry) => !getSkuDisplayImageUrl(entry));
  const targetEntries = emptyEntries.slice(0, assets.length);
  const targetIds = new Set(targetEntries.map((entry) => entry.id));

  return {
    ...record,
    schemaVersion: 3,
    skuEntries: record.skuEntries.map((entry) => {
      if (!targetIds.has(entry.id)) return entry;
      const asset = assets[targetEntries.findIndex((target) => target.id === entry.id) % assets.length];
      const displayUrl = getAssetDisplayUrl(asset);
      return {
        ...entry,
        imageAsset: buildSkuImageAsset(record, entry.id, asset, getSkuEntryDisplayName(entry)),
        imageUrl: displayUrl || entry.imageUrl,
      };
    }),
  };
}

function normalizeSkuBindingText(value?: string) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function getSkuBindingSubjectKey(value?: string) {
  const normalized = normalizeSkuBindingText(value).toLowerCase();
  return normalized.replace(/[^a-z0-9\u4e00-\u9fff]+/g, '');
}

function getSkuComponentBindingSubjectKey(
  component: LinkListRecord['skuEntries'][number]['componentSkus'][number],
  fallback: string,
) {
  const sourcePart = normalizeSkuBindingText(component.sourceId || component.sourceUrl || component.sourceTitle);
  const skuPart = normalizeSkuBindingText(
    component.sourceSkuId || component.sourceSkuKey || component.name || component.specText || fallback,
  );
  return getSkuBindingSubjectKey([sourcePart, skuPart].filter(Boolean).join('|')) || getSkuBindingSubjectKey(fallback);
}

function getSkuEntryBindingSubjectKey(entry: LinkListRecord['skuEntries'][number], fallback: string) {
  const primaryLink = (entry.sourceSkuLinks || [])[0];
  const primaryComponent = (entry.componentSkus || [])[0];
  const sourcePart = normalizeSkuBindingText(
    primaryLink?.sourceId ||
      primaryComponent?.sourceId ||
      primaryLink?.sourceProductUrl ||
      primaryComponent?.sourceUrl ||
      primaryLink?.sourceTitle ||
      primaryComponent?.sourceTitle,
  );
  const skuPart = normalizeSkuBindingText(
    primaryLink?.sourceSkuId ||
      primaryComponent?.sourceSkuId ||
      primaryLink?.sourceSkuKey ||
      primaryComponent?.sourceSkuKey ||
      primaryLink?.optionText ||
      primaryLink?.specText ||
      primaryComponent?.name ||
      primaryComponent?.specText ||
      fallback,
  );
  return getSkuBindingSubjectKey([sourcePart, skuPart].filter(Boolean).join('|')) || getSkuBindingSubjectKey(fallback);
}

function skuBindingSubjectKeysMatch(valueKey: string, partKey: string) {
  if (!valueKey || !partKey) return false;
  return valueKey === partKey || valueKey.startsWith(partKey) || partKey.startsWith(valueKey);
}

function splitSkuComboName(value?: string) {
  const text = normalizeSkuBindingText(value);
  if (!text) return [];
  const normalized = text
    .replace(/[＋&＆]/g, '+')
    .replace(/\s+(and|with)\s+/gi, '+')
    .replace(/[，,、;；]/g, '+');
  if (!normalized.includes('+')) return [text];
  return normalized
    .split('+')
    .map((part) => normalizeSkuBindingText(part))
    .filter(Boolean);
}

function getComponentBindingName(
  component: LinkListRecord['skuEntries'][number]['componentSkus'][number] | undefined,
  fallback: string,
) {
  return normalizeSkuBindingText(component?.name || component?.specText || component?.sourceSkuKey || fallback);
}

function getSkuImageBindingTargets(record: LinkListRecord, selectedSkuIds: string[] = []): SkuImageBindingTarget[] {
  const targetEntries = getTargetSkuEntries(record, selectedSkuIds);
  const comboParts = targetEntries
    .flatMap((entry) => {
      const parts = splitSkuComboName(getSkuEntryDisplayName(entry));
      return parts.length > 1 ? parts : [];
    })
    .map((label) => ({ label, key: getSkuBindingSubjectKey(label) }))
    .filter((part) => part.key);
  const targets: SkuImageBindingTarget[] = [];

  targetEntries.forEach((entry) => {
    const skuName = normalizeSkuBindingText(getSkuEntryDisplayName(entry));
    const components = entry.componentSkus || [];
    const parsedParts = splitSkuComboName(skuName);
    const componentTargets =
      components.length > 1 || (entry.kind === 'combo' && components.length > 0)
        ? components.map((component, index) => {
            const componentName = getComponentBindingName(component, parsedParts[index] || skuName);
            return {
              componentName,
              subjectKey: getSkuComponentBindingSubjectKey(component, componentName),
            };
          })
        : parsedParts.length > 1
          ? parsedParts.map((componentName) => ({
              componentName,
              subjectKey: getSkuBindingSubjectKey(componentName),
            }))
          : [];

    if (componentTargets.length > 0) {
      componentTargets.forEach(({ componentName, subjectKey: componentSubjectKey }, index) => {
        const subjectKey = componentSubjectKey || `${entry.id}-component-${index}`;
        targets.push({
          key: `${entry.id}:component:${index}`,
          subjectKey,
          mode: 'component' as const,
          skuEntryId: entry.id,
          skuName,
          componentIndex: index,
          componentName,
        });
      });
      return;
    }

    const skuNameKey = getSkuBindingSubjectKey(skuName);
    const sourceSubjectKey = getSkuEntryBindingSubjectKey(entry, skuName);
    const matchedComboPart = comboParts.find(
      (part) => skuBindingSubjectKeysMatch(sourceSubjectKey, part.key) || skuBindingSubjectKeysMatch(skuNameKey, part.key),
    );
    const subjectKey = matchedComboPart?.key || sourceSubjectKey || skuNameKey || entry.id;
    targets.push({
      key: `${entry.id}:sku`,
      subjectKey,
      mode: 'sku' as const,
      skuEntryId: entry.id,
      skuName,
      componentName: matchedComboPart?.label || skuName,
    });
  });

  return targets;
}

function getSkuImageBindingDialogSkuIds(record: LinkListRecord, selectedSkuIds: string[] = []) {
  const targetEntries = getTargetSkuEntries(record, selectedSkuIds);
  const comboEntries = targetEntries.filter((entry) => needsSkuImageBindingDialogEntry(record, entry));
  if (comboEntries.length === 0) return [];
  const comboPartKeys = comboEntries
    .flatMap((entry) => splitSkuComboName(getSkuEntryDisplayName(entry)))
    .map(getSkuBindingSubjectKey)
    .filter(Boolean);
  const comboSourceKeys = comboEntries
    .flatMap((entry) => {
      const skuName = getSkuEntryDisplayName(entry);
      return (entry.componentSkus || []).map((component, index) =>
        getSkuComponentBindingSubjectKey(component, splitSkuComboName(skuName)[index] || skuName),
      );
    })
    .filter(Boolean);

  return targetEntries
    .filter((entry) => {
      if (needsSkuImageBindingDialogEntry(record, entry)) return true;
      const skuNameKey = getSkuBindingSubjectKey(getSkuEntryDisplayName(entry));
      const sourceKey = getSkuEntryBindingSubjectKey(entry, getSkuEntryDisplayName(entry));
      return (
        comboPartKeys.some((partKey) => skuBindingSubjectKeysMatch(skuNameKey, partKey)) ||
        comboSourceKeys.some((partKey) => skuBindingSubjectKeysMatch(sourceKey, partKey))
      );
    })
    .map((entry) => entry.id);
}

function getSkuImageBindingSubjects(record: LinkListRecord, selectedSkuIds: string[] = []): SkuImageBindingSubject[] {
  const subjects = new Map<string, SkuImageBindingSubject>();
  getSkuImageBindingTargets(record, selectedSkuIds).forEach((target) => {
    const key = `sku:${target.skuEntryId}`;
    const entry = record.skuEntries.find((item) => item.id === target.skuEntryId);
    const existing = subjects.get(key);
    if (existing) {
      existing.targets.push(target);
      return;
    }
    subjects.set(key, {
      key,
      label: entry ? getSkuEntryDisplayName(entry) : target.skuName,
      targets: [target],
    });
  });
  return Array.from(subjects.values());
}

function isSkuImageBindingSplitSubject(subject: SkuImageBindingSubject) {
  return subject.targets.length > 1 || subject.targets.some((target) => target.mode === 'component');
}

function getSkuImageBindingChoiceKeys(subject: SkuImageBindingSubject) {
  return isSkuImageBindingSplitSubject(subject) ? subject.targets.map((target) => target.key) : [subject.key];
}

function createDefaultSkuImageBindingChoices(
  subjects: SkuImageBindingSubject[],
  selectedAssets: ImageManagerBindingImageOption[],
) {
  const choices: Record<string, string | undefined> = {};
  subjects.forEach((subject, index) => {
    if (isSkuImageBindingSplitSubject(subject)) {
      subject.targets.forEach((target, targetIndex) => {
        const option = selectedAssets[targetIndex];
        if (option) {
          choices[target.key] = option.asset.id;
        }
      });
      return;
    }
    const option = selectedAssets[index];
    if (option) {
      choices[subject.key] = option.asset.id;
    }
  });

  return choices;
}

function getSkuImageBindingReferenceDescriptors(
  record: LinkListRecord,
  subjects: SkuImageBindingSubject[],
  choices: Record<string, string | undefined>,
  selectedAssets: ImageManagerBindingImageOption[],
) {
  const descriptors = selectedAssets
    .map((option, index) => {
      const url = getAssetDisplayUrl(option.asset) || option.imageUrl;
      if (!url) return undefined;
      return {
        assetId: option.asset.id,
        order: index,
        url,
        baseLabel: `图片参数 ${index + 1}: ${option.sourceLabel} / ${option.label || option.asset.alt || `图片 ${index + 1}`}`,
        bindings: [] as string[],
      };
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item));
  const descriptorByAssetId = new Map(descriptors.map((item) => [item.assetId, item]));

  subjects.forEach((subject) => {
    const splitSubject = isSkuImageBindingSplitSubject(subject);
    subject.targets.forEach((target) => {
      const assetId = choices[splitSubject ? target.key : subject.key];
      const descriptor = assetId ? descriptorByAssetId.get(assetId) : undefined;
      if (!descriptor) return;
      const skuLabel = getSkuImageBindingTargetShortLabel(record, target);
      const bindingLabel = target.mode === 'component'
        ? `${skuLabel} = ${target.componentName}`
        : `${skuLabel} = ${subject.label}`;
      descriptor.bindings.push(bindingLabel);
    });
  });

  return descriptors
    .filter((item) => item.bindings.length > 0)
    .sort((left, right) => left.order - right.order)
    .map((item) => ({
      url: item.url,
      label: `${item.baseLabel}；绑定：${Array.from(new Set(item.bindings)).join('；')}`,
    }));
}

function createComponentFromBindingTarget(
  record: LinkListRecord,
  entry: LinkListRecord['skuEntries'][number],
  target: SkuImageBindingTarget,
): LinkListRecord['skuEntries'][number]['componentSkus'][number] {
  const sourceLink = (entry.sourceSkuLinks || [])[0];
  return {
    name: target.componentName,
    specText: target.componentName,
    sourceId: sourceLink?.sourceId,
    sourceSkuId: sourceLink?.sourceSkuId,
    sourceSkuKey: sourceLink?.sourceSkuKey || target.componentName,
    sourceTitle: sourceLink?.sourceTitle || record.productTitle,
    sourceUrl: sourceLink?.sourceProductUrl || record.productSourceUrl || '',
    imageUrl: sourceLink?.imageUrl,
    sourceImageUrl: sourceLink?.imageUrl,
    rawSpecs: { sku: target.componentName },
  };
}

function applySkuImageBindingChoices(
  record: LinkListRecord,
  subjects: SkuImageBindingSubject[],
  choices: Record<string, string | undefined>,
  selectedAssets: ImageManagerBindingImageOption[] = [],
): LinkListRecord {
  const assetMap = getRecordAssetMap(record);
  selectedAssets.forEach((option) => assetMap.set(option.asset.id, option.asset));
  const targetAssetByKey = new Map<string, LinkListImageAsset>();
  const targetsByEntryId = new Map<string, SkuImageBindingTarget[]>();

  subjects.forEach((subject) => {
    const splitSubject = isSkuImageBindingSplitSubject(subject);
    subject.targets.forEach((target) => {
      const assetId = choices[splitSubject ? target.key : subject.key];
      const asset = assetId ? assetMap.get(assetId) : undefined;
      if (!asset) return;
      targetAssetByKey.set(target.key, asset);
      const entryTargets = targetsByEntryId.get(target.skuEntryId) || [];
      entryTargets.push(target);
      targetsByEntryId.set(target.skuEntryId, entryTargets);
    });
  });

  return {
    ...record,
    schemaVersion: 3,
    skuEntries: record.skuEntries.map((entry) => {
      const targets = targetsByEntryId.get(entry.id) || [];
      if (targets.length === 0) return entry;
      const isComponentBinding = entry.kind === 'combo' || targets.some((target) => target.mode === 'component');

      if (!isComponentBinding) {
        const target = targets[0];
        const asset = targetAssetByKey.get(target.key);
        const displayUrl = asset ? getAssetDisplayUrl(asset) : undefined;
        if (!asset || !displayUrl) return entry;
        return {
          ...entry,
          imageAsset: buildSkuImageAsset(record, entry.id, asset, getSkuEntryDisplayName(entry)),
          imageUrl: displayUrl,
          sourceSkuLinks: (entry.sourceSkuLinks || []).map((link) => ({ ...link, imageUrl: displayUrl })),
          componentSkus: (entry.componentSkus || []).map((component) => ({
            ...component,
            imageUrl: displayUrl,
            sourceImageUrl: displayUrl,
          })),
        };
      }

      const sourceComponents = entry.componentSkus?.length
        ? entry.componentSkus
        : targets
            .filter((target) => target.mode === 'component')
            .map((target) => createComponentFromBindingTarget(record, entry, target));
      const nextComponents = sourceComponents.map((component, index) => {
        const componentName = getComponentBindingName(component, targets[index]?.componentName || getSkuEntryDisplayName(entry));
        const target =
          targets.find((item) => item.componentIndex === index) ||
          targets.find((item) => item.subjectKey === getSkuBindingSubjectKey(componentName));
        const asset = target ? targetAssetByKey.get(target.key) : undefined;
        const displayUrl = asset ? getAssetDisplayUrl(asset) : undefined;
        if (!asset || !displayUrl) return component;
        return {
          ...component,
          name: component.name || componentName,
          specText: component.specText || componentName,
          sourceTitle: component.sourceTitle || record.productTitle,
          sourceUrl: component.sourceUrl || record.productSourceUrl || '',
          imageUrl: displayUrl,
          sourceImageUrl: displayUrl,
        };
      });
      const representativeTarget = targets.find((target) => targetAssetByKey.has(target.key));
      const representativeAsset = representativeTarget ? targetAssetByKey.get(representativeTarget.key) : undefined;
      const representativeUrl = representativeAsset ? getAssetDisplayUrl(representativeAsset) : undefined;

      return {
        ...entry,
        imageAsset: representativeAsset
          ? buildSkuImageAsset(record, entry.id, representativeAsset, getSkuEntryDisplayName(entry))
          : entry.imageAsset,
        imageUrl: representativeUrl || entry.imageUrl,
        componentSkus: nextComponents,
      };
    }),
  };
}

function getSkuImageBindingSubjectCurrentUrl(record: LinkListRecord, subject: SkuImageBindingSubject) {
  for (const target of subject.targets) {
    const entry = record.skuEntries.find((item) => item.id === target.skuEntryId);
    if (!entry) continue;
    if (target.mode === 'component') {
      const component =
        typeof target.componentIndex === 'number' ? entry.componentSkus?.[target.componentIndex] : undefined;
      const url = component?.imageUrl || component?.sourceImageUrl;
      if (url) return url;
      continue;
    }
    const url = getSkuDisplayImageUrl(entry);
    if (url) return url;
  }
  return undefined;
}

function getSkuImageBindingTargetSkuNumber(record: LinkListRecord, target: SkuImageBindingTarget) {
  const index = record.skuEntries.findIndex((entry) => entry.id === target.skuEntryId);
  return index >= 0 ? index + 1 : undefined;
}

function getSkuImageBindingTargetShortLabel(record: LinkListRecord, target: SkuImageBindingTarget) {
  const skuNumber = getSkuImageBindingTargetSkuNumber(record, target);
  const skuPrefix = skuNumber ? `SKU ${skuNumber}` : 'SKU';
  if (target.mode === 'component') {
    const componentIndex = typeof target.componentIndex === 'number' ? target.componentIndex + 1 : undefined;
    return componentIndex ? `${skuPrefix} 组件 ${componentIndex}` : `${skuPrefix} 组件`;
  }
  return skuPrefix;
}

function getSkuImageBindingSubjectTitle(
  record: LinkListRecord,
  subject: SkuImageBindingSubject,
  subjectIndex: number,
  total: number,
) {
  const skuText =
    Array.from(
      new Set(
        subject.targets
          .map((target) => getSkuImageBindingTargetSkuNumber(record, target))
          .filter((skuNumber): skuNumber is number => typeof skuNumber === 'number')
          .map((skuNumber) => `SKU ${skuNumber}`),
      ),
    ).join(' + ') || 'SKU';
  return {
    indexLabel: `绑定项 ${subjectIndex + 1}/${total}`,
    skuLabel: skuText,
    title: subject.label,
  };
}

function getSkuImageBindingTargetLabel(record: LinkListRecord, target: SkuImageBindingTarget) {
  const skuNumber = getSkuImageBindingTargetSkuNumber(record, target);
  const skuPrefix = skuNumber ? `SKU ${skuNumber}` : 'SKU';
  if (target.mode === 'component') {
    const componentIndex = typeof target.componentIndex === 'number' ? target.componentIndex + 1 : undefined;
    return `${skuPrefix} 组件 ${componentIndex || ''}：${target.componentName}`.replace(/\s+：/, '：');
  }
  return `${skuPrefix}：${target.skuName}`;
}

function removeSkuImage(record: LinkListRecord, skuEntryId: string): LinkListRecord {
  return {
    ...record,
    schemaVersion: 3,
    skuEntries: record.skuEntries.map((entry) =>
      entry.id === skuEntryId
        ? {
            ...entry,
            imageAsset: undefined,
            imageUrl: undefined,
          }
        : entry,
    ),
  };
}

function reorderSkuEntry(record: LinkListRecord, sourceSkuId: string, targetSkuId: string): LinkListRecord {
  if (sourceSkuId === targetSkuId) return record;
  const entries = [...record.skuEntries].sort((left, right) => left.order - right.order);
  const sourceIndex = entries.findIndex((entry) => entry.id === sourceSkuId);
  const targetIndex = entries.findIndex((entry) => entry.id === targetSkuId);
  if (sourceIndex < 0 || targetIndex < 0) return record;
  const [moved] = entries.splice(sourceIndex, 1);
  entries.splice(targetIndex, 0, moved);
  const orderMap = new Map(entries.map((entry, index) => [entry.id, index + 1]));
  return {
    ...record,
    schemaVersion: 3,
    skuEntries: record.skuEntries
      .map((entry) => ({
        ...entry,
        order: orderMap.get(entry.id) || entry.order,
      }))
      .sort((left, right) => left.order - right.order),
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
      title: getSkuEntryDisplayName(entry),
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
    referenceImageUrls?: string[];
    referenceImageLabels?: string[];
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
    productTitle: getRecordDisplayTitle(record),
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
    referenceImageUrls: options.referenceImageUrls,
    referenceImageLabels: options.referenceImageLabels,
    selectedSkuIds: options.selectedSkuIds,
    selectedSlotIds: options.selectedSlotIds,
    createdAt: new Date().toISOString(),
    modules: selectedModules.map((module) => ({
      id: module.id,
      order: module.order,
      slotId: module.slotId,
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

function getVisualTaskLayout(count: number): '1x1' | '2x2' | '3x3' {
  if (count <= 1) return '1x1';
  if (count <= 4) return '2x2';
  return '3x3';
}

function getVisualTaskApiMode(mode: VisualPublishMode) {
  if (mode === 'sku_adapt') return 'sku-gallery';
  if (mode === 'single_refine') return 'single-refine';
  return 'main-gallery';
}

function getVisualTaskResultUrl(module: VisualGenerationTask['modules'][number]) {
  return module.outputUrl || module.outputPath || undefined;
}

type VisualQueueMeta = {
  queueItemId?: string;
  taskId?: string;
  mode?: VisualPublishMode;
  selectedSkuIds?: string[];
  selectedSlotIds?: string[];
  referenceImageLabels?: string[];
  createdAt?: string;
};

function getVisualTaskRecordForQueue(record: LinkListRecord, item: VisualQueueItem): LinkListRecord {
  if (['main_multi', 'sku_adapt'].includes(item.mode) && item.selectedSkuIds?.length) {
    const selectedSkuIds = new Set(item.selectedSkuIds);
    const skuEntries = record.skuEntries.filter((entry) => selectedSkuIds.has(entry.id));
    return {
      ...record,
      skuEntries,
      componentSkuCount: skuEntries.reduce((total, entry) => total + Math.max(1, entry.componentSkus?.length || 1), 0),
    };
  }
  return record;
}

function getVisualTaskRecordWithQueueMeta(record: LinkListRecord, item: VisualQueueItem): LinkListRecord {
  const taskRecord = getVisualTaskRecordForQueue(record, item) as LinkListRecord & { visualQueueMeta?: VisualQueueMeta };
  return {
    ...taskRecord,
    visualQueueMeta: {
      queueItemId: item.id,
      taskId: item.taskId,
      mode: item.mode,
      selectedSkuIds: item.selectedSkuIds || [],
      selectedSlotIds: item.selectedSlotIds || [],
      referenceImageLabels: item.referenceImageLabels || [],
      createdAt: item.createdAt,
    },
  } as LinkListRecord;
}

function getVisualPublishModeFromApiMode(mode?: string): VisualPublishMode {
  if (mode === 'sku-gallery') return 'sku_adapt';
  if (mode === 'single-refine') return 'single_refine';
  return 'main_multi';
}

function getVisualQueueStatusFromBackend(task: VisualGenerationTask, completedCount: number) {
  if (task.status === 'failed') return { label: '\u6267\u884c\u5931\u8d25', color: 'red' };
  if (task.status === 'completed' || task.status === 'split') {
    return { label: completedCount > 0 ? '\u5df2\u56de\u5199' : '\u5df2\u5b8c\u6210', color: completedCount > 0 ? 'green' : 'gold' };
  }
  if (task.status === 'queued' || task.status === 'draft') return { label: '\u6392\u961f\u4e2d', color: 'blue' };
  if (task.status === 'running' || task.status === 'planned') return { label: '\u540e\u53f0\u6267\u884c\u4e2d', color: 'processing' };
  return { label: '\u5f85\u6267\u884c', color: 'blue' };
}

function createVisualQueueItemFromBackendTask(
  task: VisualGenerationTask,
  records: LinkListRecord[],
): VisualQueueItem | undefined {
  const embeddedRecord = task.record as (LinkListRecord & { visualQueueMeta?: VisualQueueMeta }) | undefined;
  if (!embeddedRecord?.visualQueueMeta) return undefined;
  const record =
    records.find((item) => item.id === task.linkRecordId || item.id === embeddedRecord?.id) ||
    (embeddedRecord?.id && embeddedRecord.productTitle ? embeddedRecord : undefined);
  if (!record) return undefined;

  const mode = embeddedRecord.visualQueueMeta.mode || getVisualPublishModeFromApiMode(task.mode);
  const visualTasks = getRecordVisualTaskPackages(record);
  const taskPackage =
    mode === 'sku_adapt'
      ? visualTasks.find((item) => item.id.includes('sku-gallery')) || visualTasks[0]
      : visualTasks.find((item) => item.id.includes('product-gallery')) || visualTasks[0];
  if (!taskPackage) return undefined;

  const referenceImageRefs = task.referenceImageRefs?.length
    ? task.referenceImageRefs
    : task.sourceImageRef
      ? [{ url: task.sourceImageRef, label: 'Reference image 1' }]
      : [];
  const selectedSkuIds = embeddedRecord.visualQueueMeta.selectedSkuIds || [];
  const selectedSlotIds = embeddedRecord.visualQueueMeta.selectedSlotIds || [];
  const referenceImageUrls = referenceImageRefs.map((item) => item.url).filter(Boolean);
  const referenceImageLabels = referenceImageRefs.map((item, index) => item.label || `Reference image ${index + 1}`);
  const requestedCount = Math.max(1, Math.min(9, task.requestedCount || task.modules.length || referenceImageUrls.length || 1));
  const baseItem = createVisualQueueItem(record, taskPackage, {
    mode,
    count: requestedCount,
    referenceImageUrl: task.sourceImageRef || referenceImageUrls[0],
    referenceImageUrls,
    referenceImageLabels,
    selectedSkuIds,
    selectedSlotIds,
  });

  const modulesByPanel = new Map(task.modules.map((module) => [module.panelIndex || 0, module]));
  const completedCount = task.modules.filter((module) => getVisualTaskResultUrl(module)).length;
  const statusMeta = getVisualQueueStatusFromBackend(task, completedCount);

  return {
    ...baseItem,
    id: embeddedRecord.visualQueueMeta.queueItemId || `queue-${task.id}`,
    backendTaskId: task.id,
    backendStatus: task.status,
    createdAt: task.createdAt || baseItem.createdAt,
    completedCount,
    statusLabel: statusMeta.label,
    statusColor: statusMeta.color,
    analysis: task.analysis,
    promptText: task.promptText || undefined,
    motherImageUrl: task.motherImageUrl || undefined,
    motherImagePath: task.motherImagePath || undefined,
    manifest: task.manifest,
    errorMessage: task.errorMessage || undefined,
    modules: baseItem.modules.map((module, index) => {
      const backendModule = modulesByPanel.get(index + 1);
      const resultUrl = backendModule ? getVisualTaskResultUrl(backendModule) : undefined;
      return {
        ...module,
        id: backendModule?.id || module.id,
        outputUrl: backendModule?.outputUrl || undefined,
        outputPath: backendModule?.outputPath || undefined,
        imageUrl: resultUrl || module.imageUrl,
        statusLabel: resultUrl ? '\u5df2\u56de\u5199' : statusMeta.label,
        statusColor: resultUrl ? 'green' : statusMeta.color,
      };
    }),
  };
}

function isRemoteImageUrl(url?: string) {
  return Boolean(url && /^https?:\/\//i.test(url));
}

function getVisualQueueProgress(item: VisualQueueItem) {
  if (item.completedCount > 0) {
    const total = Math.max(1, item.moduleCount || item.requestedCount || item.completedCount);
    return Math.min(100, Math.max(80, Math.round(78 + (item.completedCount / total) * 22)));
  }
  if (item.motherImageUrl || item.motherImagePath) return 78;
  if (item.promptText) return 58;
  if (hasVisualDetail(item.analysis)) return 42;
  if (item.backendTaskId) return 24;
  return 8;
}

function isVisualQueueItemCompleted(item: VisualQueueItem) {
  return item.statusLabel === '已回写' || item.completedCount >= Math.max(1, item.moduleCount || item.requestedCount || 1);
}

function isVisualQueueItemActive(item: VisualQueueItem) {
  const backendStatus = String(item.backendStatus || '').toLowerCase();
  return item.statusColor !== 'red' && ACTIVE_VISUAL_BACKEND_STATUSES.has(backendStatus);
}

function isVisualQueueItemRunnable(item: VisualQueueItem) {
  return !isVisualQueueItemCompleted(item) && !isVisualQueueItemActive(item);
}

function getVisualQueueLayoutLabel(count: number) {
  return getVisualTaskLayout(count);
}

function getVisualMotherImageUrl(item?: VisualQueueItem) {
  if (!item) return undefined;
  return item.motherImageUrl || (isRemoteImageUrl(item.motherImagePath) ? item.motherImagePath : undefined);
}

function getVisualReferenceImageRefs(item: VisualQueueItem) {
  const urls = item.referenceImageUrls?.length
    ? item.referenceImageUrls
    : item.referenceImageUrl
      ? [item.referenceImageUrl]
      : [];
  const labels = item.referenceImageLabels || [];
  const seen = new Set<string>();
  return urls
    .map((url, index) => ({
      url: String(url || '').trim(),
      label: String(labels[index] || `Reference image ${index + 1}`).trim(),
      role: 'product-reference-image',
    }))
    .filter((ref) => {
      if (!ref.url || seen.has(ref.url)) return false;
      seen.add(ref.url);
      return true;
    });
}

function getVisualInputPromptText(item: VisualQueueItem) {
  const fallbackReferenceCount =
    item.referenceImageUrls?.length || (item.referenceImageUrl ? 1 : 0);
  const referenceLines = item.referenceImageLabels?.length
    ? item.referenceImageLabels
        .filter(Boolean)
        .map((label, index) => `Image ${index + 1}: ${label}`)
        .join('\n')
    : Array.from({ length: fallbackReferenceCount }, (_, index) => `Image ${index + 1}: selected reference image`).join(
        '\n',
      );
  return [
    `Mode: ${item.modeLabel}`,
    `Product title: ${item.productTitle}`,
    'Reference image parameters:',
    referenceLines || 'No reference image selected.',
    `Requested count: ${item.requestedCount}`,
    `Layout: ${getVisualQueueLayoutLabel(item.requestedCount)}`,
    `Style profile: ${item.styleProfileId}`,
    `Batch strategy: ${item.mixPolicy}`,
    '',
    'Goal: analyze the selected image parameters and product record first, then create a unified visual plan before generating the mother grid image.',
  ].join('\n');
}

function hasVisualDetail(value?: Record<string, unknown> | string | null) {
  if (!value) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  return Object.keys(value).length > 0;
}

function formatVisualDetail(value?: Record<string, unknown> | string) {
  if (!hasVisualDetail(value)) return '等待图片分析完成后展示。';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

function asVisualRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function asVisualArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function visualText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.map(visualText).filter(Boolean).join('、');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value).trim();
}

function visualTextByKeys(source: Record<string, unknown> | undefined, keys: string[]): string {
  if (!source) return '';
  for (const key of keys) {
    const text = visualText(source[key]);
    if (text) return text;
  }
  return '';
}

function visualListTexts(value: unknown, maxItems = 8): string[] {
  if (Array.isArray(value)) {
    return value.map(visualText).filter(Boolean).slice(0, maxItems);
  }
  const text = visualText(value);
  return text ? [text] : [];
}

function getVisualProductUnderstanding(analysis?: Record<string, unknown>) {
  if (!analysis) return undefined;
  return (
    asVisualRecord(analysis.productUnderstanding) ||
    asVisualRecord(analysis.productAnalysis) ||
    analysis
  );
}

function renderVisualTagList(items: string[]) {
  if (items.length === 0) return <Text type="secondary">暂无</Text>;
  return (
    <Space size={[4, 4]} wrap>
      {items.map((item) => (
        <Tag key={item}>{item}</Tag>
      ))}
    </Space>
  );
}

function renderVisualAnalysisResult(analysis: Record<string, unknown> | undefined, fallbackText: string) {
  if (!hasVisualDetail(analysis)) return <pre>{fallbackText}</pre>;

  const understanding = getVisualProductUnderstanding(analysis);
  const identity = asVisualRecord(understanding?.productIdentity);
  const titleCn = visualTextByKeys(identity, ['title_cn', 'titleCn']);
  const titleEn = visualTextByKeys(identity, ['title_en', 'titleEn']);
  const productType = visualTextByKeys(identity, ['product_type_cn', 'product_type', 'productType']);
  const category = visualTextByKeys(understanding, ['overallCategory', 'category', 'productName', 'mainObject']);
  const skuRows = asVisualArray(identity?.skus)
    .map(asVisualRecord)
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .slice(0, 8);
  const referenceRows = asVisualArray(understanding?.referenceAnalyses)
    .map(asVisualRecord)
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .slice(0, 8);
  const preserveItems = visualListTexts(
    understanding?.globalMustPreserve || understanding?.mustPreserve || identity?.mustPreserve,
    10,
  );
  const doNotChangeItems = visualListTexts(
    understanding?.globalDoNotChange || understanding?.doNotChange || identity?.doNotChange,
    10,
  );

  return (
    <>
      <div className="visual-workflow-fact-grid visual-analysis-fact-grid">
        <div>
          <span>中文标题</span>
          <strong title={titleCn || undefined}>{titleCn || '未返回'}</strong>
        </div>
        <div>
          <span>英文标题</span>
          <strong title={titleEn || undefined}>{titleEn || '未返回'}</strong>
        </div>
        <div>
          <span>商品类型</span>
          <strong title={productType || undefined}>{productType || category || '未返回'}</strong>
        </div>
        <div>
          <span>参考图数量</span>
          <strong>{referenceRows.length || '未返回'}</strong>
        </div>
      </div>

      {skuRows.length > 0 ? (
        <div className="visual-analysis-section">
          <Text strong>SKU 标准化与绑定</Text>
          <div className="visual-analysis-list">
            {skuRows.map((sku, index) => {
              const components = asVisualArray(sku.components).map(asVisualRecord).filter(Boolean);
              const componentText = components
                .map((component) =>
                  [
                    visualTextByKeys(component, ['standard_name', 'standardName', 'product_name', 'productName']),
                    visualTextByKeys(component, ['quantity']),
                    visualTextByKeys(component, ['reference_image_index', 'referenceImageIndex']),
                  ]
                    .filter(Boolean)
                    .join(' / '),
                )
                .filter(Boolean)
                .join(' + ');
              return (
                <div className="visual-analysis-row" key={`${visualText(sku.sku_index) || index}-${visualText(sku.raw_name)}`}>
                  <span>{visualText(sku.raw_name) || `SKU ${index + 1}`}</span>
                  <strong>{visualTextByKeys(sku, ['standard_name', 'standardName', 'product_name', 'productName']) || '未标准化'}</strong>
                  {componentText ? <small>{componentText}</small> : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {referenceRows.length > 0 ? (
        <div className="visual-analysis-section">
          <Text strong>参考图识别结果</Text>
          <div className="visual-analysis-list">
            {referenceRows.map((reference, index) => (
              <div className="visual-analysis-row" key={`${visualText(reference.index) || index}-${visualText(reference.label)}`}>
                <span>图 {visualText(reference.index) || index + 1}</span>
                <strong>{visualTextByKeys(reference, ['visualIdentity', 'subject', 'category', 'shape']) || '未返回主体'}</strong>
                <small>
                  {[
                    visualTextByKeys(reference, ['geometry', 'shape', 'silhouette']),
                    visualText(reference.colors),
                    visualText(reference.materials),
                    visualTextByKeys(reference, ['quantity', 'printedPattern']),
                  ]
                    .filter(Boolean)
                    .join('；') || '暂无细节'}
                </small>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="visual-analysis-section visual-analysis-guardrails">
        <div>
          <Text strong>必须保留</Text>
          {renderVisualTagList(preserveItems)}
        </div>
        <div>
          <Text strong>禁止变化</Text>
          {renderVisualTagList(doNotChangeItems)}
        </div>
      </div>

      <details className="visual-analysis-raw">
        <summary>查看阶段一原始返回 JSON</summary>
        <pre>{formatVisualDetail(analysis)}</pre>
      </details>
    </>
  );
}

function getVisualWorkflowStates(item: VisualQueueItem) {
  const completed = [
    hasVisualDetail(item.analysis),
    Boolean(item.promptText),
    item.completedCount > 0,
  ];
  const firstPendingIndex = completed.findIndex((done) => !done);
  const activeIndex = firstPendingIndex >= 0 ? firstPendingIndex : completed.length - 1;
  return completed.map((done, index) => {
    if (item.statusColor === 'red' && index === Math.max(0, activeIndex)) return 'error';
    if (done) return 'done';
    if (index === activeIndex) return 'active';
    return 'waiting';
  });
}

function replaceAssetById(assets: LinkListImageAsset[], nextAsset: LinkListImageAsset) {
  const index = assets.findIndex((asset) => asset.id === nextAsset.id);
  if (index < 0) return [...assets, nextAsset];
  const nextAssets = [...assets];
  nextAssets[index] = nextAsset;
  return nextAssets;
}

function createVisualResultAsset(
  record: LinkListRecord,
  item: VisualQueueItem,
  module: VisualGenerationTask['modules'][number],
  order: number,
  role: LinkListImageAsset['role'],
): LinkListImageAsset {
  const resultUrl = getVisualTaskResultUrl(module);
  const isRemote = isRemoteImageUrl(resultUrl);
  const baseId =
    role === 'sales-sku'
      ? `${record.id}-visual-sku-${item.backendTaskId || item.id}-${module.targetSkuEntryId || order}`
      : role === 'product-main'
        ? `${record.id}-visual-main-${item.backendTaskId || item.id}`
        : `${record.id}-visual-product-${item.backendTaskId || item.id}-${order}`;

  return {
    id: baseId,
    role,
    sourceUrl: module.outputPath || undefined,
    displayUrl: resultUrl,
    displayCloudUrl: isRemote ? resultUrl : undefined,
    editedUrl: resultUrl,
    editedCloudUrl: isRemote ? resultUrl : undefined,
    alt: module.title || module.purpose || `${record.productTitle} ${order}`,
  };
}

function applyVisualGenerationResult(record: LinkListRecord, item: VisualQueueItem, task: VisualGenerationTask) {
  const generatedModules = [...(task.modules || [])]
    .filter((module) => getVisualTaskResultUrl(module))
    .sort((left, right) => (left.panelIndex || 0) - (right.panelIndex || 0));

  if (generatedModules.length === 0) return record;

  if (item.mode === 'sku_adapt') {
    const moduleBySkuId = new Map<string, VisualGenerationTask['modules'][number]>();
    generatedModules.forEach((module, index) => {
      const queueModule = item.modules[index];
      const skuId = module.targetSkuEntryId || queueModule?.skuEntryId;
      if (skuId) moduleBySkuId.set(skuId, module);
    });

    const nextSkuEntries = record.skuEntries.map((entry) => {
      const module = moduleBySkuId.get(entry.id);
      if (!module) return entry;
      const resultUrl = getVisualTaskResultUrl(module);
      const asset = createVisualResultAsset(record, item, module, entry.order, 'sales-sku');
      return {
        ...entry,
        imageAsset: {
          ...(entry.imageAsset || {}),
          ...asset,
          sourceUrl: entry.imageAsset?.sourceUrl || entry.imageUrl,
        },
        imageUrl: resultUrl || entry.imageUrl,
      };
    });

    return {
      ...record,
      schemaVersion: 3 as const,
      skuEntries: nextSkuEntries,
    };
  }

  let nextMainImage = record.mainImage;
  let nextProductImages = [...(record.productMaterialImages || [])];
  const slotMap = new Map<string, LinkListImageSlot>();
  getRecordImageSlots(record).forEach((slot) => {
    slotMap.set(slot.id, { ...slot });
  });

  generatedModules.forEach((module, index) => {
    const queueModule =
      item.modules[index] || item.modules.find((candidate) => candidate.order === module.panelIndex) || item.modules[0];
    const order = queueModule?.order || module.panelIndex || index + 1;
    const targetSlotId = module.targetSlotId || queueModule?.slotId || `${record.id}-slot-carousel-${order}`;
    const existingSlot = slotMap.get(targetSlotId);
    const shouldReplaceMain =
      order === 1 || existingSlot?.type === 'main' || targetSlotId === `${record.id}-slot-main`;
    const asset = createVisualResultAsset(
      record,
      item,
      module,
      order,
      shouldReplaceMain ? 'product-main' : 'product-material',
    );

    if (shouldReplaceMain) {
      nextMainImage = {
        ...(record.mainImage || {}),
        ...asset,
        id: record.mainImage?.id || asset.id,
        role: 'product-main',
      };
    } else {
      nextProductImages = replaceAssetById(nextProductImages, asset);
    }

    const slotAssetId = shouldReplaceMain ? nextMainImage?.id || asset.id : asset.id;
    const nextSlot: LinkListImageSlot = {
      ...(existingSlot || {}),
      id: targetSlotId,
      type: existingSlot?.type || 'carousel',
      order: Number.isFinite(existingSlot?.order) ? Number(existingSlot?.order) : order,
      assetId: slotAssetId,
    };
    slotMap.set(targetSlotId, nextSlot);

    if (shouldReplaceMain) {
      const mainSlotId = `${record.id}-slot-main`;
      const mainSlot = slotMap.get(mainSlotId);
      slotMap.set(mainSlotId, {
        ...(mainSlot || {}),
        id: mainSlotId,
        type: 'main',
        order: 0,
        assetId: slotAssetId,
      });

      const carouselOneId = `${record.id}-slot-carousel-1`;
      const carouselOne = slotMap.get(carouselOneId);
      slotMap.set(carouselOneId, {
        ...(carouselOne || {}),
        id: carouselOneId,
        type: 'carousel',
        order: 1,
        assetId: slotAssetId,
      });
    }
  });

  return {
    ...record,
    schemaVersion: 3 as const,
    mainImage: nextMainImage,
    productMaterialImages: nextProductImages,
    productImageGenerationCount: Math.max(record.productImageGenerationCount || 0, generatedModules.length),
    imageSlots: [...slotMap.values()].sort((left, right) => left.order - right.order),
  };
}

function waitForMs(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function waitForVisualGenerationTask(
  taskId: string,
  maxAttempts = 180,
  onProgress?: (task: VisualGenerationTask) => void,
): Promise<VisualGenerationTask> {
  let lastTask: VisualGenerationTask | undefined;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const task = await fetchVisualGenerationTask(taskId);
    lastTask = task;
    onProgress?.(task);
    if (task.status === 'completed' || task.status === 'split') return task;
    if (task.status === 'failed') {
      throw new Error(task.errorMessage || '生图任务执行失败');
    }
    await waitForMs(3000);
  }
  throw new Error(lastTask?.errorMessage || '生图任务仍在执行，请稍后打开任务队列查看');
}

function getDianxiaomiExportTaskStatusMeta(task: DianxiaomiExportTask) {
  const taskProgress = Number(task.progressPercent);
  const progress = Number.isFinite(taskProgress) ? Math.max(0, Math.min(100, Math.round(taskProgress))) : undefined;
  if (task.status === 'completed') {
    return { label: '已完成', color: 'green', progress: 100, progressStatus: 'success' as const };
  }
  if (task.status === 'failed') {
    return { label: '执行失败', color: 'red', progress: 100, progressStatus: 'exception' as const };
  }
  if (task.status === 'cancelled') {
    return { label: '已停止', color: 'default', progress: 100, progressStatus: 'normal' as const };
  }
  if (task.status === 'running') {
    return { label: '执行中', color: 'processing', progress: progress ?? 58, progressStatus: 'active' as const };
  }
  return { label: '排队中', color: 'blue', progress: progress ?? 18, progressStatus: 'active' as const };
}

function sortDianxiaomiExportTasks(tasks: DianxiaomiExportTask[]) {
  return [...tasks].sort((left, right) => {
    const leftTime = new Date(left.createdAt || left.updatedAt || 0).getTime();
    const rightTime = new Date(right.createdAt || right.updatedAt || 0).getTime();
    return rightTime - leftTime;
  });
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
  onDeleteMany,
  onExportRecords,
  onUpdate,
  exporting,
}: {
  records: LinkListRecord[];
  onDelete: (recordId: string) => void;
  onDeleteMany?: (recordIds: string[]) => void;
  onExportRecords?: (records: LinkListRecord[]) => Promise<DianxiaomiExportTask | void>;
  onUpdate: (record: LinkListRecord) => void;
  exporting?: boolean;
}) {
  const [selectedRecordIds, setSelectedRecordIds] = useState<string[]>([]);
  const [previewRecord, setPreviewRecord] = useState<LinkListRecord>();
  const [previewActiveImageSlotId, setPreviewActiveImageSlotId] = useState<string>();
  const [previewActiveSkuEntryId, setPreviewActiveSkuEntryId] = useState<string>();
  const [imageManagerRecord, setImageManagerRecord] = useState<LinkListRecord>();
  const [imageEditorOpen, setImageEditorOpen] = useState(false);
  const [managerActiveSlotId, setManagerActiveSlotId] = useState<string>();
  const [imageManagerPreviewFocus, setImageManagerPreviewFocus] = useState<'gallery' | 'sku'>('gallery');
  const [imageManagerActiveSkuEntryId, setImageManagerActiveSkuEntryId] = useState<string>();
  const [imageManagerSelectedAssetIds, setImageManagerSelectedAssetIds] = useState<string[]>([]);
  const [imageManagerSelectedSlotIds, setImageManagerSelectedSlotIds] = useState<string[]>([]);
  const [imageManagerSelectedSkuIds, setImageManagerSelectedSkuIds] = useState<string[]>([]);
  const [skuImageBindingOpen, setSkuImageBindingOpen] = useState(false);
  const [skuImageBindingChoices, setSkuImageBindingChoices] = useState<Record<string, string | undefined>>({});
  const [skuImageBindingTargetSkuIds, setSkuImageBindingTargetSkuIds] = useState<string[]>([]);
  const [skuImageBindingPendingMainGalleryCount, setSkuImageBindingPendingMainGalleryCount] = useState<number | null>(null);
  const [skuImageBindingPendingMainGallerySkuIds, setSkuImageBindingPendingMainGallerySkuIds] = useState<string[] | undefined>();
  const [draggingProductSlotId, setDraggingProductSlotId] = useState<string>();
  const [draggingSkuEntryId, setDraggingSkuEntryId] = useState<string>();
  const [imageSlotPickerOpen, setImageSlotPickerOpen] = useState(false);
  const [syncingRecordId, setSyncingRecordId] = useState<string>();
  const [syncingAll, setSyncingAll] = useState(false);
  const [regeneratingSlotKey, setRegeneratingSlotKey] = useState<string>();
  const [visualQueueOpen, setVisualQueueOpen] = useState(false);
  const [visualQueueItems, setVisualQueueItems] = useState<VisualQueueItem[]>([]);
  const [visualQueueExecuting, setVisualQueueExecuting] = useState(false);
  const [visualQueueSummary, setVisualQueueSummary] = useState<VisualQueueSummary>();
  const [activeVisualQueueItemId, setActiveVisualQueueItemId] = useState<string>();
  const [expandedVisualQueueItemIds, setExpandedVisualQueueItemIds] = useState<string[]>([]);
  const [visualWorkflowStageByItemId, setVisualWorkflowStageByItemId] = useState<Record<string, number>>({});
  const [exportQueueTasks, setExportQueueTasks] = useState<DianxiaomiExportTask[]>([]);
  const [visualQueueFilter, setVisualQueueFilter] = useState<QueueTaskFilter>('all');
  const exportQueuePendingCount = useMemo(
    () => exportQueueTasks.filter((task) => task.status === 'queued' || task.status === 'running').length,
    [exportQueueTasks],
  );
  const totalQueueTaskCount = visualQueueItems.length + exportQueueTasks.length;
  const visibleVisualQueueItems = visualQueueFilter === 'excel' ? [] : visualQueueItems;
  const visibleExportQueueTasks = visualQueueFilter === 'visual' ? [] : exportQueueTasks;
  const visibleQueueTaskCount = visibleVisualQueueItems.length + visibleExportQueueTasks.length;
  const previewGalleryItems = useMemo(() => getRecordPreviewGalleryItems(previewRecord), [previewRecord]);
  const previewImageAssetOptions = useMemo(() => getImageAssetOptions(previewRecord), [previewRecord]);
  const imageManagerSlotItems = useMemo(
    () => (imageManagerRecord ? getRecordProductImageSlotItems(imageManagerRecord) : []),
    [imageManagerRecord],
  );
  const imageEditorProductSlotItems = useMemo(
    () => (imageManagerRecord ? getEditableProductImageSlotItems(imageManagerRecord) : []),
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
  const imageManagerSelectedAssets = useMemo(() => {
    const selectedSet = new Set(imageManagerSelectedAssetIds);
    return imageManagerGalleryOptions.filter((option) => selectedSet.has(option.asset.id));
  }, [imageManagerGalleryOptions, imageManagerSelectedAssetIds]);
  const skuImageBindingCandidateImages = useMemo(() => {
    const seenUrls = new Set<string>();
    return imageManagerSelectedAssets
      .map((option, index): ImageManagerBindingImageOption => ({
        ...option,
        label: option.asset.alt || `图库图片 ${index + 1}`,
        sourceLabel: '图库',
      }))
      .filter((option) => {
      const url = String(option.imageUrl || '').trim();
      if (!url || seenUrls.has(url)) return false;
      seenUrls.add(url);
      return true;
    });
  }, [imageManagerSelectedAssets]);
  const skuImageBindingSubjects = useMemo(
    () => (imageManagerRecord ? getSkuImageBindingSubjects(imageManagerRecord, skuImageBindingTargetSkuIds) : []),
    [imageManagerRecord, skuImageBindingTargetSkuIds],
  );
  const imageManagerSelectedGalleryImageRefs = useMemo(
    () => getSelectedGalleryImageRefDescriptors(imageManagerSelectedAssets, imageManagerRecord),
    [imageManagerRecord, imageManagerSelectedAssets],
  );
  const canEnqueueMainGalleryFromImageManager =
    Boolean(imageManagerProductTask) &&
    imageManagerSelectedGalleryImageRefs.length > 0;
  const activeVisualQueueItem = useMemo(
    () => visualQueueItems.find((item) => item.id === activeVisualQueueItemId) || visualQueueItems[0],
    [activeVisualQueueItemId, visualQueueItems],
  );
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
  const imageManagerPreviewActiveSlot = imageManagerActiveGalleryItem?.slot;
  const imageManagerActiveGallerySlotItem = imageManagerActiveGalleryItem
    ? {
        slot: imageManagerActiveGalleryItem.slot,
        asset: imageManagerActiveGalleryItem.asset,
        imageUrl: imageManagerActiveGalleryItem.imageUrl,
        order: imageManagerActiveGalleryItem.slot.type === 'main' ? 1 : imageManagerActiveGalleryItem.slot.order,
        imageKind: getProductImageKindForSlot(imageManagerActiveGalleryItem.slot),
        imageLabel: getImageSlotLabel(imageManagerActiveGalleryItem.slot),
        job: imageManagerRecord
          ? getProductSlotJob(imageManagerRecord, getProductImageKindForSlot(imageManagerActiveGalleryItem.slot))
          : undefined,
      }
    : undefined;
  const managerActiveSlotItem =
    imageManagerSlotItems.find((item) => item.slot.id === managerActiveSlotId) ||
    imageManagerActiveGallerySlotItem ||
    imageManagerSlotItems[0];
  const managerActiveSlot = managerActiveSlotItem?.slot;
  const activeSlotPickerRecord = previewRecord;
  const activeSlotPickerSlot = previewActiveSlot;
  const activeSlotPickerOptions = previewImageAssetOptions;
  const activePreviewSkuEntry =
    previewRecord?.skuEntries.find((entry) => entry.id === previewActiveSkuEntryId) || previewRecord?.skuEntries[0];
  const previewDisplayTitle = getRecordDisplayTitle(previewRecord);
  const previewPriceText = formatPreviewPrice(previewRecord);
  const imageManagerActiveSkuEntry =
    imageManagerRecord?.skuEntries.find((entry) => entry.id === imageManagerActiveSkuEntryId) ||
    imageManagerRecord?.skuEntries[0];
  const imageManagerActiveSkuImageUrl = imageManagerActiveSkuEntry
    ? getSkuDisplayImageUrl(imageManagerActiveSkuEntry)
    : undefined;
  const imageManagerDisplayedImageUrl =
    imageManagerPreviewFocus === 'sku' && imageManagerActiveSkuImageUrl
      ? imageManagerActiveSkuImageUrl
      : imageManagerActiveGalleryItem?.imageUrl || getRecordMainImageUrl(imageManagerRecord);
  const imageManagerDisplayedImageAlt =
    imageManagerPreviewFocus === 'sku' && imageManagerActiveSkuImageUrl && imageManagerActiveSkuEntry
      ? getSkuEntryDisplayName(imageManagerActiveSkuEntry)
      : getRecordDisplayTitle(imageManagerRecord);
  const imageManagerDisplayTitle = getRecordDisplayTitle(imageManagerRecord);
  const imageManagerPriceText = formatPreviewPrice(imageManagerRecord);
  const imageManagerProgress = imageManagerRecord ? getRecordProductImageProgress(imageManagerRecord) : undefined;
  const hasPendingCreativeJobs = records.some((record) =>
    (record.creativeJobs || []).some((job) => job.status === 'queued' || job.status === 'running'),
  );
  const selectedRecords = useMemo(
    () => records.filter((record) => selectedRecordIds.includes(record.id)),
    [records, selectedRecordIds],
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
    const availableIds = new Set(records.map((record) => record.id));
    setSelectedRecordIds((current) => current.filter((id) => availableIds.has(id)));
  }, [records]);

  useEffect(() => {
    if (!imageManagerRecord) {
      setImageEditorOpen(false);
      setManagerActiveSlotId(undefined);
      setImageManagerPreviewFocus('gallery');
      setImageManagerActiveSkuEntryId(undefined);
      setImageManagerSelectedAssetIds([]);
      setImageManagerSelectedSlotIds([]);
      setImageManagerSelectedSkuIds([]);
      setSkuImageBindingOpen(false);
      setSkuImageBindingChoices({});
      setSkuImageBindingTargetSkuIds([]);
      setSkuImageBindingPendingMainGalleryCount(null);
      setSkuImageBindingPendingMainGallerySkuIds(undefined);
      setDraggingProductSlotId(undefined);
      setDraggingSkuEntryId(undefined);
      return;
    }

    const slotItems = getRecordProductImageSlotItems(imageManagerRecord);
    const galleryItems = getRecordPreviewGalleryItems(imageManagerRecord);
    const activeSlotExists =
      slotItems.some((item) => item.slot.id === managerActiveSlotId) ||
      galleryItems.some((item) => item.slot.id === managerActiveSlotId);
    if (!activeSlotExists) {
      setManagerActiveSlotId(galleryItems[0]?.slot.id || slotItems[0]?.slot.id);
    }
    if (!imageManagerRecord.skuEntries.some((entry) => entry.id === imageManagerActiveSkuEntryId)) {
      setImageManagerActiveSkuEntryId(imageManagerRecord.skuEntries[0]?.id);
    }
  }, [imageManagerRecord, managerActiveSlotId, imageManagerActiveSkuEntryId]);

  useEffect(() => {
    setImageManagerPreviewFocus('gallery');
    setImageManagerSelectedAssetIds([]);
    setImageManagerSelectedSlotIds([]);
    setImageManagerSelectedSkuIds([]);
    setSkuImageBindingOpen(false);
    setSkuImageBindingChoices({});
    setSkuImageBindingTargetSkuIds([]);
    setSkuImageBindingPendingMainGalleryCount(null);
    setSkuImageBindingPendingMainGallerySkuIds(undefined);
    setDraggingProductSlotId(undefined);
    setDraggingSkuEntryId(undefined);
  }, [imageManagerRecord?.id]);

  useEffect(() => {
    if (visualQueueItems.length === 0) {
      setActiveVisualQueueItemId(undefined);
      setExpandedVisualQueueItemIds([]);
      return;
    }
    if (!activeVisualQueueItemId || !visualQueueItems.some((item) => item.id === activeVisualQueueItemId)) {
      setActiveVisualQueueItemId(visualQueueItems[0].id);
    }
  }, [activeVisualQueueItemId, visualQueueItems]);

  const refreshVisualQueueTasks = useCallback(async () => {
    if (records.length === 0) return;
    const tasks = await fetchVisualGenerationTasks();
    const restoredItems = tasks
      .map((task) => createVisualQueueItemFromBackendTask(task, records))
      .filter((item): item is VisualQueueItem => Boolean(item));

    setVisualQueueItems((current) => {
      const restoredIds = new Set(restoredItems.map((item) => item.id));
      const restoredBackendIds = new Set(restoredItems.map((item) => item.backendTaskId).filter((id): id is string => Boolean(id)));
      const localOnlyItems = current.filter(
        (item) => !restoredIds.has(item.id) && (!item.backendTaskId || !restoredBackendIds.has(item.backendTaskId)),
      );
      return [...restoredItems, ...localOnlyItems].sort(
        (left, right) => new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime(),
      );
    });
  }, [records]);

  const refreshVisualQueueSummary = useCallback(async () => {
    const summary = await fetchVisualQueueSummary();
    setVisualQueueSummary(summary);
  }, []);

  const refreshExportQueueTasks = useCallback(async () => {
    const tasks = await fetchDianxiaomiExportTasks();
    setExportQueueTasks(sortDianxiaomiExportTasks(tasks));
  }, []);

  const openUnifiedQueue = useCallback(() => {
    setVisualQueueOpen(true);
    void refreshVisualQueueTasks();
    void refreshExportQueueTasks();
  }, [refreshExportQueueTasks, refreshVisualQueueTasks]);

  const downloadExportQueueTask = useCallback(async (task: DianxiaomiExportTask) => {
    try {
      const blob = await downloadDianxiaomiExportTask(task.id);
      downloadBlob(blob, task.filename || `dianxiaomi_temu_export_${task.id}.xlsx`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Excel 下载失败');
    }
  }, []);

  useEffect(() => {
    void refreshVisualQueueTasks().catch((error) => {
      console.warn('Failed to restore visual queue tasks', error);
    });
  }, [refreshVisualQueueTasks]);

  useEffect(() => {
    void refreshExportQueueTasks().catch((error) => {
      console.warn('Failed to restore export queue tasks', error);
    });
  }, [refreshExportQueueTasks]);

  useEffect(() => {
    if (!visualQueueOpen) return;
    void refreshVisualQueueSummary().catch((error) => {
      console.warn('Failed to refresh visual queue summary', error);
    });
  }, [visualQueueOpen, visualQueueItems.length, refreshVisualQueueSummary]);

  useEffect(() => {
    if (!visualQueueOpen) return undefined;
    const refresh = () => {
      void refreshExportQueueTasks().catch((error) => {
        console.warn('Failed to refresh export queue tasks', error);
      });
    };
    refresh();
    const timer = window.setInterval(refresh, exportQueuePendingCount > 0 ? 3000 : 8000);
    return () => window.clearInterval(timer);
  }, [exportQueuePendingCount, refreshExportQueueTasks, visualQueueOpen]);

  const cancelExportQueueTask = useCallback(async (task: DianxiaomiExportTask) => {
    try {
      const nextTask = await cancelDianxiaomiExportTask(task.id);
      setExportQueueTasks((current) =>
        sortDianxiaomiExportTasks(current.map((item) => (item.id === nextTask.id ? nextTask : item))),
      );
      message.success('Excel 导出任务已停止');
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Excel 任务停止失败');
    }
  }, []);

  const removeExportQueueTask = useCallback(async (task: DianxiaomiExportTask) => {
    try {
      await deleteDianxiaomiExportTask(task.id);
      setExportQueueTasks((current) => current.filter((item) => item.id !== task.id));
      message.success('Excel 导出任务已删除');
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Excel 任务删除失败');
    }
  }, []);

  const toggleLinkRecordSelection = (recordId: string, checked: boolean) => {
    setSelectedRecordIds((current) =>
      checked ? [...new Set([...current, recordId])] : current.filter((id) => id !== recordId),
    );
  };

  const exportSelectedRecords = async () => {
    if (selectedRecords.length === 0) {
      message.warning('请先选择要导出的商品链接');
      return;
    }
    if (!onExportRecords) return;
    const exportedIdSet = new Set(selectedRecords.map((record) => record.id));
    setSelectedRecordIds((current) => current.filter((id) => !exportedIdSet.has(id)));
    const task = await onExportRecords(selectedRecords);
    if (task) {
      setExportQueueTasks((current) =>
        sortDianxiaomiExportTasks([task, ...current.filter((item) => item.id !== task.id)]),
      );
      setVisualQueueOpen(true);
      message.success(`导出任务已加入队列：${task.recordCount} 个商品链接`);
    }
  };

  const deleteSelectedRecords = () => {
    if (selectedRecords.length === 0) {
      message.warning('请先选择要删除的商品链接');
      return;
    }
    const deletingIds = selectedRecords.map((record) => record.id);
    Modal.confirm({
      title: `删除选中的 ${deletingIds.length} 条链接记录？`,
      content: '删除后会从当前链接列表移除，不影响商品池原始商品。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => {
        const deletingIdSet = new Set(deletingIds);
        setSelectedRecordIds((current) => current.filter((id) => !deletingIdSet.has(id)));
        if (onDeleteMany) {
          onDeleteMany(deletingIds);
          return;
        }
        deletingIds.forEach(onDelete);
      },
    });
  };

  const openImageManager = (record: LinkListRecord, slotId?: string) => {
    const firstSlotId = getRecordProductImageSlotItems(record)[0]?.slot.id;
    setImageManagerRecord(record);
    setImageEditorOpen(false);
    setManagerActiveSlotId(slotId || firstSlotId);
    setImageManagerActiveSkuEntryId(record.skuEntries[0]?.id);
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

  const commitImageManagerRecord = (nextRecord: LinkListRecord, successText?: string) => {
    onUpdate(nextRecord);
    setPreviewRecord((current) => (current?.id === nextRecord.id ? nextRecord : current));
    setImageManagerRecord((current) => (current?.id === nextRecord.id ? nextRecord : current));
    if (successText) message.success(successText);
  };

  const toggleImageManagerAsset = (assetId: string) => {
    setImageManagerSelectedAssetIds((current) =>
      current.includes(assetId) ? current.filter((id) => id !== assetId) : [...current, assetId],
    );
  };

  const addSelectedAssetsToProductImages = () => {
    if (!imageManagerRecord) return;
    const productAssetIds = imageManagerSelectedAssets
      .filter((option) => option.asset.role === 'product-main' || option.asset.role === 'product-material')
      .map((option) => option.asset.id);
    if (productAssetIds.length === 0) {
      message.warning('请先在左侧图库选择商品图素材');
      return;
    }
    const beforeCount = getEditableProductImageSlotItems(imageManagerRecord).length;
    const nextRecord = addProductImageAssets(imageManagerRecord, productAssetIds);
    const afterItems = getEditableProductImageSlotItems(nextRecord);
    const addedCount = Math.max(0, afterItems.length - beforeCount);
    commitImageManagerRecord(nextRecord, addedCount > 0 ? `已加入 ${addedCount} 张主图` : '所选图片已在主图中');
    setImageManagerSelectedSlotIds(afterItems.slice(-Math.max(addedCount, 0)).map((item) => item.slot.id));
    if (afterItems.length > 0) setManagerActiveSlotId(afterItems[Math.max(0, afterItems.length - 1)]?.slot.id);
  };

  const openSkuImageBindingDialog = (
    targetSkuIds: string[] = imageManagerSelectedSkuIds,
    options: { pendingMainGalleryCount?: number | null; pendingMainGallerySelectedSkuIds?: string[] } = {},
  ) => {
    if (!imageManagerRecord) return;
    if (skuImageBindingCandidateImages.length === 0) {
      message.warning('请先在图库或 SKU 图中选择要作为绑定参数的图片');
      return;
    }
    const subjects = getSkuImageBindingSubjects(imageManagerRecord, targetSkuIds);
    if (subjects.length === 0) {
      message.warning('当前没有可绑定的 SKU');
      return;
    }
    setSkuImageBindingTargetSkuIds(targetSkuIds);
    setSkuImageBindingChoices(createDefaultSkuImageBindingChoices(subjects, skuImageBindingCandidateImages));
    setSkuImageBindingPendingMainGalleryCount(options.pendingMainGalleryCount ?? null);
    setSkuImageBindingPendingMainGallerySkuIds(options.pendingMainGallerySelectedSkuIds);
    setSkuImageBindingOpen(true);
  };

  const addSelectedAssetsToSkuImages = () => {
    if (!imageManagerRecord) return;
    if (imageManagerSelectedAssets.length === 0) {
      message.warning('请先在左侧图库选择要加入 SKU 的图片');
      return;
    }
    const assetIds = imageManagerSelectedAssets.map((option) => option.asset.id);
    const targetEntries = getTargetSkuEntries(imageManagerRecord, imageManagerSelectedSkuIds);
    const emptyTargetEntries = targetEntries.filter((entry) => !getSkuDisplayImageUrl(entry));
    if (emptyTargetEntries.length === 0) {
      message.info('当前 SKU 图位没有空缺，请先删除要替换的 SKU 图');
      return;
    }
    const nextRecord = addSkuImageAssetsDirect(imageManagerRecord, assetIds, imageManagerSelectedSkuIds);
    const addedCount = Math.min(assetIds.length, emptyTargetEntries.length);
    commitImageManagerRecord(nextRecord, `已按顺序填补 ${addedCount} 张 SKU 图`);
  };

  const confirmSkuImageBindings = () => {
    if (!imageManagerRecord) return;
    const boundCount = skuImageBindingSubjects.filter((subject) =>
      getSkuImageBindingChoiceKeys(subject).some((choiceKey) => skuImageBindingChoices[choiceKey]),
    ).length;
    const pendingMainGalleryCount = skuImageBindingPendingMainGalleryCount;
    const pendingSkuIds = skuImageBindingPendingMainGallerySkuIds ?? skuImageBindingTargetSkuIds;
    const pendingReferenceSkuIds = skuImageBindingTargetSkuIds;
    const boundReferenceImageDescriptors = getSkuImageBindingReferenceDescriptors(
      imageManagerRecord,
      skuImageBindingSubjects,
      skuImageBindingChoices,
      skuImageBindingCandidateImages,
    );
    const nextRecord = applySkuImageBindingChoices(
      imageManagerRecord,
      skuImageBindingSubjects,
      skuImageBindingChoices,
      skuImageBindingCandidateImages,
    );
    commitImageManagerRecord(nextRecord, boundCount > 0 ? `已绑定 ${boundCount} 个 SKU 图片项` : '未绑定新的 SKU 图片');
    setSkuImageBindingOpen(false);
    setSkuImageBindingTargetSkuIds([]);
    setSkuImageBindingPendingMainGalleryCount(null);
    setSkuImageBindingPendingMainGallerySkuIds(undefined);
    if (pendingMainGalleryCount !== null) {
      enqueueMainGalleryWithRecord(nextRecord, pendingMainGalleryCount, pendingSkuIds, {
        includeSelectedGalleryRefs: false,
        referenceSkuIds: pendingReferenceSkuIds,
        referenceImageDescriptors: boundReferenceImageDescriptors,
      });
    }
  };

  const removeProductImageFromEditor = (slotId: string) => {
    if (!imageManagerRecord) return;
    const nextRecord = removeProductImageSlot(imageManagerRecord, slotId);
    commitImageManagerRecord(nextRecord, '已删除主图');
    setImageManagerSelectedSlotIds((current) => current.filter((id) => id !== slotId));
    if (managerActiveSlotId === slotId) {
      setManagerActiveSlotId(getEditableProductImageSlotItems(nextRecord)[0]?.slot.id);
    }
  };

  const removeSkuImageFromEditor = (skuEntryId: string) => {
    if (!imageManagerRecord) return;
    const nextRecord = removeSkuImage(imageManagerRecord, skuEntryId);
    commitImageManagerRecord(nextRecord, '已删除 SKU 图');
    setImageManagerSelectedSkuIds((current) => current.filter((id) => id !== skuEntryId));
  };

  const reorderProductImageFromEditor = (targetSlotId: string) => {
    if (!imageManagerRecord || !draggingProductSlotId) return;
    const nextRecord = reorderProductImageSlot(imageManagerRecord, draggingProductSlotId, targetSlotId);
    commitImageManagerRecord(nextRecord);
    setManagerActiveSlotId(draggingProductSlotId);
    setDraggingProductSlotId(undefined);
  };

  const reorderSkuFromEditor = (targetSkuEntryId: string) => {
    if (!imageManagerRecord || !draggingSkuEntryId) return;
    const nextRecord = reorderSkuEntry(imageManagerRecord, draggingSkuEntryId, targetSkuEntryId);
    commitImageManagerRecord(nextRecord);
    setImageManagerActiveSkuEntryId(draggingSkuEntryId);
    setDraggingSkuEntryId(undefined);
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

  const enqueueVisualTask = async (
    record: LinkListRecord,
    task: ReturnType<typeof getRecordVisualTaskPackages>[number],
    options: {
      mode: VisualPublishMode;
      count: number;
      referenceImageUrl?: string;
      referenceImageUrls?: string[];
      referenceImageLabels?: string[];
      selectedSkuIds?: string[];
      selectedSlotIds?: string[];
      autoRun?: boolean;
      openQueue?: boolean;
    },
  ) => {
    const referenceImageUrl = options.referenceImageUrl || getRecordMainImageUrl(record);
    if (!referenceImageUrl) {
      message.warning('\u8bf7\u5148\u9009\u62e9\u4e00\u5f20\u53c2\u8003\u56fe');
      return;
    }

    const draftItem = createVisualQueueItem(record, task, {
      ...options,
      referenceImageUrl,
      referenceImageUrls: options.referenceImageUrls,
      referenceImageLabels: options.referenceImageLabels,
    });
    const referenceImageRefs = getVisualReferenceImageRefs(draftItem);
    const primaryReferenceImageUrl = referenceImageRefs[0]?.url || draftItem.referenceImageUrl;

    try {
      const created = await createVisualGenerationTask({
        record: getVisualTaskRecordWithQueueMeta(record, draftItem),
        linkRecordId: record.id,
        productId: record.productId,
        mode: getVisualTaskApiMode(draftItem.mode),
        layout: getVisualTaskLayout(draftItem.requestedCount),
        requestedCount: draftItem.requestedCount,
        sourceImageRef: primaryReferenceImageUrl,
        referenceImageRefs,
      });
      const item: VisualQueueItem = {
        ...draftItem,
        id: `queue-${created.id}`,
        backendTaskId: created.id,
        backendStatus: created.status,
        createdAt: created.createdAt || draftItem.createdAt,
      };
      setVisualQueueItems((current) => [item, ...current.filter((candidate) => candidate.backendTaskId !== created.id)]);
      setActiveVisualQueueItemId(item.id);
      setExpandedVisualQueueItemIds((current) => [item.id, ...current.filter((id) => id !== item.id)]);
      if (options.autoRun) {
        message.success('\u5df2\u521b\u5efa\u751f\u56fe\u4efb\u52a1\uff0c\u6b63\u5728\u81ea\u52a8\u6267\u884c');
        window.setTimeout(() => {
          const recordMap = new Map(records.map((candidate) => [candidate.id, candidate]));
          setVisualQueueExecuting(true);
          void executeVisualQueueItem(item, recordMap)
            .then(() => {
              message.success('\u751f\u56fe\u4efb\u52a1\u5df2\u5b8c\u6210\uff0c\u7ed3\u679c\u5df2\u56de\u5199\u5230\u94fe\u63a5\u5217\u8868');
            })
            .catch((error) => {
              const errorMessage = error instanceof Error ? error.message : '\u751f\u56fe\u4efb\u52a1\u6267\u884c\u5931\u8d25';
              failVisualQueueItemToTail(item.id, errorMessage);
              message.warning(`生图任务执行失败，已移到队尾：${errorMessage}`);
            })
            .finally(() => {
              setVisualQueueExecuting(false);
            });
        }, 0);
        return;
      }
      if (options.openQueue !== false) setVisualQueueOpen(true);
      message.success('\u5df2\u52a0\u5165\u7edf\u4e00\u4efb\u52a1\u961f\u5217');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '\u4efb\u52a1\u961f\u5217\u521b\u5efa\u5931\u8d25');
    }
  };

  const enqueueMainGalleryWithRecord = (
    record: LinkListRecord,
    requestedCount?: number,
    selectedSkuIds: string[] = imageManagerSelectedSkuIds,
    options: {
      includeSelectedGalleryRefs?: boolean;
      referenceSkuIds?: string[];
      referenceImageDescriptors?: Array<{ url: string; label: string }>;
    } = {},
  ) => {
    if (!imageManagerProductTask) return;
    const referenceImageDescriptors =
      options.referenceImageDescriptors && options.referenceImageDescriptors.length > 0
        ? options.referenceImageDescriptors
        : mergeImageRefDescriptors(
            options.includeSelectedGalleryRefs === false ? [] : getSelectedGalleryImageRefDescriptors(imageManagerSelectedAssets, record),
            options.referenceSkuIds && options.referenceSkuIds.length > 0
              ? getSelectedSkuImageRefDescriptors(record, options.referenceSkuIds)
              : [],
          );
    const referenceImageUrls = referenceImageDescriptors.map((item) => item.url);
    if (referenceImageUrls.length === 0) {
      message.warning('请先在图库或 SKU 中选择要作为主图生成依据的图片');
      return;
    }
    enqueueVisualTask(record, imageManagerProductTask, {
      mode: 'main_multi',
      count: requestedCount || getRecordProductImageGenerationCount(record),
      referenceImageUrl: referenceImageUrls[0],
      referenceImageUrls,
      referenceImageLabels: referenceImageDescriptors.map((item) => item.label),
      selectedSkuIds,
      autoRun: true,
      openQueue: false,
    });
  };

  const enqueueMainGalleryFromSelectedSkus = (requestedCount?: number) => {
    if (!imageManagerRecord || !imageManagerProductTask) return;
    const count = requestedCount || getRecordProductImageGenerationCount(imageManagerRecord);
    if (!canEnqueueMainGalleryFromImageManager) {
      message.warning('请先在图库或 SKU 中选择要作为主图生成依据的图片');
      return;
    }
    if (skuImageBindingCandidateImages.length > 0 && imageManagerRecord.skuEntries.length > 0) {
      const bindingTargetSkuIds = getSkuImageBindingDialogSkuIds(imageManagerRecord);
      if (bindingTargetSkuIds.length > 0) {
        openSkuImageBindingDialog(bindingTargetSkuIds, {
          pendingMainGalleryCount: count,
          pendingMainGallerySelectedSkuIds: [],
        });
        return;
      }
    }
    enqueueMainGalleryWithRecord(imageManagerRecord, count, imageManagerSelectedSkuIds);
  };

  const enqueueSkuAdaptFromSelectedSkus = () => {
    if (!imageManagerRecord || !imageManagerSkuTask) return;
    const selectedSkuIds =
      imageManagerSelectedSkuIds.length > 0
        ? imageManagerSelectedSkuIds
        : imageManagerActiveSkuEntry
          ? [imageManagerActiveSkuEntry.id]
          : [];
    if (selectedSkuIds.length === 0) {
      message.warning('请先选择要适配的 SKU');
      return;
    }
    const referenceImageDescriptors = getSelectedSkuImageRefDescriptors(imageManagerRecord, selectedSkuIds);
    const referenceImageUrls = referenceImageDescriptors.map((item) => item.url);
    if (referenceImageUrls.length === 0) {
      message.warning('选中的 SKU 没有可用图片，不能作为 SKU 适配参数');
      return;
    }
    enqueueVisualTask(imageManagerRecord, imageManagerSkuTask, {
      mode: 'sku_adapt',
      count: selectedSkuIds.length,
      referenceImageUrl: referenceImageUrls[0],
      referenceImageUrls,
      referenceImageLabels: referenceImageDescriptors.map((item) => item.label),
      selectedSkuIds,
      autoRun: true,
      openQueue: false,
    });
  };

  const removeVisualQueueItem = async (queueItemId: string) => {
    const item = visualQueueItems.find((candidate) => candidate.id === queueItemId);
    if (item?.backendTaskId) {
      try {
        await deleteVisualGenerationTask(item.backendTaskId);
      } catch (error) {
        message.error(error instanceof Error ? error.message : '\u5220\u9664\u540e\u7aef\u4efb\u52a1\u5931\u8d25');
        return;
      }
    }
    setVisualQueueItems((current) => current.filter((candidate) => candidate.id !== queueItemId));
    setExpandedVisualQueueItemIds((current) => current.filter((id) => id !== queueItemId));
    setVisualWorkflowStageByItemId((current) => {
      const next = { ...current };
      delete next[queueItemId];
      return next;
    });
  };

  const clearVisualQueue = async () => {
    const backendTaskIds = visualQueueItems.map((item) => item.backendTaskId).filter((id): id is string => Boolean(id));
    const results = await Promise.allSettled(backendTaskIds.map((taskId) => deleteVisualGenerationTask(taskId)));
    const failedCount = results.filter((result) => result.status === 'rejected').length;
    if (failedCount > 0) {
      message.warning(`\u6709 ${failedCount} \u4e2a\u540e\u7aef\u4efb\u52a1\u5220\u9664\u5931\u8d25\uff0c\u5df2\u4fdd\u7559\u5728\u961f\u5217\u4e2d`);
      const failedIds = new Set(
        results
          .map((result, index) => (result.status === 'rejected' ? backendTaskIds[index] : undefined))
          .filter((id): id is string => Boolean(id)),
      );
      setVisualQueueItems((current) => current.filter((item) => item.backendTaskId && failedIds.has(item.backendTaskId)));
      return;
    }
    setVisualQueueItems([]);
    setExpandedVisualQueueItemIds([]);
    setVisualWorkflowStageByItemId({});
  };

  const patchVisualQueueItem = (
    queueItemId: string,
    patcher: (item: VisualQueueItem) => Partial<VisualQueueItem>,
  ) => {
    setVisualQueueItems((current) =>
      current.map((item) => (item.id === queueItemId ? { ...item, ...patcher(item) } : item)),
    );
  };

  const failVisualQueueItemToTail = (queueItemId: string, errorMessage: string) => {
    setVisualQueueItems((current) => {
      const failedItem = current.find((item) => item.id === queueItemId);
      if (!failedItem) return current;
      const nextFailedItem: VisualQueueItem = {
        ...failedItem,
        statusLabel: '执行失败',
        statusColor: 'red',
        backendStatus: 'failed',
        errorMessage,
        modules: failedItem.modules.map((module) => ({
          ...module,
          statusLabel: '失败',
          statusColor: 'red',
        })),
      };
      return [...current.filter((item) => item.id !== queueItemId), nextFailedItem];
    });
    setExpandedVisualQueueItemIds((current) => current.filter((id) => id !== queueItemId));
    setActiveVisualQueueItemId((current) => (current === queueItemId ? undefined : current));
  };

  const executeVisualQueueItem = async (item: VisualQueueItem, recordMap: Map<string, LinkListRecord>) => {
    const record = recordMap.get(item.recordId) || records.find((candidate) => candidate.id === item.recordId);
    if (!record) {
      throw new Error('找不到该链接记录，请刷新后重试');
    }

    const markModules = (statusLabel: string, statusColor: string) =>
      item.modules.map((module) => ({
        ...module,
        statusLabel,
        statusColor,
      }));

    patchVisualQueueItem(item.id, () => ({
      statusLabel: '创建中',
      statusColor: 'processing',
      backendStatus: 'creating',
      errorMessage: undefined,
      modules: markModules('排队中', 'processing'),
    }));

    const taskRecord =
      ['main_multi', 'sku_adapt'].includes(item.mode) && item.selectedSkuIds?.length
        ? {
            ...record,
            skuEntries: record.skuEntries.filter((entry) => item.selectedSkuIds?.includes(entry.id)),
            componentSkuCount: record.skuEntries
              .filter((entry) => item.selectedSkuIds?.includes(entry.id))
              .reduce((total, entry) => total + Math.max(1, entry.componentSkus?.length || 1), 0),
          }
        : record;

    const referenceImageRefs = getVisualReferenceImageRefs(item);
    const primaryReferenceImageUrl = referenceImageRefs[0]?.url || item.referenceImageUrl;

    const created = item.backendTaskId
      ? await fetchVisualGenerationTask(item.backendTaskId)
      : await createVisualGenerationTask({
          record: getVisualTaskRecordWithQueueMeta(record, item),
          linkRecordId: record.id,
          productId: record.productId,
          mode: getVisualTaskApiMode(item.mode),
          layout: getVisualTaskLayout(item.requestedCount),
          requestedCount: item.requestedCount,
          sourceImageRef: primaryReferenceImageUrl,
          referenceImageRefs,
        });

    patchVisualQueueItem(item.id, () => ({
      backendTaskId: created.id,
      backendStatus: created.status,
      statusLabel: '后台执行中',
      statusColor: 'processing',
      errorMessage: undefined,
      modules: markModules('等待回写', 'processing'),
    }));

    const runResult = await runVisualGenerationTask(created.id, {
      sourceImageRef: primaryReferenceImageUrl,
      referenceImageRefs,
      allowShortLabels: true,
      splitAfter: true,
      uploadToOss: true,
      useReferenceImage: true,
      applyToLinkRecord: true,
      reuseExistingOutputs: Boolean(item.backendTaskId),
    });
    const waitingForConcurrency = Boolean(runResult.waitingForConcurrency);
    if (waitingForConcurrency) {
      message.info(runResult.message || '\u5df2\u8d85\u8fc7\u6210\u5458\u5e76\u53d1\u4e0a\u9650\uff0c\u4efb\u52a1\u5df2\u8fdb\u5165\u7b49\u5f85\u961f\u5217');
    }

    patchVisualQueueItem(item.id, () => ({
      backendTaskId: created.id,
      backendStatus: runResult.item.status || (waitingForConcurrency ? 'queued' : 'running'),
      statusLabel: waitingForConcurrency ? '\u6392\u961f\u7b49\u5f85' : '\u751f\u6210\u4e2d',
      statusColor: waitingForConcurrency ? 'blue' : 'processing',
      errorMessage: undefined,
      modules: markModules(waitingForConcurrency ? '\u7b49\u5f85\u7a7a\u4f4d' : '\u751f\u6210\u4e2d', waitingForConcurrency ? 'blue' : 'processing'),
    }));

    const generated = await waitForVisualGenerationTask(created.id, waitingForConcurrency ? 7200 : 180, (progressTask) => {
      const hasAnalysis = hasVisualDetail(progressTask.analysis);
      if (!hasAnalysis && !progressTask.promptText) return;
      patchVisualQueueItem(item.id, (current) => ({
        backendTaskId: created.id,
        backendStatus: progressTask.status,
        analysis: hasAnalysis ? progressTask.analysis : current.analysis,
        promptText: progressTask.promptText || current.promptText,
        motherImageUrl: progressTask.motherImageUrl || current.motherImageUrl,
        motherImagePath: progressTask.motherImagePath || current.motherImagePath,
        manifest: progressTask.manifest || current.manifest,
        errorMessage: progressTask.status === 'failed' ? progressTask.errorMessage || current.errorMessage : undefined,
      }));
    });
    const itemWithBackendId = { ...item, backendTaskId: created.id };
    let nextRecord = applyVisualGenerationResult(record, itemWithBackendId, generated);
    try {
      const refreshedRecords = await fetchLinkListRecords();
      nextRecord = refreshedRecords.find((candidate) => candidate.id === record.id) || nextRecord;
    } catch {
      // The backend has the durable record; keep the task result visible if refresh is temporarily unavailable.
    }
    recordMap.set(nextRecord.id, nextRecord);
    onUpdate(nextRecord);
    setPreviewRecord((current) => (current?.id === nextRecord.id ? nextRecord : current));
    setImageManagerRecord((current) => (current?.id === nextRecord.id ? nextRecord : current));

    const generatedModules = [...(generated.modules || [])].sort(
      (left, right) => (left.panelIndex || 0) - (right.panelIndex || 0),
    );
    const completedCount = generatedModules.filter((module) => getVisualTaskResultUrl(module)).length;
    const remoteCount = generatedModules.filter((module) => isRemoteImageUrl(module.outputUrl || undefined)).length;

    patchVisualQueueItem(item.id, () => ({
      backendTaskId: created.id,
      backendStatus: generated.status,
      statusLabel: completedCount > 0 ? '已回写' : '未返回图片',
      statusColor: completedCount > 0 ? 'green' : 'gold',
      completedCount,
      analysis: generated.analysis,
      promptText: generated.promptText,
      motherImageUrl: generated.motherImageUrl || undefined,
      motherImagePath: generated.motherImagePath || undefined,
      manifest: generated.manifest,
      errorMessage: generated.status === 'failed' ? generated.errorMessage || undefined : undefined,
      modules: item.modules.map((module, index) => {
        const generatedModule = generatedModules[index];
        const resultUrl = generatedModule ? getVisualTaskResultUrl(generatedModule) : undefined;
        return {
          ...module,
          imageUrl: resultUrl || module.imageUrl,
          outputUrl: generatedModule?.outputUrl || undefined,
          outputPath: generatedModule?.outputPath || undefined,
          statusLabel: resultUrl ? '已回写' : '未返回图片',
          statusColor: resultUrl ? 'green' : 'gold',
        };
      }),
    }));

    if (completedCount > 0 && remoteCount === 0) {
      message.warning('Generated images are saved locally, but no OSS public URL was returned. Check OSS settings.');
    }
  };

  const executeVisualQueue = async () => {
    const pendingItems = visualQueueItems.filter(isVisualQueueItemRunnable);
    if (pendingItems.length === 0) {
      const activeCount = visualQueueItems.filter(isVisualQueueItemActive).length;
      message.info(activeCount > 0 ? '当前已有任务在执行或等待空位，没有新的可执行失败任务' : '队列中没有待执行任务');
      return;
    }

    setVisualQueueExecuting(true);
    const recordMap = new Map(records.map((record) => [record.id, record]));
    let latestSummary = visualQueueSummary;
    try {
      try {
        latestSummary = await fetchVisualQueueSummary();
        setVisualQueueSummary(latestSummary);
      } catch {
        // Summary is only used to size the local worker pool; fallback keeps local dev usable.
      }

      const fallbackLimit = Math.min(pendingItems.length, LOCAL_VISUAL_QUEUE_FALLBACK_WORKERS);
      const userLimit = Number(latestSummary?.userConcurrencyLimit || 0);
      const teamLimit = Number(latestSummary?.teamConcurrencyLimit || 0);
      const userRunning = Number(latestSummary?.runningCount ?? latestSummary?.activeCount ?? 0);
      const teamRunning = Number(latestSummary?.teamRunningCount ?? latestSummary?.teamActiveCount ?? 0);
      const userAvailable = userLimit > 0 ? Math.max(0, userLimit - userRunning) : fallbackLimit;
      const teamAvailable = teamLimit > 0 ? Math.max(0, teamLimit - teamRunning) : fallbackLimit;
      const workerCount = Math.max(1, Math.min(pendingItems.length, userAvailable || 1, teamAvailable || 1));
      const itemQueue = [...pendingItems];
      const attemptByItemId = new Map<string, number>();
      let successCount = 0;
      let failedCount = 0;
      let retryCount = 0;

      const runWorker = async () => {
        while (itemQueue.length > 0) {
          const item = itemQueue.shift();
          if (!item) return;
          const attempt = (attemptByItemId.get(item.id) || 0) + 1;
          attemptByItemId.set(item.id, attempt);
          try {
            // eslint-disable-next-line no-await-in-loop
            await executeVisualQueueItem(item, recordMap);
            successCount += 1;
          } catch (error) {
            const errorMessage = error instanceof Error ? error.message : '生图任务执行失败';
            failVisualQueueItemToTail(item.id, errorMessage);
            if (attempt < LOCAL_VISUAL_QUEUE_MAX_ATTEMPTS_PER_CLICK) {
              retryCount += 1;
              message.warning(`任务执行失败，已移到队尾，稍后自动重试：${errorMessage}`);
              // eslint-disable-next-line no-await-in-loop
              await waitForMs(1500);
              itemQueue.push(item);
            } else {
              failedCount += 1;
              message.warning(`任务执行失败，已达到本轮重试上限：${errorMessage}`);
            }
          }
        }
      };

      await Promise.all(Array.from({ length: workerCount }, () => runWorker()));

      if (successCount > 0) {
        message.success(`已执行 ${successCount} 个生图任务，结果已回写到链接列表`);
      }
      if (failedCount > 0) {
        message.warning(`${failedCount} 个生图任务本轮仍失败，已保留在队尾，可稍后再次执行`);
      }
      if (retryCount > 0) {
        message.info(`本轮已自动补位重试 ${retryCount} 次`);
      }
    } finally {
      setVisualQueueExecuting(false);
      void refreshVisualQueueSummary().catch((error) => {
        console.warn('Failed to refresh visual queue summary after execution', error);
      });
    }
  };

  const renderVisualQueueWorkflow = (item: VisualQueueItem) => {
    const workflowStates = getVisualWorkflowStates(item);
    const motherImageUrl = getVisualMotherImageUrl(item);
    const splitModules = item.modules.filter((module) => module.outputUrl || module.outputPath);
    const motherImagePlaceholder = item.motherImagePath || '生成完成后展示九宫格母图。';
    const stages = [
      {
        title: '商品身份分析',
        description: '读取任务输入并完成商品身份、标题和 SKU 绑定分析。',
        body: (
          <>
            <div className="visual-workflow-fact-grid">
              <div><span>模式</span><strong>{item.modeLabel}</strong></div>
              <div><span>请求数量</span><strong>{item.requestedCount}</strong></div>
              <div><span>网格布局</span><strong>{getVisualQueueLayoutLabel(item.requestedCount)}</strong></div>
              <div><span>组批策略</span><strong>{item.mixPolicy}</strong></div>
            </div>
            {renderVisualAnalysisResult(item.analysis, getVisualInputPromptText(item))}
          </>
        ),
      },
      {
        title: '提示词规划',
        description: '整合九宫格任务规划和单图提示词生成，展示最终九宫格提示词。',
        body: <pre>{item.promptText || '等待九宫格提示词规划完成后展示。'}</pre>,
      },
      {
        title: '图片生成',
        description: '生成母图、切割九宫格，并把结果回写到商品图位。',
        body: (
          <>
            {motherImageUrl ? (
              <Image
                alt="九宫格母图"
                className="visual-workflow-mother-image"
                referrerPolicy="no-referrer"
                src={motherImageUrl}
              />
            ) : (
              <div
                className="visual-workflow-placeholder visual-workflow-path-placeholder"
                title={item.motherImagePath || undefined}
              >
                {motherImagePlaceholder}
              </div>
            )}
            {splitModules.length > 0 ? (
              <div className="visual-workflow-split-grid">
                {splitModules.map((module, index) => (
                  <div className="visual-workflow-split-item" key={module.id}>
                    <span>{index + 1}</span>
                    {module.outputUrl ? (
                      <Image
                        alt={module.title}
                        height={72}
                        preview={false}
                        referrerPolicy="no-referrer"
                        src={module.outputUrl}
                        width={72}
                      />
                    ) : (
                      <PictureOutlined />
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="visual-workflow-placeholder">切割并回写完成后展示结果。</div>
            )}
          </>
        ),
      },
    ];

    const errorStageIndex = workflowStates.findIndex((state) => state === 'error');
    const firstActiveStageIndex = workflowStates.findIndex((state) => state === 'active');
    const fallbackStageIndex =
      errorStageIndex >= 0
        ? errorStageIndex
        : firstActiveStageIndex >= 0
          ? firstActiveStageIndex
          : Math.max(0, workflowStates.lastIndexOf('done'));
    const selectedStageIndex = Math.min(
      stages.length - 1,
      Math.max(0, errorStageIndex >= 0 ? errorStageIndex : visualWorkflowStageByItemId[item.id] ?? fallbackStageIndex),
    );
    const selectedStage = stages[selectedStageIndex] || stages[0];
    const selectedState = workflowStates[selectedStageIndex] || 'waiting';
    const getStageStatusText = (state: string) => {
      if (state === 'done') return '完成';
      if (state === 'active') return '进行中';
      if (state === 'error') return '失败';
      return '等待';
    };

    return (
      <div className="visual-workflow visual-workflow-line">
        <div className="visual-workflow-track" role="tablist" aria-label="生图任务阶段">
          {stages.map((stage, index) => {
            const state = workflowStates[index] || 'waiting';
            const selected = index === selectedStageIndex;
            return (
              <button
                aria-selected={selected}
                className={`visual-workflow-track-step visual-workflow-track-step-${state} ${
                  selected ? 'visual-workflow-track-step-selected' : ''
                }`}
                key={stage.title}
                role="tab"
                type="button"
                onClick={() =>
                  setVisualWorkflowStageByItemId((current) => ({
                    ...current,
                    [item.id]: index,
                  }))
                }
              >
                <span className="visual-workflow-track-dot">
                  {state === 'done' ? <CheckCircleOutlined /> : state === 'error' ? <WarningOutlined /> : index + 1}
                </span>
                <span className="visual-workflow-track-copy">
                  <strong>{stage.title}</strong>
                  <small>{getStageStatusText(state)}</small>
                </span>
              </button>
            );
          })}
        </div>
        <div className={`visual-workflow-detail visual-workflow-detail-${selectedState}`}>
          <div className="visual-workflow-title-row">
            <div>
              <Text strong>{selectedStage.title}</Text>
              <Text type="secondary">{selectedStage.description}</Text>
            </div>
            <Tag color={selectedState === 'done' ? 'green' : selectedState === 'active' ? 'blue' : selectedState === 'error' ? 'red' : 'default'}>
              {getStageStatusText(selectedState)}
            </Tag>
          </div>
          <div className="visual-workflow-body">{selectedStage.body}</div>
        </div>
      </div>
    );

    return (
      <div className="visual-workflow visual-workflow-compact">
        {stages.map((stage, index) => {
          const state = workflowStates[index] || 'waiting';
          return (
            <div className={`visual-workflow-step visual-workflow-step-${state}`} key={stage.title}>
              <div className="visual-workflow-marker">
                {state === 'done' ? <CheckCircleOutlined /> : state === 'error' ? <WarningOutlined /> : index + 1}
              </div>
              <div className="visual-workflow-content">
                <div className="visual-workflow-title-row">
                  <div>
                    <Text strong>{stage.title}</Text>
                    <Text type="secondary">{stage.description}</Text>
                  </div>
                  <Tag color={state === 'done' ? 'green' : state === 'active' ? 'blue' : state === 'error' ? 'red' : 'default'}>
                    {state === 'done' ? '完成' : state === 'active' ? '进行中' : state === 'error' ? '失败' : '等待'}
                  </Tag>
                </div>
                <div className="visual-workflow-body">{stage.body}</div>
              </div>
            </div>
          );
        })}
      </div>
    );
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
              <Text type="secondary">已选 {selectedRecords.length}</Text>
              <Button disabled={records.length === 0} onClick={() => setSelectedRecordIds(records.map((record) => record.id))}>
                全选
              </Button>
              <Button disabled={selectedRecordIds.length === 0} onClick={() => setSelectedRecordIds([])}>
                清空
              </Button>
              <Button danger disabled={selectedRecords.length === 0} onClick={deleteSelectedRecords}>
                删除选中
              </Button>
              <Button
                disabled={selectedRecords.length === 0 || !onExportRecords}
                loading={exporting}
                type="primary"
                onClick={() => void exportSelectedRecords()}
              >
                导出选中
              </Button>
              <Button icon={<ClockCircleOutlined />} onClick={openUnifiedQueue}>
                任务队列
                {totalQueueTaskCount > 0 ? ` ${totalQueueTaskCount}` : ''}
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
              const selected = selectedRecordIds.includes(record.id);
              const recordDisplayTitle = getRecordDisplayTitle(record);
              return (
            <Card
              className={`link-record-card ${selected ? 'link-record-card-selected' : ''}`}
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
                <div className="link-record-select" onClick={(event) => event.stopPropagation()}>
                  <Checkbox
                    checked={selected}
                    aria-label={`选择导出 ${record.productTitle}`}
                    onChange={(event) => toggleLinkRecordSelection(record.id, event.target.checked)}
                  />
                </div>
                <div className="link-record-image">
                  {getRecordMainImageUrl(record) ? (
                    <Image
                      alt={recordDisplayTitle}
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
                      {recordDisplayTitle}
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
                      setSelectedRecordIds((current) => current.filter((id) => id !== record.id));
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
                      alt={`${previewDisplayTitle} 商品图 ${index + 1}`}
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
                      alt={previewDisplayTitle}
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
                        onClick={() => setImageSlotPickerOpen(true)}
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
                  <Text>{previewDisplayTitle.slice(0, 34)}...</Text>
                </Space>

                <Typography.Title className="temu-preview-title" level={3}>
                  {previewDisplayTitle}
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
                    {activePreviewSkuEntry ? (
                      <Text type="secondary">Selected: {getSkuEntryDisplayName(activePreviewSkuEntry)}</Text>
                    ) : null}
                  </div>
                  <div className="temu-preview-sku-grid">
                    {previewRecord.skuEntries.map((entry) => {
                      const skuImageUrl = getSkuDisplayImageUrl(entry);
                      const skuDisplayName = getSkuEntryDisplayName(entry);
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
                                alt={skuDisplayName}
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
                            <span>{skuDisplayName}</span>
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
            <Button
              disabled={visualQueueExecuting || visualQueueItems.length === 0}
              onClick={() => void clearVisualQueue()}
            >
              清空队列
            </Button>
            <Button
              disabled={visualQueueItems.length === 0}
              loading={visualQueueExecuting}
              type="primary"
              onClick={() => void executeVisualQueue()}
            >
              开始执行
            </Button>
            <Button onClick={() => setVisualQueueOpen(false)}>
              知道了
            </Button>
          </Space>
        }
        open={visualQueueOpen}
        title="统一任务队列"
        width={1120}
        onCancel={() => setVisualQueueOpen(false)}
      >
        <div className="visual-queue-shell">
          <div className="visual-queue-summary">
            <div>
              <span>队列任务</span>
              <strong>{totalQueueTaskCount}</strong>
            </div>
            <div>
              <span>Excel 导出</span>
              <strong>{exportQueueTasks.length}</strong>
            </div>
            <div>
              <span>Excel 等待/执行</span>
              <strong>{exportQueuePendingCount}</strong>
            </div>
            {visualQueueSummary ? (
              <>
                <div>
                  <span>{'\u540e\u7aef\u6392\u961f'}</span>
                  <strong>{visualQueueSummary.queuedCount ?? (visualQueueSummary.counts.queued || 0)}</strong>
                </div>
                <div>
                  <span>{'\u8fd0\u884c/\u6210\u5458\u4e0a\u9650'}</span>
                  <strong>
                    {visualQueueSummary.runningCount ?? (visualQueueSummary.counts.running || 0)}/
                    {visualQueueSummary.userConcurrencyLimit || '\u4e0d\u9650'}
                  </strong>
                </div>
                <div>
                  <span>Retry waiting</span>
                  <strong>{visualQueueSummary.counts.retry_waiting || 0}</strong>
                </div>
                <div>
                  <span>{'\u56e2\u961f\u8fd0\u884c/\u4e0a\u9650'}</span>
                  <strong>
                    {visualQueueSummary.teamRunningCount ?? (visualQueueSummary.teamActiveCount || 0)}/
                    {visualQueueSummary.teamConcurrencyLimit || '\u4e0d\u9650'}
                  </strong>
                </div>
                <div>
                  <span>Redis length</span>
                  <strong>{visualQueueSummary.redisQueueLength ?? '-'}</strong>
                </div>
                <div>
                  <span>Retry queue</span>
                  <strong>{visualQueueSummary.redisRetryQueueLength ?? '-'}</strong>
                </div>
                <div>
                  <span>Dead queue</span>
                  <strong>{visualQueueSummary.redisDeadQueueLength ?? '-'}</strong>
                </div>
              </>
            ) : null}
            <div>
              <span>模块总数</span>
              <strong>{visualQueueItems.reduce((sum, item) => sum + item.moduleCount, 0)}</strong>
            </div>
            <div>
              <span>执行状态</span>
              <strong>
                {visualQueueExecuting
                  ? '执行中'
                  : visualQueueItems.some((item) => item.statusColor === 'red')
                    ? '有失败'
                    : visualQueueItems.some((item) => item.completedCount > 0)
                      ? '已接入'
                      : '待执行'}
              </strong>
            </div>
          </div>
          <div className="visual-queue-filterbar">
            <Segmented
              value={visualQueueFilter}
              options={[
                {
                  label: (
                    <span className="visual-queue-filter-label">
                      <SyncOutlined />
                      <span>全部</span>
                      <strong>{totalQueueTaskCount}</strong>
                    </span>
                  ),
                  value: 'all',
                },
                {
                  label: (
                    <span className="visual-queue-filter-label">
                      <PictureOutlined />
                      <span>图片导出</span>
                      <strong>{visualQueueItems.length}</strong>
                    </span>
                  ),
                  value: 'visual',
                },
                {
                  label: (
                    <span className="visual-queue-filter-label">
                      <FileExcelOutlined />
                      <span>Excel 导出</span>
                      <strong>{exportQueueTasks.length}</strong>
                    </span>
                  ),
                  value: 'excel',
                },
              ]}
              onChange={(value) => setVisualQueueFilter(value as QueueTaskFilter)}
            />
            <span className="visual-queue-filter-hint">当前显示 {visibleQueueTaskCount} 个任务</span>
          </div>
          {visibleQueueTaskCount > 0 ? (
            <div className="visual-queue-accordion">
              {visibleVisualQueueItems.map((item) => {
                const active = activeVisualQueueItem?.id === item.id;
                const progress = getVisualQueueProgress(item);
                const referencePreviewRefs = getVisualReferenceImageRefs(item);
                const visibleReferencePreviewRefs = referencePreviewRefs.slice(0, 3);
                return (
                  <details
                    className={`visual-queue-panel ${active ? 'visual-queue-panel-active' : ''}`}
                    key={item.id}
                    open={expandedVisualQueueItemIds.includes(item.id)}
                    onToggle={(event) => {
                      if (event.currentTarget.open) {
                        setActiveVisualQueueItemId(item.id);
                        setExpandedVisualQueueItemIds((current) => [item.id, ...current.filter((id) => id !== item.id)]);
                      } else {
                        setExpandedVisualQueueItemIds((current) => current.filter((id) => id !== item.id));
                      }
                    }}
                  >
                    <summary className="visual-queue-panel-summary">
                      <span className="visual-queue-reference-thumb">
                        {visibleReferencePreviewRefs.length > 0 ? (
                          <>
                            {visibleReferencePreviewRefs.map((ref, index) => (
                              <Image
                                alt={ref.label || `${item.productTitle} reference ${index + 1}`}
                                height={visibleReferencePreviewRefs.length > 1 ? 34 : 46}
                                key={`${ref.url}-${index}`}
                                preview={false}
                                referrerPolicy="no-referrer"
                                src={ref.url}
                                width={visibleReferencePreviewRefs.length > 1 ? 34 : 46}
                              />
                            ))}
                            {referencePreviewRefs.length > visibleReferencePreviewRefs.length ? (
                              <span className="visual-queue-reference-more">
                                +{referencePreviewRefs.length - visibleReferencePreviewRefs.length}
                              </span>
                            ) : null}
                          </>
                        ) : (
                          <PictureOutlined />
                        )}
                      </span>
                      <span className="visual-queue-panel-main">
                        <span className="visual-queue-panel-title">
                          <strong>{item.modeLabel}</strong>
                          <Text ellipsis>{item.productTitle}</Text>
                        </span>
                        <span className="visual-queue-panel-meta">
                          <Tag color={item.statusColor}>{item.statusLabel}</Tag>
                          <Tag color="purple">{item.generationMode}</Tag>
                          <Tag color={item.styleLockStatus === 'ready' ? 'green' : 'gold'}>{item.styleLockLabel}</Tag>
                          <Tag color={referencePreviewRefs.length > 1 ? 'cyan' : 'default'}>
                            参考图 {referencePreviewRefs.length || 0}
                          </Tag>
                          <span>{item.requestedCount} 张</span>
                          <span>{getVisualQueueLayoutLabel(item.requestedCount)}</span>
                          <span>{item.backendTaskId || item.backendStatus || '待创建'}</span>
                        </span>
                      </span>
                      <span className="visual-queue-panel-progress">
                        <Progress percent={progress} showInfo={false} size="small" status={item.statusColor === 'red' ? 'exception' : 'active'} />
                        <strong>{progress}%</strong>
                      </span>
                      <Button
                        danger
                        size="small"
                        type="text"
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          void removeVisualQueueItem(item.id);
                        }}
                      >
                        移除
                      </Button>
                    </summary>
                    <div className="visual-queue-panel-body">
                      <div className="visual-queue-panel-facts">
                        <div><span>任务包</span><strong>{item.taskName}</strong></div>
                        <div><span>模块完成</span><strong>{item.completedCount}/{item.moduleCount}</strong></div>
                        <div><span>请求数量</span><strong>{item.requestedCount}</strong></div>
                        <div><span>组批策略</span><strong>{item.mixPolicy}</strong></div>
                      </div>
                      {item.errorMessage ? <div className="visual-queue-panel-error">{item.errorMessage}</div> : null}
                      {renderVisualQueueWorkflow(item)}
                    </div>
                  </details>
                );
              })}
              {visibleExportQueueTasks.map((task) => {
                const statusMeta = getDianxiaomiExportTaskStatusMeta(task);
                return (
                  <details className="visual-queue-panel visual-queue-export-panel" key={`export-${task.id}`} open={task.status !== 'completed'}>
                    <summary className="visual-queue-panel-summary">
                      <span className="visual-queue-panel-main">
                        <span className="visual-queue-panel-title">
                          <Text ellipsis>{task.filename || `店小秘导出任务 ${task.id}`}</Text>
                          <span className="visual-queue-export-stage">
                            {task.currentStage || statusMeta.label}
                            {task.totalCount ? ` · ${task.processedCount ?? 0}/${task.totalCount}` : ''}
                          </span>
                        </span>
                        <span className="visual-queue-panel-meta">
                          <Tag color={statusMeta.color}>{statusMeta.label}</Tag>
                          <Tag color="blue">{task.recordCount} 条链接</Tag>
                          <span>{task.exportMode}</span>
                          <span>{formatRecordTime(task.createdAt)}</span>
                        </span>
                      </span>
                      <span className="visual-queue-panel-progress">
                        <Progress percent={statusMeta.progress} showInfo={false} size="small" status={statusMeta.progressStatus} />
                        <strong>{statusMeta.progress}%</strong>
                      </span>
                      <Button
                        disabled={task.status !== 'completed'}
                        size="small"
                        type={task.status === 'completed' ? 'primary' : 'default'}
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          void downloadExportQueueTask(task);
                        }}
                      >
                        下载
                      </Button>
                      <Button
                        danger
                        size="small"
                        onClick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          void removeExportQueueTask(task);
                        }}
                      >
                        删除
                      </Button>
                    </summary>
                    <div className="visual-queue-panel-body">
                      <div className="visual-queue-panel-facts">
                        <div><span>任务 ID</span><strong>{task.id}</strong></div>
                        <div><span>商品链接</span><strong>{task.recordCount}</strong></div>
                        <div><span>状态</span><strong>{statusMeta.label}</strong></div>
                        <div><span>更新时间</span><strong>{formatRecordTime(task.updatedAt)}</strong></div>
                      </div>
                      <div className="visual-queue-panel-facts">
                        <div><span>当前阶段</span><strong>{task.currentStage || statusMeta.label}</strong></div>
                        <div><span>处理进度</span><strong>{task.processedCount ?? 0}/{task.totalCount || task.recordCount}</strong></div>
                        {task.currentRecordTitle ? <div><span>当前商品</span><strong>{task.currentRecordTitle}</strong></div> : null}
                      </div>
                      <Space>
                        <Button
                          danger
                          disabled={task.status !== 'queued' && task.status !== 'running'}
                          size="small"
                          onClick={() => void cancelExportQueueTask(task)}
                        >
                          停止任务
                        </Button>
                        <Button danger size="small" onClick={() => void removeExportQueueTask(task)}>
                          删除任务
                        </Button>
                      </Space>
                      {task.filename ? (
                        <div className="visual-queue-panel-facts">
                          <div><span>文件名</span><strong>{task.filename}</strong></div>
                        </div>
                      ) : null}
                      {task.status === 'failed' && task.errorMessage ? (
                        <div className="visual-queue-panel-error">{task.errorMessage}</div>
                      ) : null}
                    </div>
                  </details>
                );
              })}
            </div>
          ) : (
            <Empty
              description={
                totalQueueTaskCount > 0
                  ? '当前分类暂无任务'
                  : '暂无任务。请在图片管理中发布生图任务，或在链接列表中导出 Excel。'
              }
            />
          )}
        </div>
      </Modal>
      <Drawer
        className="image-manager-drawer"
        destroyOnClose={false}
        open={Boolean(imageManagerRecord)}
        title="图片管理"
        width={1280}
        onClose={() => {
          setImageEditorOpen(false);
          setImageManagerRecord(undefined);
        }}
      >
        {imageManagerRecord ? (
          <div className="image-manager-shell">
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
                          setImageManagerPreviewFocus('gallery');
                          setImageManagerSelectedSlotIds((current) =>
                            current.includes(item.slot.id)
                              ? current.filter((slotId) => slotId !== item.slot.id)
                              : [...current, item.slot.id],
                          );
                        }}
                      >
                        <span className="image-manager-preview-thumb-index">{index + 1}</span>
                        <Image
                          alt={`${imageManagerDisplayTitle} 商品图 ${index + 1}`}
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
                        alt={imageManagerDisplayedImageAlt || imageManagerDisplayTitle}
                        height="100%"
                        preview={false}
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
                      <Tag color="blue">{imageManagerRecord.skuEntries.length} SKU</Tag>
                      <Tag>{imageManagerRecord.sourceLinks.length} 货源</Tag>
                      <Tag color={imageManagerProgress && imageManagerProgress.ready >= imageManagerProgress.total ? 'green' : 'blue'}>
                        商品图 {imageManagerProgress?.ready || 0}/{imageManagerProgress?.total || 0}
                      </Tag>
                      {imageManagerProgress?.queued ? <Tag color="blue">队列 {imageManagerProgress.queued}</Tag> : null}
                      {imageManagerProgress?.running ? <Tag color="gold">生成中 {imageManagerProgress.running}</Tag> : null}
                      {imageManagerProgress?.failed ? <Tag color="red">失败 {imageManagerProgress.failed}</Tag> : null}
                    </div>
                    <Space size={8} wrap>
                      <Button icon={<PictureOutlined />} type="primary" onClick={() => setImageEditorOpen(true)}>
                        编辑图片
                      </Button>
                      <Button icon={<ClockCircleOutlined />} onClick={openUnifiedQueue}>
                        任务队列{totalQueueTaskCount > 0 ? ` ${totalQueueTaskCount}` : ''}
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
                  <Text>{imageManagerDisplayTitle.slice(0, 34)}...</Text>
                </Space>

                <Typography.Title className="temu-preview-title" level={3}>
                  {imageManagerDisplayTitle}
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
                      const skuDisplayName = getSkuEntryDisplayName(entry);
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
                            setImageManagerPreviewFocus('sku');
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
                                alt={skuDisplayName}
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
                            <span>{skuDisplayName}</span>
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
              </div>
            </div>
          </div>
        ) : null}
      </Drawer>
      <Modal
        className="image-editor-modal"
        destroyOnClose={false}
        footer={null}
        open={Boolean(imageManagerRecord) && imageEditorOpen}
        title="编辑商品图片"
        width={1240}
        onCancel={() => setImageEditorOpen(false)}
      >
        {imageManagerRecord ? (
          <div className="image-editor-shell">
            <section className="image-editor-toolbar">
              <div>
                <Text strong>图片生成</Text>
                <Text type="secondary">
                  先选择要作为图片参数的 SKU，再选择生成模式。组合出售时勾选组合内的商品 SKU。
                </Text>
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
                  type="primary"
                  disabled={!canEnqueueMainGalleryFromImageManager}
                  onClick={() => enqueueMainGalleryFromSelectedSkus(FULL_MAIN_GALLERY_IMAGE_COUNT)}
                >
                  主图全量生成 9张
                </Button>
                <Button
                  disabled={!canEnqueueMainGalleryFromImageManager}
                  onClick={() => enqueueMainGalleryFromSelectedSkus(COMPACT_MAIN_GALLERY_IMAGE_COUNT)}
                >
                  主图全量生成 4张
                </Button>
                <Button
                  disabled={!imageManagerSkuTask || imageManagerRecord.skuEntries.length === 0}
                  onClick={enqueueSkuAdaptFromSelectedSkus}
                >
                  SKU 适配
                </Button>
                <Button
                  disabled={!imageManagerProductTask || !managerActiveSlotItem?.imageUrl}
                  onClick={() => {
                    if (!imageManagerProductTask || !managerActiveSlot) return;
                    enqueueVisualTask(imageManagerRecord, imageManagerProductTask, {
                      mode: 'single_refine',
                      count: 1,
                      referenceImageUrl: managerActiveSlotItem?.imageUrl || getRecordMainImageUrl(imageManagerRecord),
                      referenceImageLabels: [`当前槽位：${getImageSlotLabel(managerActiveSlot)}`],
                      selectedSlotIds: [managerActiveSlot.id],
                      autoRun: true,
                      openQueue: false,
                    });
                  }}
                >
                  当前图精修
                </Button>
                <Button icon={<ClockCircleOutlined />} onClick={openUnifiedQueue}>
                  任务队列{totalQueueTaskCount > 0 ? ` ${totalQueueTaskCount}` : ''}
                </Button>
              </Space>
            </section>

            <div className="image-editor-grid">
              <aside className="image-editor-library">
                <div className="image-editor-panel-head">
                  <div>
                    <Text strong>统一图库</Text>
                    <Text type="secondary">批量选择图片后，加入主图或 SKU 图。</Text>
                  </div>
                  <Space className="image-editor-library-actions" size={6} wrap>
                    <Tag className="image-editor-action-count">{imageManagerSelectedAssetIds.length}/{imageManagerGalleryOptions.length} 张</Tag>
                    <Button size="small" disabled={imageManagerSelectedAssetIds.length === 0} onClick={addSelectedAssetsToProductImages}>
                      加入主图
                    </Button>
                    <Button size="small" disabled={imageManagerSelectedAssetIds.length === 0} onClick={addSelectedAssetsToSkuImages}>
                      加入 SKU 图
                    </Button>
                    <Button size="small" disabled={skuImageBindingCandidateImages.length === 0} onClick={() => openSkuImageBindingDialog()}>
                      手动绑定
                    </Button>
                    <Button size="small" disabled={imageManagerSelectedAssetIds.length === 0} onClick={() => setImageManagerSelectedAssetIds([])}>
                      清空
                    </Button>
                  </Space>
                </div>
                {imageManagerGalleryOptions.length > 0 ? (
                  <div className="image-editor-library-grid">
                    {imageManagerGalleryOptions.map((option, index) => {
                      const selected = imageManagerSelectedAssetIds.includes(option.asset.id);
                      const sourceMeta = getImageAssetSourceMeta(option.asset);
                      const sourceTone =
                        option.asset.role === 'sales-sku'
                          ? 'sku'
                          : sourceMeta.label.includes('AI') || sourceMeta.label.includes('结果')
                            ? 'generated'
                            : 'collected';
                      const sourceLabel = sourceTone === 'generated' ? '生成' : sourceTone === 'sku' ? 'SKU' : '采集';
                      const assetTitle = option.asset.alt || `图片 ${index + 1}`;
                      return (
                        <button
                          className={`image-editor-library-card ${selected ? 'is-selected' : ''}`}
                          key={option.asset.id}
                          type="button"
                          onClick={() => toggleImageManagerAsset(option.asset.id)}
                        >
                          {selected ? <span className="image-editor-library-check">✓</span> : null}
                          <Image
                            alt={assetTitle}
                            height={78}
                            preview={false}
                            referrerPolicy="no-referrer"
                            src={option.imageUrl}
                            width={112}
                          />
                          <span className="image-editor-library-info">
                            <strong title={assetTitle}>{assetTitle}</strong>
                            <span className={`image-editor-source-badge image-editor-source-${sourceTone}`}>{sourceLabel}</span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <Empty description="暂无图库图片" />
                )}
              </aside>

              <section className="image-editor-preview-panel">
                <div className="image-editor-panel-head">
                  <div>
                    <Text strong>商品预览图编辑</Text>
                    <Text type="secondary">
                      当前槽位：{getImageSlotLabel(managerActiveSlot)}，已选商品图 {imageManagerSelectedSlotIds.length} 张。
                    </Text>
                  </div>
                  <Space className="image-editor-preview-actions" size={6} wrap>
                    <Button size="small" onClick={() => setImageManagerSelectedSlotIds(imageEditorProductSlotItems.map((item) => item.slot.id))}>
                      全选主图
                    </Button>
                    <Button size="small" onClick={() => setImageManagerSelectedSlotIds([])}>
                      清空选择
                    </Button>
                    <Button
                      size="small"
                      disabled={!imageManagerProductTask || imageManagerSelectedSlotIds.length === 0}
                      onClick={() => {
                        if (!imageManagerProductTask) return;
                        enqueueVisualTask(imageManagerRecord, imageManagerProductTask, {
                          mode: 'single_refine',
                          count: imageManagerSelectedSlotIds.length,
                          referenceImageUrl: managerActiveSlotItem?.imageUrl || getRecordMainImageUrl(imageManagerRecord),
                          referenceImageLabels: imageEditorProductSlotItems
                            .filter((item) => imageManagerSelectedSlotIds.includes(item.slot.id))
                            .map((item) => `主图槽位 ${item.order}：${item.imageLabel}`),
                          selectedSlotIds: imageManagerSelectedSlotIds,
                        });
                      }}
                    >
                      批量精修
                    </Button>
                  </Space>
                </div>

                <div className="image-editor-compact-preview">
                  <section className="image-editor-mini-section">
                    <div className="image-editor-mini-head">
                      <Text strong>主图</Text>
                      <Text type="secondary">批量加入后可拖拽排序，点叉删除。</Text>
                    </div>
                    <div className="image-editor-main-thumb-grid">
                      {imageEditorProductSlotItems.map((item) => {
                        const active = managerActiveSlotItem?.slot.id === item.slot.id;
                        const selected = imageManagerSelectedSlotIds.includes(item.slot.id);
                        return (
                          <div
                            className={[
                              'image-editor-main-thumb-card',
                              active ? 'is-active' : '',
                              selected ? 'is-selected' : '',
                            ]
                              .filter(Boolean)
                              .join(' ')}
                            draggable
                            key={item.slot.id}
                            role="button"
                            tabIndex={0}
                            title="拖拽调整主图顺序"
                            onDragEnd={() => setDraggingProductSlotId(undefined)}
                            onDragOver={(event) => event.preventDefault()}
                            onDragStart={() => setDraggingProductSlotId(item.slot.id)}
                            onDrop={() => reorderProductImageFromEditor(item.slot.id)}
                            onClick={() => {
                              setManagerActiveSlotId(item.slot.id);
                              setImageManagerSelectedSlotIds((current) =>
                                current.includes(item.slot.id)
                                  ? current.filter((slotId) => slotId !== item.slot.id)
                                : [...current, item.slot.id],
                              );
                            }}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                setManagerActiveSlotId(item.slot.id);
                              }
                            }}
                          >
                            <span className="image-editor-thumb-order">{item.order}</span>
                            <button
                              aria-label={`删除图片 ${item.order}`}
                              className="image-editor-thumb-remove"
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                removeProductImageFromEditor(item.slot.id);
                              }}
                            >
                              ×
                            </button>
                            <span className="image-editor-main-thumb-image">
                              {item.imageUrl ? (
                                <Image
                                  alt={item.imageLabel}
                                  height={56}
                                  preview={false}
                                  referrerPolicy="no-referrer"
                                  src={item.imageUrl}
                                  width={56}
                                />
                              ) : (
                                <PictureOutlined />
                              )}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </section>

                  <section className="image-editor-mini-section">
                    <div className="image-editor-mini-head">
                      <Text strong>SKU 图</Text>
                      <Tag color={imageManagerSelectedSkuIds.length > 0 ? 'blue' : 'default'}>
                        已选 {imageManagerSelectedSkuIds.length}
                      </Tag>
                    </div>
                    <div className="image-editor-sku-thumb-grid">
                      {imageManagerRecord.skuEntries.map((entry) => {
                        const skuImageUrl = getSkuDisplayImageUrl(entry);
                        const skuDisplayName = getSkuEntryDisplayName(entry);
                        const active = imageManagerSelectedSkuIds.includes(entry.id);
                        return (
                          <div
                            className={active ? 'is-active' : ''}
                            draggable
                            key={entry.id}
                            role="button"
                            tabIndex={0}
                            title="拖拽调整 SKU 顺序"
                            onDragEnd={() => setDraggingSkuEntryId(undefined)}
                            onDragOver={(event) => event.preventDefault()}
                            onDragStart={() => setDraggingSkuEntryId(entry.id)}
                            onDrop={() => reorderSkuFromEditor(entry.id)}
                            onClick={() => {
                              setImageManagerActiveSkuEntryId(entry.id);
                              setImageManagerSelectedSkuIds((current) =>
                                current.includes(entry.id) ? current.filter((id) => id !== entry.id) : [...current, entry.id],
                              );
                            }}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                setImageManagerActiveSkuEntryId(entry.id);
                              }
                            }}
                          >
                            <span className="image-editor-sku-thumb-name">{skuDisplayName}</span>
                            <span className="image-editor-sku-thumb-image">
                              {skuImageUrl ? (
                                <Image
                                  alt={skuDisplayName}
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
                            <button
                              aria-label={`删除 ${skuDisplayName} 的 SKU 图`}
                              className="image-editor-thumb-remove"
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                removeSkuImageFromEditor(entry.id);
                              }}
                            >
                              ×
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </section>
                </div>
              </section>
            </div>
          </div>
        ) : null}
      </Modal>
      <Modal
        className="sku-image-binding-modal"
        open={skuImageBindingOpen}
        title="绑定 SKU 与图片参数"
        width={980}
        okText="确认绑定"
        cancelText="取消"
        onCancel={() => {
          setSkuImageBindingOpen(false);
          setSkuImageBindingTargetSkuIds([]);
          setSkuImageBindingPendingMainGalleryCount(null);
          setSkuImageBindingPendingMainGallerySkuIds(undefined);
        }}
        onOk={confirmSkuImageBindings}
      >
        {imageManagerRecord ? (
          <div className="sku-image-binding-shell">
            <Alert
              showIcon
              type="info"
              message="用于跨货源组合 SKU 或需要人工指定图片关系的情况；确认后会把绑定结果写回 SKU 和组合组件。"
            />

            <section className="sku-image-binding-selected-assets">
              <div className="sku-image-binding-section-head">
                <Text strong>已选图片参数</Text>
                <Tag>{skuImageBindingCandidateImages.length} 张</Tag>
              </div>
              <div className="sku-image-binding-asset-strip">
                {skuImageBindingCandidateImages.map((option, index) => (
                  <div className="sku-image-binding-asset" key={option.asset.id}>
                    <span className="sku-image-binding-asset-index">{index + 1}</span>
                    <Image
                      alt={option.label || option.asset.alt || `图片参数 ${index + 1}`}
                      height={58}
                      preview={false}
                      referrerPolicy="no-referrer"
                      src={option.imageUrl}
                      width={58}
                    />
                    <Text ellipsis title={`${option.sourceLabel} / ${option.label || option.asset.alt || `图片参数 ${index + 1}`}`}>
                      {option.sourceLabel} / {option.label || option.asset.alt || `图片参数 ${index + 1}`}
                    </Text>
                  </div>
                ))}
              </div>
            </section>

            <section className="sku-image-binding-list">
              {skuImageBindingSubjects.map((subject, subjectIndex) => {
                const currentUrl = getSkuImageBindingSubjectCurrentUrl(imageManagerRecord, subject);
                const subjectTitle = getSkuImageBindingSubjectTitle(
                  imageManagerRecord,
                  subject,
                  subjectIndex,
                  skuImageBindingSubjects.length,
                );
                const targetLabels = Array.from(
                  new Set(subject.targets.map((target) => getSkuImageBindingTargetLabel(imageManagerRecord, target))),
                );
                const targetShortLabels = Array.from(
                  new Set(
                    subject.targets.map((target) => getSkuImageBindingTargetShortLabel(imageManagerRecord, target)),
                  ),
                );
                const splitSubject = isSkuImageBindingSplitSubject(subject);
                const renderChoiceGrid = (choiceKey: string) => {
                  const selectedAssetId = skuImageBindingChoices[choiceKey];
                  return (
                    <div className="sku-image-binding-choice-grid">
                      <button
                        className={`sku-image-binding-choice ${selectedAssetId ? '' : 'is-active'}`}
                        type="button"
                        onClick={() =>
                          setSkuImageBindingChoices((current) => ({
                            ...current,
                            [choiceKey]: undefined,
                          }))
                        }
                      >
                        <span className="sku-image-binding-no-image">不绑定</span>
                        <Text type="secondary">保留现状</Text>
                      </button>
                      {skuImageBindingCandidateImages.map((option, index) => {
                        const active = selectedAssetId === option.asset.id;
                        return (
                          <button
                            className={`sku-image-binding-choice ${active ? 'is-active' : ''}`}
                            key={option.asset.id}
                            type="button"
                            onClick={() =>
                              setSkuImageBindingChoices((current) => ({
                                ...current,
                                [choiceKey]: option.asset.id,
                              }))
                            }
                          >
                            <span className="sku-image-binding-choice-index">{index + 1}</span>
                            <Image
                              alt={option.label || option.asset.alt || `图片参数 ${index + 1}`}
                              height={54}
                              preview={false}
                              referrerPolicy="no-referrer"
                              src={option.imageUrl}
                              width={54}
                            />
                          </button>
                        );
                      })}
                    </div>
                  );
                };
                return (
                  <div className="sku-image-binding-row" key={subject.key}>
                    <div className="sku-image-binding-target">
                      <Space className="sku-image-binding-index-tags" size={[6, 6]} wrap>
                        <Tag color="blue">{subjectTitle.indexLabel}</Tag>
                        <Tag color="geekblue">{subjectTitle.skuLabel}</Tag>
                      </Space>
                      <div className="sku-image-binding-target-title">
                        {currentUrl ? (
                          <Image
                            alt={`${subjectTitle.title} 当前图`}
                            height={42}
                            preview={false}
                            referrerPolicy="no-referrer"
                            src={currentUrl}
                            width={42}
                          />
                        ) : (
                          <span className="sku-image-binding-empty-thumb">空</span>
                        )}
                        <div>
                          <Text strong className="sku-image-binding-subject-name" title={subjectTitle.title}>
                            {subjectTitle.title}
                          </Text>
                          <Text className="sku-image-binding-subject-meta" type="secondary">
                            确认后会同步写回：{targetShortLabels.join('、')}
                          </Text>
                        </div>
                      </div>
                      <Space className="sku-image-binding-target-tags" size={[6, 6]} wrap>
                        {targetLabels.slice(0, 4).map((label) => (
                          <Tag className="sku-image-binding-target-tag" key={label} title={label}>
                            {label}
                          </Tag>
                        ))}
                        {targetLabels.length > 4 ? <Tag>+{targetLabels.length - 4}</Tag> : null}
                      </Space>
                    </div>

                    {splitSubject ? (
                      <div className="sku-image-binding-component-stack">
                        {subject.targets.map((target) => (
                          <div className="sku-image-binding-component-row" key={target.key}>
                            <div className="sku-image-binding-component-head">
                              <Tag color="cyan">{getSkuImageBindingTargetShortLabel(imageManagerRecord, target)}</Tag>
                              <Text ellipsis title={target.componentName}>
                                {target.componentName}
                              </Text>
                            </div>
                            {renderChoiceGrid(target.key)}
                          </div>
                        ))}
                      </div>
                    ) : (
                      renderChoiceGrid(subject.key)
                    )}
                  </div>
                );
              })}
            </section>
          </div>
        ) : null}
      </Modal>
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
    fetchProductCategories('all')
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

  const recordProductToPool = async (product: Product) => {
    setAddingToPool(true);
    try {
      const result = await addProductsToPool([product.id]);
      setSelectedRowKeys((keys) => keys.filter((key) => key !== product.id));
      await Promise.all([loadDataDeskProducts(page, pageSize, filters), loadDataDeskStats()]);
      onProductsAddedToPool();
      message.success(result.added_count > 0 ? '已录入商品池' : '商品已在商品池中');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '录入商品池失败');
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
            <CategoryCascaderFilterV2 categories={categories} />
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
          onRecord={recordProductToPool}
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
  const [form] = Form.useForm<ProductPoolFilters>();
  const [products, setProducts] = useState<Product[]>(mockProducts);
  const [productTotal, setProductTotal] = useState(mockProducts.length);
  const [backendReady, setBackendReady] = useState(false);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);
  const [filters, setFilters] = useState<ProductPoolFilters>(defaultProductPoolFilters);
  const [priceSortOrder, setPriceSortOrder] = useState<SortOrder>();
  const [gmvSortOrder, setGmvSortOrder] = useState<SortOrder>();
  const [importOpen, setImportOpen] = useState(false);
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
        const requestFilters = getProductPoolRequestFilters(nextFilters);
        const response = await fetchProducts({
          page: nextPage,
          pageSize: nextPageSize,
          sortBy: nextPriceSortOrder ? 'price' : nextGmvSortOrder ? 'gmv' : undefined,
          sortOrder: toBackendPriceSortOrder(nextPriceSortOrder || nextGmvSortOrder),
          ...requestFilters,
        });
        setProducts(response.items.map(mapBackendProduct));
        setProductTotal(response.total);
        setBackendReady(true);
      } catch {
        setBackendReady(false);
        const fallbackProducts = mockProducts.filter((product) => {
          if (
            nextFilters.keyword &&
            !product.title.toLowerCase().includes(nextFilters.keyword.toLowerCase()) &&
            !(product.titleEn || '').toLowerCase().includes(nextFilters.keyword.toLowerCase()) &&
            !product.id.toLowerCase().includes(nextFilters.keyword.toLowerCase())
          ) {
            return false;
          }
          if (!matchesProductPoolDateRange(product, nextFilters.selectedDateRange)) return false;
          if (!matchesRange(product.price, nextFilters.priceRange)) return false;
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

  const warnLinkPersistenceFailure = useCallback((error: unknown) => {
    console.error(error);
    message.warning('链接列表已先保存在本地，后端持久化失败，请确认后端已启动');
  }, []);

  useEffect(() => {
    if (isAdminUser) return;
    void loadProducts(1, pageSize, filters);
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

  const deleteLinkEntries = useCallback((recordIds: string[]) => {
    const uniqueIds = Array.from(new Set(recordIds)).filter(Boolean);
    if (uniqueIds.length === 0) return;

    const deletingIdSet = new Set(uniqueIds);
    setLinkListRecords((current) => {
      const next = current.filter((record) => !deletingIdSet.has(record.id));
      writeLinkListRecords(next, currentUser.id);
      return next;
    });
    void Promise.allSettled(uniqueIds.map((recordId) => deleteLinkListRecord(recordId))).then((results) => {
      const failedCount = results.filter((result) => result.status === 'rejected').length;
      if (failedCount > 0) {
        warnLinkPersistenceFailure(new Error(`${failedCount} 条链接记录后端删除失败`));
      }
    });
    message.success(uniqueIds.length === 1 ? '已删除链接记录' : `已删除 ${uniqueIds.length} 条链接记录`);
  }, [currentUser.id, warnLinkPersistenceFailure]);

  const deleteLinkEntry = useCallback((recordId: string) => {
    deleteLinkEntries([recordId]);
  }, [deleteLinkEntries]);

  const updateLinkEntry = useCallback((record: LinkListRecord) => {
    setLinkListRecords((current) => {
      const next = current.map((item) => (item.id === record.id ? record : item));
      writeLinkListRecords(next, currentUser.id);
      return next;
    });
    void saveLinkListRecord(record).catch(warnLinkPersistenceFailure);
  }, [currentUser.id, warnLinkPersistenceFailure]);

  const enrichRecordsWithProductCategory = useCallback(
    (records: LinkListRecord[]) => {
      const productById = new Map(products.map((product) => [product.id, product]));
      let changed = false;
      const enriched = records.map((record) => {
        const product = productById.get(record.productId);
        if (!product) return record;
        const categoryPath = record.categoryPath || product.categoryPath || product.category;
        const category = record.category || product.category || categoryPath;
        const categoryLevel1 = record.categoryLevel1 || product.categoryLevel1;
        const categoryLevel2 = record.categoryLevel2 || product.categoryLevel2;
        if (
          category === record.category &&
          categoryPath === record.categoryPath &&
          categoryLevel1 === record.categoryLevel1 &&
          categoryLevel2 === record.categoryLevel2
        ) {
          return record;
        }
        changed = true;
        return {
          ...record,
          category,
          categoryPath,
          categoryLevel1,
          categoryLevel2,
        };
      });
      return changed ? enriched : records;
    },
    [products],
  );

  const exportTemplate = useCallback(async (targetRecords?: LinkListRecord[]) => {
    const requestedRecords = targetRecords && targetRecords.length > 0 ? targetRecords : linkListRecords;
    if (requestedRecords.length === 0) {
      message.warning('请先在商品池中录入链接列表，再导出 Excel');
      return;
    }

    if (exportingTemplate) {
      message.info('Excel 正在后台生成，可以继续选品');
      return;
    }

    setExportingTemplate(true);
    message.open({
      key: EXPORT_TEMPLATE_MESSAGE_KEY,
      type: 'loading',
      content: 'Excel 正在后台生成，可以继续选品',
      duration: 0,
    });
    try {
      let recordsForExport = requestedRecords;
      let shouldPersistRecordsForExport = false;
      try {
        const syncResult = await syncPluginCreativeJobs(requestedRecords);
        recordsForExport = syncResult.records.length > 0 ? syncResult.records : requestedRecords;
        if (syncResult.records.length > 0) {
          shouldPersistRecordsForExport = true;
        }
      } catch {
        message.warning('插件旧任务同步失败，已跳过同步并继续使用当前链接列表数据导出');
      }

      const enrichedRecordsForExport = enrichRecordsWithProductCategory(recordsForExport);
      if (enrichedRecordsForExport !== recordsForExport) {
        shouldPersistRecordsForExport = true;
      }
      recordsForExport = enrichedRecordsForExport;
      if (shouldPersistRecordsForExport) {
        const updatedById = new Map(recordsForExport.map((record) => [record.id, record]));
        const nextLinkListRecords = linkListRecords.map((record) => updatedById.get(record.id) || record);
        setLinkListRecords(nextLinkListRecords);
        writeLinkListRecords(nextLinkListRecords, currentUser.id);
        void saveLinkListRecords(nextLinkListRecords).catch(warnLinkPersistenceFailure);
      }

      const task = await createDianxiaomiExportTask(recordsForExport);
      message.open({
        key: EXPORT_TEMPLATE_MESSAGE_KEY,
        type: 'success',
        content: `导出任务已加入队列：${task.recordCount} 个商品链接`,
        duration: 3,
      });
      return task;
    } catch (error) {
      message.open({
        key: EXPORT_TEMPLATE_MESSAGE_KEY,
        type: 'error',
        content: error instanceof Error ? error.message : 'Excel 导出失败',
        duration: 5,
      });
    } finally {
      setExportingTemplate(false);
    }
  }, [currentUser.id, enrichRecordsWithProductCategory, exportingTemplate, linkListRecords, warnLinkPersistenceFailure]);

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
      .then(() => {
        if (activeProduct?.id === product.id) closeProduct();
        message.success('商品已删除');
      })
      .catch((error) => message.error(error.message || '删除失败'));
  };

  const deleteSelectedProducts = () => {
    const productIds = selectedRowKeys.map(String).filter(Boolean);
    if (productIds.length === 0) {
      message.warning('请先选择要删除的商品');
      return;
    }

    Modal.confirm({
      title: `确认删除选中的 ${productIds.length} 个商品？`,
      content: '删除后会从当前商品池中移除，不影响数据台原始商品库。',
      okText: '批量删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      async onOk() {
        const deletingIdSet = new Set(productIds);
        if (!backendReady) {
          setProducts((current) => current.filter((product) => !deletingIdSet.has(product.id)));
          setProductTotal((current) => Math.max(0, current - deletingIdSet.size));
          setSelectedRowKeys([]);
          if (activeProduct && deletingIdSet.has(activeProduct.id)) closeProduct();
          message.success(`已删除 ${deletingIdSet.size} 个商品`);
          return;
        }

        const results = await Promise.allSettled(productIds.map((productId) => deleteBackendProduct(productId)));
        const failedCount = results.filter((result) => result.status === 'rejected').length;
        setSelectedRowKeys([]);
        await loadProducts(currentPage, pageSize, filters);
        if (activeProduct && deletingIdSet.has(activeProduct.id)) closeProduct();
        if (failedCount > 0) {
          message.error(`批量删除完成，但有 ${failedCount} 个商品删除失败`);
          return;
        }
        message.success(`已删除 ${productIds.length} 个商品`);
      },
    });
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
    form.setFieldsValue(defaultProductPoolFilters);
    setFilters(defaultProductPoolFilters);
    setCurrentPage(1);
    void loadProducts(1, pageSize, defaultProductPoolFilters);
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
              onDeleteMany={deleteLinkEntries}
              onExportRecords={exportTemplate}
              onUpdate={updateLinkEntry}
              exporting={exportingTemplate}
            />
          ) : activeWorkbenchTab === 'admin' ? (
            <AdminPage />
          ) : activeWorkbenchTab === 'data' ? (
            <DataDeskPanel
              onProductsAddedToPool={() => {
                void loadProducts(currentPage, pageSize, filters);
              }}
              onViewProduct={(product) => openProduct(product, { drawerMode: 'sales', syncUrl: false })}
            />
          ) : (
            <>
          <Card className="filter-card" title="筛选器">
            <Form
              form={form}
              layout="inline"
              onFinish={(values) => {
                setFilters(values);
                setCurrentPage(1);
                void loadProducts(1, pageSize, values);
              }}
              initialValues={defaultProductPoolFilters}
            >
              <Form.Item label="关键词" name="keyword">
                <Input allowClear placeholder="搜索商品标题 / ID" />
              </Form.Item>
              <Form.Item label="时间范围" name="selectedDateRange">
                <RangePicker allowClear format="YYYY-MM-DD" />
              </Form.Item>
              <Form.Item label="价格区间" name="priceRange">
                <Input allowClear placeholder="¥0 - ¥999" />
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
            extra={
              <Button
                danger
                disabled={selectedRowKeys.length === 0}
                onClick={deleteSelectedProducts}
              >
                批量删除
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
              hideGmvColumn
              dateColumnTitle="选入时间"
              dateMetaLabel="选入"
              getDateValue={(product) => product.selectedAt || product.listedAt}
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
          const result = await uploadDianxiaomiTemplateFile(file);
          setImportOpen(false);

          const importedRecords = result.records || [];
          if (importedRecords.length > 0) {
            setLinkListRecords((current) => {
              const importedIdSet = new Set(importedRecords.map((record) => record.id));
              const next = [
                ...importedRecords,
                ...current.filter((record) => !importedIdSet.has(record.id)),
              ].slice(0, 200);
              writeLinkListRecords(next, currentUser.id);
              return next;
            });
          }

          message.success(`导入完成：${result.imported_count} 个商品，${importedRecords.length} 条 SKU 回显记录`);
          setCurrentPage(1);
          await loadProducts(1, pageSize, filters);
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

    </Layout>
  );
}
