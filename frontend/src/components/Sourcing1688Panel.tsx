import { Button, Card, Empty, Image, Input, Space, Tabs, Tag, Typography, message } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchCaptured1688Candidates,
  setActive1688CaptureSession,
} from '../api/backendApi';
import type { Captured1688Candidate } from '../api/backendApi';
import type { Product, SourcingCandidate } from '../types/product';

const { Text } = Typography;

type Props = {
  product: Product;
  candidates: SourcingCandidate[];
  searched: boolean;
  activeCandidate?: SourcingCandidate;
  activeTab: 'search' | 'detail';
  onSearch: () => void;
  onOpenDetail: (candidate: SourcingCandidate) => void;
  onBackToSearch: () => void;
  onSelectCandidate: (candidate: SourcingCandidate) => void;
};

function buildKeyword(product: Product) {
  return (product.title || product.titleEn || '')
    .replace(/家用|便携|批发款/g, '')
    .split(/\s+/)
    .slice(0, 8)
    .join(' ');
}

function formatPrice(candidate: Captured1688Candidate) {
  if (candidate.price_range) return candidate.price_range;
  if (candidate.price !== null && candidate.price !== undefined) return `¥${candidate.price.toFixed(2)}`;
  return '待采集';
}

export function Sourcing1688Panel({ product, onSearch }: Props) {
  const [captureStarted, setCaptureStarted] = useState(false);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [capturedCandidates, setCapturedCandidates] = useState<Captured1688Candidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<Captured1688Candidate | undefined>();
  const [tab, setTab] = useState<'search' | 'detail'>('search');

  const keyword = useMemo(() => buildKeyword(product), [product]);

  const loadCapturedCandidates = useCallback(async () => {
    setLoadingCandidates(true);
    try {
      const items = await fetchCaptured1688Candidates(product.id);
      setCapturedCandidates(items);
      if (!selectedCandidate && items.length > 0) {
        setSelectedCandidate(items[0]);
      }
    } catch {
      setCapturedCandidates([]);
    } finally {
      setLoadingCandidates(false);
    }
  }, [product.id, selectedCandidate]);

  useEffect(() => {
    setCaptureStarted(false);
    setCapturedCandidates([]);
    setSelectedCandidate(undefined);
    setTab('search');
    void loadCapturedCandidates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product.id]);

  useEffect(() => {
    if (!captureStarted) return undefined;
    const timer = window.setInterval(() => {
      void loadCapturedCandidates();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [captureStarted, loadCapturedCandidates]);

  const startCapture = async () => {
    try {
      await setActive1688CaptureSession(product.id);
      setCaptureStarted(true);
      onSearch();
      message.success('已绑定当前商品，插件采集会回显到这里');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '绑定采集商品失败');
    }
  };

  const open1688 = () => {
    window.open('https://www.1688.com/', '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="sourcing-panel">
      <Tabs
        activeKey={tab}
        items={[
          { key: 'search', label: '1688 采集' },
          { key: 'detail', label: '采集详情', disabled: !selectedCandidate },
        ]}
        onChange={(key) => setTab(key as 'search' | 'detail')}
      />

      {tab === 'search' ? (
        <div className="sourcing-search">
          <div className="search-row">
            <Input value={keyword} readOnly />
            <Button onClick={open1688}>打开 1688</Button>
            <Button type="primary" onClick={startCapture}>
              开始采集
            </Button>
          </div>

          <Card className="capture-guide" size="small">
            <Space direction="vertical" size={6}>
              <Text strong>采集流程</Text>
              <Text type="secondary">1. 点击开始采集，绑定当前 Temu 商品。</Text>
              <Text type="secondary">2. 使用 1688 官方图搜插件找到同款并进入商品详情页。</Text>
              <Text type="secondary">3. 点击我们的 Chrome 插件“采集到工作台”。</Text>
              <Text type="secondary">4. 本抽屉会自动刷新并显示 1688 链接、价格和 SKU 信息。</Text>
            </Space>
          </Card>

          {capturedCandidates.length === 0 ? (
            <Empty
              className="sourcing-empty"
              description={captureStarted ? '等待插件采集当前 1688 商品页。' : '先点击开始采集，绑定当前商品。'}
            >
              <Space>
                <Button onClick={startCapture} type="primary">
                  开始采集
                </Button>
                <Button loading={loadingCandidates} onClick={loadCapturedCandidates}>
                  刷新结果
                </Button>
              </Space>
            </Empty>
          ) : (
            <>
              <Space className="tag-row">
                <Tag color="blue">已采集 {capturedCandidates.length} 个货源</Tag>
                {captureStarted ? <Tag color="green">监听中</Tag> : <Tag>未监听</Tag>}
              </Space>
              <div className="captured-candidate-list">
                {capturedCandidates.map((candidate) => (
                  <Card
                    className="captured-candidate-card"
                    hoverable
                    key={candidate.id}
                    onClick={() => {
                      setSelectedCandidate(candidate);
                      setTab('detail');
                    }}
                  >
                    <div className="captured-candidate-layout">
                      <div className="candidate-image candidate-image-real">
                        {candidate.main_image_url ? (
                          <Image
                            alt={candidate.title}
                            height={76}
                            preview={false}
                            referrerPolicy="no-referrer"
                            src={candidate.main_image_url}
                            width={76}
                          />
                        ) : (
                          <span>1688 图</span>
                        )}
                      </div>
                      <div>
                        <div className="candidate-title">{candidate.title}</div>
                        <div className="candidate-meta-line">
                          <Text strong className="price-red">
                            {formatPrice(candidate)}
                          </Text>
                          <Tag color="blue">SKU {candidate.sku_list.length}</Tag>
                          {candidate.moq ? <Tag color="gold">MOQ {candidate.moq}</Tag> : null}
                        </div>
                        <Text type="secondary">{candidate.shop_name || '店铺待采集'}</Text>
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            </>
          )}
        </div>
      ) : selectedCandidate ? (
        <div className="candidate-detail-page">
          <div className="detail-gallery">
            <div className="detail-hero-image detail-hero-image-real">
              {selectedCandidate.main_image_url ? (
                <Image
                  alt={selectedCandidate.title}
                  height="100%"
                  referrerPolicy="no-referrer"
                  src={selectedCandidate.main_image_url}
                  width="100%"
                />
              ) : (
                '1688 商品大图'
              )}
            </div>
          </div>
          <div className="detail-info">
            <Typography.Title level={4}>{selectedCandidate.title}</Typography.Title>
            <Space wrap>
              <Tag color="blue">1688 已采集</Tag>
              <Tag color="green">SKU {selectedCandidate.sku_list.length}</Tag>
              {selectedCandidate.offer_id ? <Tag>Offer {selectedCandidate.offer_id}</Tag> : null}
            </Space>
            <div className="detail-metrics">
              <div>
                <Text type="secondary">采购价</Text>
                <strong className="price-large">{formatPrice(selectedCandidate)}</strong>
              </div>
              <div>
                <Text type="secondary">MOQ</Text>
                <strong>{selectedCandidate.moq || '-'}</strong>
              </div>
              <div>
                <Text type="secondary">店铺</Text>
                <strong>{selectedCandidate.shop_name || '-'}</strong>
              </div>
              <div>
                <Text type="secondary">采集时间</Text>
                <strong>{selectedCandidate.captured_at.slice(0, 19)}</strong>
              </div>
            </div>
            <div className="detail-lines">
              <p>链接：{selectedCandidate.product_url}</p>
              <p>店铺链接：{selectedCandidate.shop_url || '-'}</p>
            </div>
            <Card size="small" title="SKU 数据">
              {selectedCandidate.sku_list.length === 0 ? (
                <Text type="secondary">插件暂未采集到 SKU 明细。</Text>
              ) : (
                <div className="sku-list">
                  {selectedCandidate.sku_list.map((sku, index) => (
                    <div className="sku-row" key={sku.sku_id || index}>
                      <Text strong>{Object.values(sku.specs || {}).join(' / ') || `SKU ${index + 1}`}</Text>
                      <Text type="secondary">
                        {sku.price ? `¥${sku.price}` : '价格待采集'}
                        {sku.stock !== undefined ? ` · 库存 ${sku.stock}` : ''}
                      </Text>
                    </div>
                  ))}
                </div>
              )}
            </Card>
            <Space className="detail-actions">
              <Button onClick={() => setTab('search')}>返回采集列表</Button>
              <Button onClick={() => window.open(selectedCandidate.product_url, '_blank', 'noopener,noreferrer')}>
                打开 1688 原页
              </Button>
              <Button type="primary">确认使用该货源</Button>
            </Space>
          </div>
        </div>
      ) : null}
    </div>
  );
}
