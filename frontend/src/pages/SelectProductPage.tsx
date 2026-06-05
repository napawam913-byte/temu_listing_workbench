import {
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Image,
  Input,
  InputNumber,
  Layout,
  Modal,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
  message,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Key } from 'react';
import {
  addProductsToPool,
  deleteProduct as deleteBackendProduct,
  deleteLinkListRecord,
  createPluginCreativeJobs,
  exportDianxiaomiTemuTemplate,
  fetchLinkListRecords,
  fetchProductStats,
  fetchProducts,
  mapBackendProduct,
  saveLinkListRecord,
  saveLinkListRecords,
  syncPluginCreativeJobs,
  upload1688Links,
  uploadYunqiFile,
} from '../api/backendApi';
import type { ProductStats } from '../api/backendApi';
import { DataImportModal } from '../components/DataImportModal';
import { ProductDetailDrawer } from '../components/ProductDetailDrawer';
import { ProductTable } from '../components/ProductTable';
import { mockProducts } from '../mock/products';
import type { LinkListImageAsset, LinkListImageSlot, LinkListRecord } from '../types/linkList';
import type { Product, ProductSourceType, SourcingCandidate } from '../types/product';

const { Header, Content } = Layout;
const { Text } = Typography;

type Filters = {
  keyword?: string;
  period?: Product['period'] | '全部';
  priceRange?: string;
  salesRange?: string;
  gmvRange?: string;
};

const defaultFilters: Filters = {
  period: '全部',
};

const PRODUCT_ROUTE_PREFIX = '#/products/';

type ProductRoute = {
  sourceType: ProductSourceType;
  sourceProductId: string;
};

type WorkbenchTab = 'sourcing' | 'data' | 'links' | 'automation';

type AutomationTemplate = {
  id: string;
  name: string;
  siteName: string;
  warehouseNames: string[];
  freightTemplateName: string;
  promisedShipDays: string;
  imageRootDir: string;
  batchProductCount: number;
  createTimestampFolder: boolean;
  remark?: string;
  updatedAt: string;
};

const LINK_LIST_STORAGE_KEY = 'temuListingWorkbenchLinkListRecords';
const AUTOMATION_TEMPLATE_STORAGE_KEY = 'temuListingWorkbenchAutomationTemplates';
const CURATED_EXPORT_IMAGE_COUNT = 8;
const MAX_EXPORT_CAROUSEL_IMAGE_COUNT = 10;

function createDefaultAutomationTemplate(): AutomationTemplate {
  return {
    id: `automation-template-${Date.now()}`,
    name: '默认上架模板',
    siteName: '美国站',
    warehouseNames: ['美中仓库'],
    freightTemplateName: '默认',
    promisedShipDays: '',
    imageRootDir: 'C:/Users/AA/Desktop/新建文件夹',
    batchProductCount: 1,
    createTimestampFolder: true,
    remark: 'Excel 导入店小秘后，由机器人按此参数轮询检查并补全站点配置。',
    updatedAt: new Date().toISOString(),
  };
}

function readAutomationTemplates(): AutomationTemplate[] {
  try {
    const value = JSON.parse(localStorage.getItem(AUTOMATION_TEMPLATE_STORAGE_KEY) || '[]');
    if (Array.isArray(value) && value.length > 0) return value;
  } catch {
    // Ignore localStorage corruption and rebuild a usable default template.
  }
  return [createDefaultAutomationTemplate()];
}

function writeAutomationTemplates(templates: AutomationTemplate[]) {
  localStorage.setItem(AUTOMATION_TEMPLATE_STORAGE_KEY, JSON.stringify(templates));
}

