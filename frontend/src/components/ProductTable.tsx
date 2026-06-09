import { Button, Image, InputNumber, Popconfirm, Space, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType, SortOrder, TableRowSelection } from 'antd/es/table/interface';
import { useEffect, useState } from 'react';
import type { Product } from '../types/product';

type Props = {
  products: Product[];
  total: number;
  currentPage: number;
  pageSize: number;
  selectedRowKeys: React.Key[];
  onSelectedRowKeysChange: (keys: React.Key[]) => void;
  onPageChange: (page: number, pageSize: number) => void;
  priceSortOrder?: SortOrder;
  onPriceSortChange?: (order?: SortOrder) => void;
  gmvSortOrder?: SortOrder;
  onGmvSortChange?: (order?: SortOrder) => void;
  onView: (product: Product) => void;
  onDelete: (product: Product) => void;
};

function formatProductPrice(product: Product) {
  if (!Number.isFinite(product.price)) return '-';
  const symbol = product.sourceType === '1688' ? '¥' : '$';
  return `${symbol}${product.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatProductGmv(product: Product) {
  if (!Number.isFinite(product.gmv)) return '-';
  return `$${product.gmv.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function ProductThumb({
  alt,
  src,
  tone,
}: {
  alt: string;
  src?: string;
  tone: Product['imageTone'];
}) {
  const [broken, setBroken] = useState(false);

  useEffect(() => {
    setBroken(false);
  }, [src]);

  return (
    <div className={`product-thumb product-thumb-${tone}`}>
      {src && !broken ? (
        <Image
          alt={alt}
          height={46}
          loading="lazy"
          preview={{ mask: '预览' }}
          referrerPolicy="no-referrer"
          src={src}
          width={46}
          onError={() => setBroken(true)}
        />
      ) : (
        <span>图</span>
      )}
    </div>
  );
}

function ProductTitleBlock({
  product,
  onView,
}: {
  product: Product;
  onView: (product: Product) => void;
}) {
  const visibleTitle = product.titleEn || product.title;
  const shouldShowFulfillmentTag = product.sourceType !== '1688';

  return (
    <div className="product-title-stack">
      <Tooltip
        placement="topLeft"
        title={<div className="product-title-tooltip">{product.title}</div>}
      >
        <button className="product-title-link" type="button" onClick={() => onView(product)}>
          {visibleTitle}
        </button>
      </Tooltip>
      {shouldShowFulfillmentTag ? (
        <div className="product-title-tags">
          <Tag color="orange">半托管</Tag>
        </div>
      ) : null}
      <div className="product-title-meta">上架：{product.listedAt || '-'}</div>
    </div>
  );
}

export function ProductTable({
  products,
  total,
  currentPage,
  pageSize,
  selectedRowKeys,
  onSelectedRowKeysChange,
  onPageChange,
  priceSortOrder,
  onPriceSortChange,
  gmvSortOrder,
  onGmvSortChange,
  onView,
  onDelete,
}: Props) {
  const [pageSizeDraft, setPageSizeDraft] = useState<number | null>(10);

  useEffect(() => {
    setPageSizeDraft(pageSize);
  }, [pageSize]);

  const commitPageSize = () => {
    const nextPageSize = pageSizeDraft ?? pageSize;
    const normalizedPageSize = Math.max(1, Math.min(100, Math.floor(nextPageSize)));
    setPageSizeDraft(normalizedPageSize);
    onPageChange(1, normalizedPageSize);
  };

  const rowSelection: TableRowSelection<Product> = {
    columnWidth: 36,
    selectedRowKeys,
    onChange: onSelectedRowKeysChange,
  };

  const columns: ColumnsType<Product> = [
    {
      title: '商品',
      dataIndex: 'title',
      width: '45%',
      render: (_, product) => (
        <div className="product-cell">
          <ProductThumb alt={product.titleEn || product.title} src={product.mainImageUrl} tone={product.imageTone} />
          <ProductTitleBlock product={product} onView={onView} />
        </div>
      ),
    },
    {
      title: '类目',
      dataIndex: 'category',
      width: '14%',
      render: (value: string) => <span className="table-wrap-text">{value}</span>,
    },
    {
      title: '价格',
      key: 'price',
      dataIndex: 'price',
      width: '10%',
      sorter: true,
      sortDirections: ['ascend', 'descend'],
      sortOrder: priceSortOrder || null,
      render: (_, product) => formatProductPrice(product),
    },
    {
      title: 'GMV',
      key: 'gmv',
      dataIndex: 'gmv',
      width: '11%',
      sorter: true,
      sortDirections: ['descend', 'ascend'],
      sortOrder: gmvSortOrder || null,
      render: (_, product) => formatProductGmv(product),
    },
    {
      title: '上架时间',
      dataIndex: 'listedAt',
      width: '12%',
    },
    {
      title: '操作',
      key: 'action',
      width: '8%',
      render: (_, product) => (
        <div className="table-actions">
          <Button type="link" onClick={() => onView(product)}>
            查看
          </Button>
          <Button
            disabled={!product.sourceUrl}
            type="link"
            onClick={() => {
              if (!product.sourceUrl) return;
              window.open(product.sourceUrl, '_blank', 'noopener,noreferrer');
            }}
          >
            访问
          </Button>
          <Popconfirm
            title="确认删除该商品？"
            description="删除后商品会从当前列表中隐藏。"
            okText="删除"
            cancelText="取消"
            onConfirm={() => onDelete(product)}
          >
            <Button danger type="link">
              删除
            </Button>
          </Popconfirm>
        </div>
      ),
    },
  ];

  return (
    <Table<Product>
      className="product-table"
      columns={columns}
      dataSource={products}
      pagination={{
        current: currentPage,
        pageSize,
        total,
        showSizeChanger: false,
        showTotal: (total) => (
          <Space className="page-helper" size={8}>
            <span>共 {total} 条</span>
            <span>每页</span>
            <InputNumber
              aria-label="每页显示商品数"
              className="page-size-input"
              controls={false}
              max={100}
              min={1}
              precision={0}
              size="small"
              value={pageSizeDraft}
              onBlur={commitPageSize}
              onChange={(value) => setPageSizeDraft(value)}
              onPressEnter={commitPageSize}
            />
            <span>条</span>
          </Space>
        ),
        onChange: (page) => onPageChange(page, pageSize),
      }}
      rowKey="id"
      rowSelection={rowSelection}
      size="middle"
      tableLayout="auto"
      onChange={(_, __, sorter, extra) => {
        if (extra.action !== 'sort') return;
        const activeSorter = Array.isArray(sorter) ? sorter[0] : sorter;
        const nextPriceOrder = activeSorter?.columnKey === 'price' ? activeSorter.order : undefined;
        const nextGmvOrder = activeSorter?.columnKey === 'gmv' ? activeSorter.order : undefined;
        onPriceSortChange?.(nextPriceOrder || undefined);
        onGmvSortChange?.(nextGmvOrder || undefined);
      }}
    />
  );
}
