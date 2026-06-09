import { Button, Descriptions, Drawer, Image, Space, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { mockCandidates } from '../mock/products';
import type { LinkListRecord } from '../types/linkList';
import type { Product, SourcingCandidate } from '../types/product';
import { Sourcing1688Panel } from './Sourcing1688Panel';

const { Title, Text } = Typography;

type Props = {
  open: boolean;
  product?: Product;
  mode?: 'sourcing' | 'sales';
  searched: boolean;
  activeCandidate?: SourcingCandidate;
  activeTab: 'search' | 'detail';
  onClose: () => void;
  onSearch: () => void;
  onOpenCandidateDetail: (candidate: SourcingCandidate) => void;
  onBackToSearch: () => void;
  onSelectCandidate: (product: Product, candidate: SourcingCandidate) => void;
  onRecordLinkEntry: (record: LinkListRecord) => void;
};

function formatProductPrice(product: Product) {
  if (!Number.isFinite(product.price)) return '-';
  const symbol = product.sourceType === '1688' ? '¥' : '$';
  return `${symbol}${product.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatUsd(value: number) {
  return Number.isFinite(value)
    ? `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '-';
}

function formatNumber(value?: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '0';
}

function DrawerProductImage({ product }: { product: Product }) {
  const [broken, setBroken] = useState(false);

  useEffect(() => {
    setBroken(false);
  }, [product.mainImageUrl]);

  return (
    <div className={`drawer-product-image product-thumb-${product.imageTone}`}>
      {product.mainImageUrl && !broken ? (
        <Image
          alt={product.titleEn || product.title}
          height="100%"
          preview={{ mask: '预览商品主图' }}
          referrerPolicy="no-referrer"
          src={product.mainImageUrl}
          width="100%"
          onError={() => setBroken(true)}
        />
      ) : (
        <span>商品主图</span>
      )}
    </div>
  );
}

export function ProductDetailDrawer({
  open,
  product,
  mode = 'sourcing',
  searched,
  activeCandidate,
  activeTab,
  onClose,
  onSearch,
  onOpenCandidateDetail,
  onBackToSearch,
  onSelectCandidate,
  onRecordLinkEntry,
}: Props) {
  if (!product) return null;
  const weeklySales = product.weeklySales ?? (product.period === '近7天' ? product.sales : 0);
  const monthlySales = product.monthlySales ?? product.sales;

  return (
    <Drawer
      className="product-detail-drawer"
      width="80vw"
      open={open}
      onClose={onClose}
      title={
        <Space>
          <span>商品详情</span>
          <Tag color={product.status === 'sourced' ? 'green' : 'gold'}>
            {product.status === 'sourced' ? '已找到货源' : '待找品'}
          </Tag>
        </Space>
      }
    >
      <div className="drawer-layout">
        <aside className="drawer-product-side">
          <DrawerProductImage product={product} />
          <Title level={4}>{product.title}</Title>
          <Text type="secondary">
            原始行：{product.sourceRow} · {product.category}
          </Text>
          <Descriptions column={2} className="product-descriptions">
            <Descriptions.Item label="价格">{formatProductPrice(product)}</Descriptions.Item>
            <Descriptions.Item label="销量">{product.sales.toLocaleString()}</Descriptions.Item>
            <Descriptions.Item label="GMV">{formatUsd(product.gmv)}</Descriptions.Item>
            <Descriptions.Item label="评论数">{product.reviewCount.toLocaleString()}</Descriptions.Item>
            <Descriptions.Item label="上架时间">{product.listedAt}</Descriptions.Item>
            <Descriptions.Item label="增长率">+{product.growthRate}%</Descriptions.Item>
          </Descriptions>
        </aside>

        <main className="drawer-sourcing-side">
          {mode === 'sales' ? (
            <div className="drawer-sales-panel">
              <div className="drawer-sales-head">
                <div>
                  <Title level={4}>销售数据</Title>
                  <Text type="secondary">来自数据台商品记录，用于后续筛选、推荐和选品判断。</Text>
                </div>
                {product.sourceUrl ? (
                  <Button onClick={() => window.open(product.sourceUrl, '_blank', 'noopener,noreferrer')}>
                    打开原链接
                  </Button>
                ) : null}
              </div>

              <div className="drawer-sales-grid">
                <div className="drawer-sales-card">
                  <Text type="secondary">周销量</Text>
                  <strong>{formatNumber(weeklySales)}</strong>
                </div>
                <div className="drawer-sales-card">
                  <Text type="secondary">月销量</Text>
                  <strong>{formatNumber(monthlySales)}</strong>
                </div>
                <div className="drawer-sales-card">
                  <Text type="secondary">GMV</Text>
                  <strong>{formatUsd(product.gmv)}</strong>
                </div>
                <div className="drawer-sales-card">
                  <Text type="secondary">评论数</Text>
                  <strong>{formatNumber(product.reviewCount)}</strong>
                </div>
              </div>

              <Descriptions bordered column={2} className="drawer-sales-descriptions">
                <Descriptions.Item label="商品价格">{formatProductPrice(product)}</Descriptions.Item>
                <Descriptions.Item label="增长率">+{product.growthRate}%</Descriptions.Item>
                <Descriptions.Item label="上架时间">{product.listedAt || '-'}</Descriptions.Item>
                <Descriptions.Item label="来源行">{product.sourceRow || '-'}</Descriptions.Item>
                <Descriptions.Item label="一级类目">{product.categoryLevel1 || '-'}</Descriptions.Item>
                <Descriptions.Item label="二级类目">{product.categoryLevel2 || '-'}</Descriptions.Item>
                <Descriptions.Item label="完整类目" span={2}>
                  {product.categoryPath || product.category || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="商品 ID" span={2}>
                  {product.sourceProductId || product.id}
                </Descriptions.Item>
              </Descriptions>
            </div>
          ) : (
            <Sourcing1688Panel
              product={product}
              candidates={mockCandidates}
              searched={searched}
              activeCandidate={activeCandidate}
              activeTab={activeTab}
              onSearch={onSearch}
              onOpenDetail={onOpenCandidateDetail}
              onBackToSearch={onBackToSearch}
              onSelectCandidate={(candidate) => onSelectCandidate(product, candidate)}
              onRecordLinkEntry={onRecordLinkEntry}
            />
          )}
        </main>
      </div>
    </Drawer>
  );
}