function readLinkListRecords(): LinkListRecord[] {
  try {
    const value = JSON.parse(localStorage.getItem(LINK_LIST_STORAGE_KEY) || '[]');
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function writeLinkListRecords(records: LinkListRecord[]) {
  localStorage.setItem(LINK_LIST_STORAGE_KEY, JSON.stringify(records));
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
  const mainSlotUrl = mainSlot?.assetId ? getAssetDisplayUrl(getRecordAssetMap(record).get(mainSlot.assetId)) : undefined;
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
  const assets = collectRecordImageAssets(record);
  const mainAsset =
    (record.mainImage?.id ? assets.find((asset) => asset.id === record.mainImage?.id) : undefined) ||
    assets.find((asset) => asset.role === 'product-main') ||
    assets.find((asset) => asset.role === 'product-material') ||
    assets[0];
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
      const imageUrl = getAssetDisplayUrl(asset);
      return imageUrl ? { slot, asset, imageUrl } : undefined;
    })
    .filter((item): item is { slot: LinkListImageSlot; asset: LinkListImageAsset | undefined; imageUrl: string } => {
      if (!item || seenUrls.has(item.imageUrl)) return false;
      seenUrls.add(item.imageUrl);
      return true;
    });
}

function getImageAssetOptions(record?: LinkListRecord) {
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
  if (status === 'done') return '已统一';
  if (status === 'failed') return '生成失败';
  return '待修图';
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
  const [imageSlotPickerOpen, setImageSlotPickerOpen] = useState(false);
  const [generatingRecordId, setGeneratingRecordId] = useState<string>();
  const [syncingRecordId, setSyncingRecordId] = useState<string>();
  const [syncingAll, setSyncingAll] = useState(false);
  const previewGalleryItems = useMemo(() => getRecordPreviewGalleryItems(previewRecord), [previewRecord]);
  const previewImageAssetOptions = useMemo(() => getImageAssetOptions(previewRecord), [previewRecord]);
  const previewActiveGalleryItem =
    previewGalleryItems.find((item) => item.slot.id === previewActiveImageSlotId) || previewGalleryItems[0];
  const previewDisplayedImageUrl = previewActiveGalleryItem?.imageUrl || getRecordMainImageUrl(previewRecord);
  const previewActiveSlot = previewActiveGalleryItem?.slot;
  const activePreviewSkuEntry =
    previewRecord?.skuEntries.find((entry) => entry.id === previewActiveSkuEntryId) || previewRecord?.skuEntries[0];
  const previewPriceText = formatPreviewPrice(previewRecord);
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
    },
    [onUpdate],
  );

  const generateRecordCreative = async (record: LinkListRecord) => {
    setGeneratingRecordId(record.id);
    try {
      await createPluginCreativeJobs([record]);
      const synced = await syncPluginCreativeJobs([record]);
      const nextRecord = synced.records[0] || record;
      applySyncedRecords([nextRecord]);
      setPreviewRecord((current) => (current?.id === record.id ? nextRecord : current));
      message.success('已创建插件生图任务，请在插件侧边栏处理');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '插件生图任务创建失败');
    } finally {
      setGeneratingRecordId(undefined);
    }
  };

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

  const replacePreviewImageSlot = (assetId: string) => {
    if (!previewRecord || !previewActiveSlot) return;
    const nextRecord = updateRecordImageSlot(previewRecord, previewActiveSlot.id, assetId);
    onUpdate(nextRecord);
    setPreviewRecord(nextRecord);
    setPreviewActiveImageSlotId(previewActiveSlot.id);
    setImageSlotPickerOpen(false);
    message.success('已替换当前图片');
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
                插件生图完成后会自动同步并回显到这里
              </Text>
            </div>
            <Button loading={syncingAll} onClick={() => void syncAllCreative(false)}>
              同步生成结果
            </Button>
          </div>
          <div className="link-list">
            {records.map((record) => {
              const jobSummary = getCreativeJobSummary(record);
              return (
            <Card
              className="link-record-card"
              hoverable
              key={record.id}
              tabIndex={0}
              onClick={() => setPreviewRecord(record)}
              onKeyDown={(event) => {
                if (event.key !== 'Enter' && event.key !== ' ') return;
                event.preventDefault();
                setPreviewRecord(record);
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
                      {record.styleProfile ? <Tag color="purple">{record.styleProfile.provider === 'comfyui' ? 'ComfyUI' : 'ChatGPT'}</Tag> : null}
                      {jobSummary.total > 0 ? (
                        <Tag color={jobSummary.completed >= CURATED_EXPORT_IMAGE_COUNT ? 'green' : 'gold'}>
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

                <Button
                  loading={generatingRecordId === record.id}
                  size="small"
                  type="primary"
                  onClick={(event) => {
                    event.stopPropagation();
                    void generateRecordCreative(record);
                  }}
                >
                  创建插件任务
                </Button>

                <Button
                  loading={syncingRecordId === record.id}
                  size="small"
                  onClick={(event) => {
                    event.stopPropagation();
                    void syncRecordCreative(record);
                  }}
                >
                  同步结果
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
                    <Button
                      disabled={!previewActiveSlot || previewImageAssetOptions.length === 0}
                      size="small"
                      onClick={() => setImageSlotPickerOpen(true)}
                    >
                      替换当前图
                    </Button>
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
        footer={null}
        open={imageSlotPickerOpen}
        title={`替换${getImageSlotLabel(previewActiveSlot)}`}
        width={760}
        onCancel={() => setImageSlotPickerOpen(false)}
      >
        {previewImageAssetOptions.length > 0 ? (
          <div className="link-image-slot-picker">
            {previewImageAssetOptions.map((option, index) => {
              const active = option.asset.id === previewActiveSlot?.assetId;
              return (
                <button
                  className={`link-image-slot-option ${active ? 'link-image-slot-option-active' : ''}`}
                  key={option.asset.id}
                  type="button"
                  onClick={() => replacePreviewImageSlot(option.asset.id)}
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
  const [loading, setLoading] = useState(false);
  const [addingToPool, setAddingToPool] = useState(false);

  const loadDataDeskProducts = useCallback(
    async (nextPage = page, nextPageSize = pageSize, nextFilters: Filters | string = filters) => {
      const normalizedFilters = typeof nextFilters === 'string' ? { keyword: nextFilters } : nextFilters;
      setLoading(true);
      try {
        const response = await fetchProducts({
          page: nextPage,
          pageSize: nextPageSize,
          scope: 'all',
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
    [filters, page, pageSize],
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

function AutomationTemplatePanel({ records }: { records: LinkListRecord[] }) {
  const [templates, setTemplates] = useState<AutomationTemplate[]>(() => readAutomationTemplates());
  const [activeTemplateId, setActiveTemplateId] = useState(() => readAutomationTemplates()[0]?.id || '');
  const activeTemplate = templates.find((template) => template.id === activeTemplateId) || templates[0];
  const robotPayload = useMemo(
    () => ({
      schemaVersion: 1,
      source: 'temu_listing_workbench',
      generatedAt: new Date().toISOString(),
      template: activeTemplate,
      batch: {
        linkRecordCount: records.length,
        skuCount: records.reduce((total, record) => total + record.skuEntries.length, 0),
        recordIds: records.map((record) => record.id),
      },
      workflow: {
        stage: 'after_dianxiaomi_excel_import',
        action: 'poll_and_fill_site_parameters',
        robotLinked: false,
      },
    }),
    [activeTemplate, records],
  );

  const persistTemplates = (nextTemplates: AutomationTemplate[]) => {
    setTemplates(nextTemplates);
    writeAutomationTemplates(nextTemplates);
  };

  const updateActiveTemplate = (patch: Partial<AutomationTemplate>) => {
    if (!activeTemplate) return;
    const nextTemplates = templates.map((template) =>
      template.id === activeTemplate.id
        ? {
            ...template,
            ...patch,
            updatedAt: new Date().toISOString(),
          }
        : template,
    );
    persistTemplates(nextTemplates);
  };

  const addTemplate = () => {
    const nextTemplate = {
      ...createDefaultAutomationTemplate(),
      id: `automation-template-${Date.now()}`,
      name: `上架模板 ${templates.length + 1}`,
    };
    const nextTemplates = [...templates, nextTemplate];
    persistTemplates(nextTemplates);
    setActiveTemplateId(nextTemplate.id);
  };

  const deleteTemplate = () => {
    if (!activeTemplate || templates.length <= 1) {
      message.warning('至少保留一个自动化模板');
      return;
    }
    const nextTemplates = templates.filter((template) => template.id !== activeTemplate.id);
    persistTemplates(nextTemplates);
    setActiveTemplateId(nextTemplates[0]?.id || '');
  };

  const copyPayload = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(robotPayload, null, 2));
      message.success('机器人参数 JSON 已复制');
    } catch {
      message.error('复制失败，请手动复制右侧 JSON');
    }
  };

  if (!activeTemplate) {
    return (
      <Card>
        <Empty description="暂无自动化模板">
          <Button type="primary" onClick={addTemplate}>
            新建模板
          </Button>
        </Empty>
      </Card>
    );
  }

  return (
    <div className="automation-page">
      <div className="automation-hero">
        <div>
          <Typography.Title level={3}>店小秘自动化参数模板</Typography.Title>
          <Text type="secondary">
            先把不同站点的仓库、运费模板、承诺发货等参数沉淀成模板。当前阶段只在前端保存，后续再把 JSON 交给机器人执行。
          </Text>
        </div>
        <Space>
          <Button onClick={addTemplate}>新建模板</Button>
          <Button danger onClick={deleteTemplate}>
            删除当前模板
          </Button>
          <Button type="primary" onClick={copyPayload}>
            复制机器人参数
          </Button>
        </Space>
      </div>

      <div className="automation-summary-grid">
        <Card className="automation-summary-card">
          <Statistic title="参数模板" value={templates.length} />
        </Card>
        <Card className="automation-summary-card">
          <Statistic title="待上架链接" value={records.length} />
        </Card>
        <Card className="automation-summary-card">
          <Statistic title="销售 SKU" value={records.reduce((total, record) => total + record.skuEntries.length, 0)} />
        </Card>
      </div>

      <div className="automation-layout">
        <Card
          className="automation-card"
          title={
            <Space>
              <span>模板编辑</span>
              <Tag color="blue">{activeTemplate.siteName || '未设置站点'}</Tag>
            </Space>
          }
        >
          <Space direction="vertical" size={14} className="automation-form">
            <label className="automation-field">
              <Text strong>选择模板</Text>
              <Select
                value={activeTemplate.id}
                options={templates.map((template) => ({ value: template.id, label: template.name }))}
                onChange={setActiveTemplateId}
              />
            </label>
            <label className="automation-field">
              <Text strong>模板名称</Text>
              <Input value={activeTemplate.name} onChange={(event) => updateActiveTemplate({ name: event.target.value })} />
            </label>
            <label className="automation-field">
              <Text strong>站点</Text>
              <Input
                placeholder="例如：美国站 / 欧洲站 / 加拿大站"
                value={activeTemplate.siteName}
                onChange={(event) => updateActiveTemplate({ siteName: event.target.value })}
              />
            </label>
            <label className="automation-field">
              <Text strong>仓库</Text>
              <Select
                mode="tags"
                placeholder="可输入多个仓库，回车确认"
                value={activeTemplate.warehouseNames}
                options={[
                  { value: '美中仓库', label: '美中仓库' },
                  { value: '美西仓库', label: '美西仓库' },
                  { value: '美东仓库', label: '美东仓库' },
                  { value: '美南仓库', label: '美南仓库' },
                ]}
                onChange={(warehouseNames) => updateActiveTemplate({ warehouseNames })}
              />
            </label>
            <label className="automation-field">
              <Text strong>运费模板</Text>
              <Input
                placeholder="例如：默认 / 标准运费 / 美区包邮模板"
                value={activeTemplate.freightTemplateName}
                onChange={(event) => updateActiveTemplate({ freightTemplateName: event.target.value })}
              />
            </label>
            <div className="automation-field-row">
              <label className="automation-field">
                <Text strong>承诺发货</Text>
                <Input
                  placeholder="置空表示不填"
                  suffix="工作日内发货"
                  value={activeTemplate.promisedShipDays}
                  onChange={(event) => updateActiveTemplate({ promisedShipDays: event.target.value })}
                />
              </label>
              <label className="automation-field">
                <Text strong>每轮商品数</Text>
                <InputNumber
                  min={1}
                  max={200}
                  value={activeTemplate.batchProductCount}
                  onChange={(value) => updateActiveTemplate({ batchProductCount: Number(value) || 1 })}
                />
              </label>
            </div>
            <label className="automation-field">
              <Text strong>图片根目录</Text>
              <Input
                placeholder="机器人下载/上传图片时使用的本地目录"
                value={activeTemplate.imageRootDir}
                onChange={(event) => updateActiveTemplate({ imageRootDir: event.target.value })}
              />
            </label>
            <Checkbox
              checked={activeTemplate.createTimestampFolder}
              onChange={(event) => updateActiveTemplate({ createTimestampFolder: event.target.checked })}
            >
              每次自动新建时间戳子文件夹，避免混入旧图
            </Checkbox>
            <label className="automation-field">
              <Text strong>备注</Text>
              <Input.TextArea
                autoSize={{ minRows: 3, maxRows: 5 }}
                value={activeTemplate.remark}
                onChange={(event) => updateActiveTemplate({ remark: event.target.value })}
              />
            </label>
          </Space>
        </Card>

        <Card className="automation-card" title="机器人参数预览">
          <div className="automation-flow">
            <div>
              <Tag color="default">1</Tag>
              <Text>导出店小秘 Excel</Text>
            </div>
            <div>
              <Tag color="blue">2</Tag>
              <Text>店小秘导入待发布</Text>
            </div>
            <div>
              <Tag color="green">3</Tag>
              <Text>机器人轮询检查并补全参数</Text>
            </div>
          </div>
          <pre className="automation-json">{JSON.stringify(robotPayload, null, 2)}</pre>
        </Card>
      </div>
    </div>
  );
}

export function SelectProductPage() {
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
  const [importOpen, setImportOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportingTemplate, setExportingTemplate] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMode, setDrawerMode] = useState<'sourcing' | 'sales'>('sourcing');
  const [activeProduct, setActiveProduct] = useState<Product | undefined>();
  const [sourcingSearched, setSourcingSearched] = useState(false);
  const [activeCandidate, setActiveCandidate] = useState<SourcingCandidate | undefined>();
  const [activeTab, setActiveTab] = useState<'search' | 'detail'>('search');
  const [activeWorkbenchTab, setActiveWorkbenchTab] = useState<WorkbenchTab>('sourcing');
  const [linkListRecords, setLinkListRecords] = useState<LinkListRecord[]>(() => readLinkListRecords());

  const loadProducts = useCallback(
    async (nextPage = currentPage, nextPageSize = pageSize, nextFilters = filters) => {
      setLoadingProducts(true);
      try {
        const response = await fetchProducts({
          page: nextPage,
          pageSize: nextPageSize,
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
        setProducts(fallbackProducts.slice((nextPage - 1) * nextPageSize, nextPage * nextPageSize));
        setProductTotal(fallbackProducts.length);
      } finally {
        setLoadingProducts(false);
      }
    },
    [currentPage, filters, pageSize],
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
    void loadProducts(1, pageSize, filters);
    void loadStats();
    setCurrentPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let active = true;

    const loadLinkRecords = async () => {
      const localRecords = readLinkListRecords();
      try {
        const backendRecords = await fetchLinkListRecords();
        if (!active) return;

        if (backendRecords.length > 0 || localRecords.length === 0) {
          setLinkListRecords(backendRecords);
          writeLinkListRecords(backendRecords);
          return;
        }

        await saveLinkListRecords(localRecords);
        if (!active) return;
        setLinkListRecords(localRecords);
        writeLinkListRecords(localRecords);
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
  }, []);

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
        writeLinkListRecords(next);
        return next;
      });
      void saveLinkListRecord(record).catch(warnLinkPersistenceFailure);
      closeProduct();
      setActiveWorkbenchTab('links');
      message.success('已录入链接列表');
    },
    [closeProduct, warnLinkPersistenceFailure],
  );

  const deleteLinkEntry = useCallback((recordId: string) => {
    setLinkListRecords((current) => {
      const next = current.filter((record) => record.id !== recordId);
      writeLinkListRecords(next);
      return next;
    });
    void deleteLinkListRecord(recordId).catch(warnLinkPersistenceFailure);
    message.success('已删除链接记录');
  }, [warnLinkPersistenceFailure]);

  const updateLinkEntry = useCallback((record: LinkListRecord) => {
    setLinkListRecords((current) => {
      const next = current.map((item) => (item.id === record.id ? record : item));
      writeLinkListRecords(next);
      return next;
    });
    void saveLinkListRecord(record).catch(warnLinkPersistenceFailure);
  }, [warnLinkPersistenceFailure]);

  const exportTemplate = useCallback(async () => {
    if (linkListRecords.length === 0) {
      message.warning('请先在商品池中录入链接列表，再导出店小秘模板');
      return;
    }

    setExportingTemplate(true);
    try {
      const syncResult = await syncPluginCreativeJobs(linkListRecords);
      const recordsForExport = syncResult.records;
      if (syncResult.records.length > 0) {
        setLinkListRecords(syncResult.records);
        writeLinkListRecords(syncResult.records);
        void saveLinkListRecords(syncResult.records).catch(warnLinkPersistenceFailure);
      }

      const blob = await exportDianxiaomiTemuTemplate(recordsForExport);
      downloadBlob(blob, `店小秘_TEMU半托管_${new Date().toISOString().slice(0, 10)}.xlsx`);
      setExportOpen(false);
      message.success('店小秘 TEMU 半托管模板已生成');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '模板导出失败');
    } finally {
      setExportingTemplate(false);
    }
  }, [linkListRecords, warnLinkPersistenceFailure]);

  const openProductFromRoute = useCallback(async () => {
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
  }, [openProduct, pageSize, products]);

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
    <Layout className="app-layout">
      <Header className="app-header">
        <div className="app-header-inner">
          <div className="brand">Temu 选品上架工作台</div>
          <nav aria-label="主导航" className="main-nav">
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
            <button
              className={`main-nav-item ${activeWorkbenchTab === 'automation' ? 'main-nav-active' : ''}`}
              type="button"
              onClick={() => setActiveWorkbenchTab('automation')}
            >
              自动化模板
            </button>
          </nav>
          <Space className="header-actions">
            <span className="batch-pill">当前批次：云启 0522</span>
            <Button className="header-button" type="primary" onClick={() => setImportOpen(true)}>
              数据导入
            </Button>
            <Button className="header-button" onClick={() => setExportOpen(true)}>
              清单导出
            </Button>
          </Space>
        </div>
      </Header>

      <Content className="page-content">
        <div className="page-shell">
          {activeWorkbenchTab === 'links' ? (
            <LinkListPanel records={linkListRecords} onDelete={deleteLinkEntry} onUpdate={updateLinkEntry} />
          ) : activeWorkbenchTab === 'automation' ? (
            <AutomationTemplatePanel records={linkListRecords} />
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
        title="店小秘 TEMU 半托管模板导出"
        open={exportOpen}
        confirmLoading={exportingTemplate}
        onCancel={() => setExportOpen(false)}
        onOk={exportTemplate}
        okText="开始导出"
        cancelText="取消"
      >
        <Space direction="vertical" size={16} className="export-modal-content">
          <Text type="secondary">
            按店小秘 TEMU 半托管模板直接导出；如果商品已经改图，会优先使用云端改图结果，否则使用原始采集图片。
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
