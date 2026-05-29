import { Descriptions, Drawer, Image, Space, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { mockCandidates } from '../mock/products';
import type { Product, SourcingCandidate } from '../types/product';
import { Sourcing1688Panel } from './Sourcing1688Panel';

const { Title, Text } = Typography;

type Props = {
  open: boolean;
  product?: Product;
  searched: boolean;
  activeCandidate?: SourcingCandidate;
  activeTab: 'search' | 'detail';
  onClose: () => void;
  onSearch: () => void;
  onOpenCandidateDetail: (candidate: SourcingCandidate) => void;
  onBackToSearch: () => void;
  onSelectCandidate: (product: Product, candidate: SourcingCandidate) => void;
};

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
        <span>云启商品图</span>
      )}
    </div>
  );
}

export function ProductDetailDrawer({
  open,
  product,
  searched,
  activeCandidate,
  activeTab,
  onClose,
  onSearch,
  onOpenCandidateDetail,
  onBackToSearch,
  onSelectCandidate,
}: Props) {
  if (!product) return null;

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
          <Text type="secondary">原始行：{product.sourceRow} · {product.category}</Text>
          <Descriptions column={2} className="product-descriptions">
            <Descriptions.Item label="价格">¥{product.price.toFixed(2)}</Descriptions.Item>
            <Descriptions.Item label="销量">{product.sales.toLocaleString()}</Descriptions.Item>
            <Descriptions.Item label="GMV">${(product.gmv / 1000).toFixed(1)}k</Descriptions.Item>
            <Descriptions.Item label="评论数">
              {product.reviewCount.toLocaleString()}
            </Descriptions.Item>
            <Descriptions.Item label="上架时间">{product.listedAt}</Descriptions.Item>
            <Descriptions.Item label="增长率">+{product.growthRate}%</Descriptions.Item>
          </Descriptions>
        </aside>

        <main className="drawer-sourcing-side">
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
          />
        </main>
      </div>
    </Drawer>
  );
}
