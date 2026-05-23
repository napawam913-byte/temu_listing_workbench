import {
  Button,
  Card,
  Form,
  Input,
  Layout,
  Modal,
  Select,
  Space,
  Statistic,
  TreeSelect,
  Typography,
  message,
} from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { Key } from 'react';
import {
  deleteProduct as deleteBackendProduct,
  fetchProductCategories,
  fetchProductStats,
  fetchProducts,
  mapBackendProduct,
  uploadYunqiFile,
} from '../api/backendApi';
import type { ProductStats } from '../api/backendApi';
import type { ProductCategoryOption } from '../api/backendApi';
import { DataImportModal } from '../components/DataImportModal';
import { ProductDetailDrawer } from '../components/ProductDetailDrawer';
import { ProductTable } from '../components/ProductTable';
import { mockProducts } from '../mock/products';
import type { Product, SourcingCandidate } from '../types/product';

const { Header, Content } = Layout;
const { Title, Text } = Typography;

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
  category: '全部类目',
};

const ALL_CATEGORY_VALUE = '全部类目';

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

export function SelectProductPage() {
  const [form] = Form.useForm<Filters>();
  const [products, setProducts] = useState<Product[]>(mockProducts);
  const [productTotal, setProductTotal] = useState(mockProducts.length);
  const [productStats, setProductStats] = useState<ProductStats>(defaultStats);
  const [categoryOptions, setCategoryOptions] = useState<ProductCategoryOption[]>([]);
  const [backendReady, setBackendReady] = useState(false);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [importOpen, setImportOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [activeProduct, setActiveProduct] = useState<Product | undefined>();
  const [sourcingSearched, setSourcingSearched] = useState(false);
  const [activeCandidate, setActiveCandidate] = useState<SourcingCandidate | undefined>();
  const [activeTab, setActiveTab] = useState<'search' | 'detail'>('search');

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
            nextFilters.category &&
            nextFilters.category !== '全部类目' &&
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

  const loadCategories = useCallback(async () => {
    try {
      const options = await fetchProductCategories();
      setCategoryOptions(options);
    } catch {
      setCategoryOptions([]);
    }
  }, []);

  useEffect(() => {
    void loadProducts(1, pageSize, filters);
    void loadStats();
    void loadCategories();
    setCurrentPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeCount = productStats.active_count;
  const deletedCount = productStats.deleted_count;

  const openProduct = (product: Product) => {
    setActiveProduct(product);
    setSourcingSearched(product.status === 'sourced');
    setActiveCandidate(undefined);
    setActiveTab('search');
    setDrawerOpen(true);
  };

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
      if (activeProduct?.id === product.id) setDrawerOpen(false);
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
        if (activeProduct?.id === product.id) setDrawerOpen(false);
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
          <div className="main-nav-active">选品找货</div>
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
          <div className="page-title-row">
            <div>
              <Title level={2}>选品找货</Title>
              <Text type="secondary">导入云启数据后，在这里查看、筛选和导出商品记录。</Text>
            </div>
          </div>

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
              <Form.Item label="类目" name="category">
                <TreeSelect
                  allowClear
                  dropdownStyle={{ maxHeight: 420, minWidth: 460, overflow: 'auto' }}
                  placeholder="分类筛选"
                  showSearch
                  style={{ width: 190 }}
                  treeDefaultExpandAll={false}
                  treeNodeFilterProp="title"
                  treeData={[
                    { value: ALL_CATEGORY_VALUE, title: '全分类' },
                    ...categoryOptions.map((option) => ({
                      value: option.value,
                      title: `${option.label}（${option.count}）`,
                      children: option.children?.map((child) => ({
                        value: child.value,
                        title: `${child.label}（${child.count}）`,
                      })),
                    })),
                  ]}
                  onClear={() => form.setFieldValue('category', ALL_CATEGORY_VALUE)}
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
          await Promise.all([loadProducts(1, pageSize, filters), loadStats(), loadCategories()]);
        }}
      />

      <ProductDetailDrawer
        open={drawerOpen}
        product={activeProduct}
        searched={sourcingSearched}
        activeCandidate={activeCandidate}
        activeTab={activeTab}
        onClose={() => setDrawerOpen(false)}
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
        onDelete={deleteProduct}
      />

      <Modal
        title="清单导出"
        open={exportOpen}
        onCancel={() => setExportOpen(false)}
        onOk={() => {
          setExportOpen(false);
          message.success('已模拟生成商品清单');
        }}
        okText="开始导出"
        cancelText="取消"
      >
        <Space direction="vertical" size={16} className="export-modal-content">
          <Text type="secondary">导出当前选品阶段的商品清单，不是店小蜜上架模板。</Text>
          <Card size="small" title="导出范围">
            <Space direction="vertical">
              <Text strong>已勾选商品（{selectedRowKeys.length} 条）</Text>
              <Text>当前筛选结果（{productTotal} 条）</Text>
              <Text>当前批次全部商品（{products.length} 条）</Text>
            </Space>
          </Card>
          <Card size="small" title="导出地址">
            <Text>D:\learning\temu_listing_workbench\storage\exports</Text>
          </Card>
        </Space>
      </Modal>
    </Layout>
  );
}
