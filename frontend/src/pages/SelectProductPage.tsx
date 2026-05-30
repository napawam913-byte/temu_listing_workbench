import {
  Button,
  Card,
  Empty,
  Form,
  Image,
  Input,
  Layout,
  Modal,
  Radio,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
  message,
} from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { Key } from 'react';
import {
  deleteProduct as deleteBackendProduct,
  createPluginCreativeJobs,
  exportDianxiaomiTemuTemplate,
  fetchProductStats,
  fetchProducts,
  mapBackendProduct,
  syncPluginCreativeJobs,
  upload1688Links,
  uploadYunqiFile,
} from '../api/backendApi';
import type { DianxiaomiExportMode, ProductStats } from '../api/backendApi';
import { DataImportModal } from '../components/DataImportModal';
import { ProductDetailDrawer } from '../components/ProductDetailDrawer';
import { ProductTable } from '../components/ProductTable';
import { mockProducts } from '../mock/products';
import type { LinkListRecord } from '../types/linkList';
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

type WorkbenchTab = 'sourcing' | 'differentiation' | 'links';

const LINK_LIST_STORAGE_KEY = 'temuListingWorkbenchLinkListRecords';
const CURATED_EXPORT_IMAGE_COUNT = 8;

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

function hasCuratedExportImages(record: LinkListRecord) {
  const mainImage = record.mainImage;
  const mainReady = Boolean(mainImage?.editedCloudUrl || mainImage?.editedUrl || mainImage?.displayCloudUrl);
  const curatedImages = (record.productMaterialImages || []).filter(
    (asset) => asset.editedCloudUrl || asset.editedUrl || asset.displayCloudUrl,
  );

  return mainReady && curatedImages.length >= CURATED_EXPORT_IMAGE_COUNT;
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

function getRecordMainImageUrl(record?: LinkListRecord) {
  if (!record) return undefined;
  return record.mainImage?.editedUrl || record.mainImage?.displayUrl || record.mainImage?.sourceUrl || record.productImageUrl;
}

function getSkuDisplayImageUrl(entry: LinkListRecord['skuEntries'][number]) {
  return entry.imageAsset?.editedUrl || entry.imageAsset?.displayUrl || entry.imageAsset?.sourceUrl || entry.imageUrl;
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
  const [generatingRecordId, setGeneratingRecordId] = useState<string>();
  const previewMainImage = getRecordMainImageUrl(previewRecord);

  const generateRecordCreative = async (record: LinkListRecord) => {
    setGeneratingRecordId(record.id);
    try {
      await createPluginCreativeJobs([record]);
      const synced = await syncPluginCreativeJobs([record]);
      const nextRecord = synced.records[0] || record;
      onUpdate(nextRecord);
      setPreviewRecord((current) => (current?.id === record.id ? nextRecord : current));
      message.success('已创建插件生图任务，请在插件侧边栏处理');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '插件生图任务创建失败');
    } finally {
      setGeneratingRecordId(undefined);
    }
  };

  return (
    <>
      {records.length === 0 ? (
        <Card className="link-list-empty-card">
          <Empty description="还没有录入链接。请在选品找货中选择 SKU 后点击“录入链接列表”。" />
        </Card>
      ) : (
        <div className="link-list">
          {records.map((record) => (
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
          ))}
        </div>
      )}

      <Modal
        className="link-preview-modal"
        footer={null}
        open={Boolean(previewRecord)}
        title="商品预览"
        width={960}
        onCancel={() => setPreviewRecord(undefined)}
      >
        {previewRecord ? (
          <div className="link-preview-shell">
            <div className="link-preview-media">
              <div className="link-preview-main-image">
                {previewMainImage ? (
                  <Image
                    alt={previewRecord.productTitle}
                    height="100%"
                    preview={false}
                    referrerPolicy="no-referrer"
                    src={previewMainImage}
                    width="100%"
                  />
                ) : (
                  <span>商品主图</span>
                )}
              </div>
            </div>

            <div className="link-preview-info">
              <Text className="link-preview-title" strong>
                {previewRecord.productTitle}
              </Text>
              <div className="link-preview-meta">
                <Tag color="blue">{previewRecord.skuEntries.length} 个销售 SKU</Tag>
                <Tag>{previewRecord.sourceLinks.length} 个货源链接</Tag>
                <Tag>组件 SKU {previewRecord.componentSkuCount}</Tag>
                {previewRecord.styleProfile ? <Tag color="purple">{previewRecord.styleProfile.provider === 'comfyui' ? 'ComfyUI' : 'ChatGPT'} 统一画风</Tag> : null}
              </div>

              <div className="link-preview-section">
                <Text strong>SKU 顺序</Text>
                <div className="link-preview-sku-list">
                  {previewRecord.skuEntries.map((entry) => (
                    <div className="link-preview-sku" key={entry.id}>
                      <span className="link-sku-order">{entry.order}</span>
                      <span className="link-sku-thumb">
                        {getSkuDisplayImageUrl(entry) ? (
                          <Image
                            alt={entry.name}
                            height={38}
                            preview={false}
                            referrerPolicy="no-referrer"
                            src={getSkuDisplayImageUrl(entry)}
                            width={38}
                          />
                        ) : (
                          'SKU'
                        )}
                      </span>
                      <div className="link-sku-copy">
                        <Text strong>{entry.name}</Text>
                        <Text type="secondary">
                          {entry.kind === 'combo' ? '组合' : '单 SKU'} · {entry.componentSkus.length} 个组件
                        </Text>
                        <Tag color="gold">{getImageTaskStatusText(entry.imageEditTask?.status)}</Tag>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="link-preview-section">
                <Text strong>货源链接</Text>
                <div className="link-preview-source-list">
                  {previewRecord.sourceLinks.map((source) => (
                    <a
                      className="link-source-card"
                      href={source.productUrl}
                      key={source.id}
                      rel="noreferrer"
                      target="_blank"
                    >
                      <span className="link-source-title">{source.title}</span>
                      <span>{source.shopName || '1688 货源'}</span>
                    </a>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
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
  const [exportMode, setExportMode] = useState<DianxiaomiExportMode>('distribution');
  const [exportingTemplate, setExportingTemplate] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
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

  useEffect(() => {
    void loadProducts(1, pageSize, filters);
    void loadStats();
    setCurrentPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeCount = productStats.active_count;
  const deletedCount = productStats.deleted_count;

  const openProduct = useCallback((product: Product, options: { syncUrl?: boolean } = {}) => {
    setActiveProduct(product);
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
        const next = [record, ...current].slice(0, 200);
        writeLinkListRecords(next);
        return next;
      });
      closeProduct();
      setActiveWorkbenchTab('links');
      message.success('已录入链接列表');
    },
    [closeProduct],
  );

  const deleteLinkEntry = useCallback((recordId: string) => {
    setLinkListRecords((current) => {
      const next = current.filter((record) => record.id !== recordId);
      writeLinkListRecords(next);
      return next;
    });
    message.success('已删除链接记录');
  }, []);

  const updateLinkEntry = useCallback((record: LinkListRecord) => {
    setLinkListRecords((current) => {
      const next = current.map((item) => (item.id === record.id ? record : item));
      writeLinkListRecords(next);
      return next;
    });
  }, []);

  const exportTemplate = useCallback(async () => {
    if (linkListRecords.length === 0) {
      message.warning('请先在选品找货中录入链接列表，再导出店小秘模板');
      return;
    }

    setExportingTemplate(true);
    try {
      const modeLabel = exportMode === 'distribution' ? '铺货' : '精铺';
      let recordsForExport = linkListRecords;
      if (exportMode === 'curated') {
        const syncResult = await syncPluginCreativeJobs(linkListRecords);
        recordsForExport = syncResult.records;
        if (syncResult.completedRecordIds.length > 0) {
          setLinkListRecords(syncResult.records);
          writeLinkListRecords(syncResult.records);
        }

        const missingRecords = recordsForExport.filter((record) => !hasCuratedExportImages(record));
        if (missingRecords.length > 0) {
          const jobResult = await createPluginCreativeJobs(missingRecords);
          setLinkListRecords(recordsForExport);
          writeLinkListRecords(recordsForExport);
          setExportOpen(false);
          message.info(
            `已创建 ${jobResult.items.length} 个插件生图任务，请在插件侧边栏完成后再导出精铺模板`,
            6,
          );
          return;
        }
      }

      const blob = await exportDianxiaomiTemuTemplate(recordsForExport, exportMode);
      downloadBlob(blob, `店小秘_TEMU半托管_${modeLabel}_${new Date().toISOString().slice(0, 10)}.xlsx`);
      setExportOpen(false);
      message.success(`店小秘 TEMU 半托管${modeLabel}模板已生成`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '模板导出失败');
    } finally {
      setExportingTemplate(false);
    }
  }, [exportMode, linkListRecords]);

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
              className={`main-nav-item ${activeWorkbenchTab === 'sourcing' ? 'main-nav-active' : ''}`}
              type="button"
              onClick={() => setActiveWorkbenchTab('sourcing')}
            >
              选品找货
            </button>
            <button
              className={`main-nav-item ${activeWorkbenchTab === 'differentiation' ? 'main-nav-active' : ''}`}
              type="button"
              onClick={() => setActiveWorkbenchTab('differentiation')}
            >
              商品差异化
            </button>
            <button
              className={`main-nav-item ${activeWorkbenchTab === 'links' ? 'main-nav-active' : ''}`}
              type="button"
              onClick={() => setActiveWorkbenchTab('links')}
            >
              链接列表
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
          ) : activeWorkbenchTab === 'differentiation' ? (
            <>
              <Card>
                <Empty description="商品差异化功能待配置。" />
              </Card>
            </>
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
          <Text type="secondary">按桌面提供的店小秘 TEMU 半托管模板输出；精铺模式会先改图上传云端，再写入模板。</Text>
          <Card size="small" title="导出模式">
            <Space direction="vertical" size={10}>
              <Radio.Group
                buttonStyle="solid"
                optionType="button"
                value={exportMode}
                onChange={(event) => setExportMode(event.target.value)}
              >
                <Radio.Button value="distribution">铺货模式</Radio.Button>
                <Radio.Button value="curated">精铺模式</Radio.Button>
              </Radio.Group>
              <Text type="secondary">
                {exportMode === 'distribution'
                  ? '照搬原链接商品主图，产品描述直接使用产品素材图图片。'
                  : '先生成统一画风主图和素材图并上传 OSS，再用云端图片填写模板。'}
              </Text>
            </Space>
          </Card>
          <Card size="small" title="导出范围">
            <Space direction="vertical">
              <Text strong>链接列表商品：{linkListRecords.length} 个</Text>
              <Text>销售 SKU：{linkListRecords.reduce((total, record) => total + record.skuEntries.length, 0)} 个</Text>
              <Text>
                图片策略：
                {exportMode === 'distribution'
                  ? '原始主图/素材图进入轮播、素材图和描述；SKU 图使用原图。'
                  : '缺少精铺云端图时会先调用 ChatGPT 生成 8 张图并上传 OSS。'}
              </Text>
            </Space>
          </Card>
          <Card size="small" title="默认字段">
            <Space direction="vertical">
              <Text>变种属性：按店小秘下拉枚举自动匹配（颜色/风格/材质/数量/型号等）</Text>
              <Text>包装：不规则 / 硬包装</Text>
              <Text>尺寸重量缺失时：10 × 10 × 5 cm，200 g</Text>
              <Text>库存：0；发货时效：16 天</Text>
            </Space>
          </Card>
        </Space>
      </Modal>
    </Layout>
  );
}
