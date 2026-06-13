import { BulbOutlined, EyeOutlined } from '@ant-design/icons';
import { Button, Card, Checkbox, Empty, Image, Input, InputNumber, Modal, Select, Skeleton, Space, Tabs, Tag, Typography, message } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  API_BASE_URL,
  deleteCaptured1688Candidate,
  fetchCaptured1688Candidates,
  fetchSmart1688Keywords,
  fetchSmart1688Recommendations,
  setActive1688CaptureSession,
} from '../api/backendApi';
import type {
  Captured1688Candidate,
  Captured1688Sku,
  Smart1688Keyword,
  Smart1688Recommendation,
  Smart1688RecommendationsResponse,
} from '../api/backendApi';
import type { LinkListImageAsset, LinkListImageSlot, LinkListRecord, LinkListSource } from '../types/linkList';
import type { Product, SourcingCandidate } from '../types/product';

const { Text } = Typography;
const DEFAULT_IMAGE_PROVIDER = 'chatgpt';
const MIN_PRODUCT_IMAGE_GENERATION_COUNT = 1;
const MAX_PRODUCT_IMAGE_GENERATION_COUNT = 8;
const SMART_RECOMMEND_CACHE_STORAGE_KEY = 'temuListingWorkbenchSmart1688CacheV2';
const SMART_RECOMMEND_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const DEFAULT_STYLE_PROMPT =
  '先分析，再执行。先分析商品品类、主体组件、SKU/组合售卖内容、可复用画风和禁用元素；再统一光线、背景、色温、质感和构图。保留 SKU 的真实款式、颜色、数量和关键细节，组合 SKU 必须把购买会收到的所有组件同框展示，生成干净一致的 Temu 电商商品图。';

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
  onRecordLinkEntry: (record: LinkListRecord) => void;
};

type SkuCombinationItem = {
  key: string;
  candidate: Captured1688Candidate;
  candidateIndex: number;
  sku: Captured1688Sku;
  index: number;
  specText: string;
  optionText: string;
  imageUrl?: string;
  price?: number;
  weight?: number;
};

type SelectedSkuCombo = {
  id: string;
  name: string;
  skuKeys: string[];
};

type FinalSkuEntry = {
  id: string;
  kind: 'single' | 'combo';
  name: string;
  items: SkuCombinationItem[];
  imageUrl?: string;
  price?: number;
  weight?: number;
};

type PanelTab = 'search' | 'recommend' | 'combo' | 'preview';

type SmartRecommendCacheEntry = {
  productKey: string;
  summary: string;
  strategy: string;
  keywords: Smart1688Keyword[];
  selectedKeywords: string[];
  items: Smart1688Recommendation[];
  updatedAt: number;
};

function buildKeyword(product: Product) {
  return (product.title || product.titleEn || '')
    .replace(/家用|便携|批发款/g, '')
    .split(/\s+/)
    .slice(0, 8)
    .join(' ');
}

function build1688KeywordSearchUrl(keyword: string) {
  const search = new URLSearchParams({ keyword });
  return `${API_BASE_URL}/api/sourcing/1688/search?${search.toString()}`;
}

function build1688TitleSearchUrl(product: Product) {
  const title = product.title.trim() || product.titleEn?.trim() || product.sourceProductId || product.id;
  const search = new URLSearchParams({ title });
  if (product.categoryPath || product.category) search.set('category', product.categoryPath || product.category);
  return `${API_BASE_URL}/api/sourcing/1688/title-search?${search.toString()}`;
}

function getSmartRecommendProductKey(product: Product) {
  return [
    product.sourceType || 'product',
    product.sourceProductId || product.id,
    product.title || product.titleEn || '',
    product.mainImageUrl || '',
  ].join('::');
}

function readSmartRecommendCache(product: Product): SmartRecommendCacheEntry | undefined {
  try {
    const productKey = getSmartRecommendProductKey(product);
    const cache = JSON.parse(localStorage.getItem(SMART_RECOMMEND_CACHE_STORAGE_KEY) || '{}') as Record<
      string,
      SmartRecommendCacheEntry
    >;
    const entry = cache[productKey];
    if (!entry || Date.now() - Number(entry.updatedAt || 0) > SMART_RECOMMEND_CACHE_MAX_AGE_MS) return undefined;
    return entry;
  } catch {
    return undefined;
  }
}

function writeSmartRecommendCache(product: Product, entry: Omit<SmartRecommendCacheEntry, 'productKey' | 'updatedAt'>) {
  try {
    const productKey = getSmartRecommendProductKey(product);
    const cache = JSON.parse(localStorage.getItem(SMART_RECOMMEND_CACHE_STORAGE_KEY) || '{}') as Record<
      string,
      SmartRecommendCacheEntry
    >;
    cache[productKey] = { ...entry, productKey, updatedAt: Date.now() };
    const entries = Object.entries(cache)
      .sort(([, left], [, right]) => Number(right.updatedAt || 0) - Number(left.updatedAt || 0))
      .slice(0, 120);
    localStorage.setItem(SMART_RECOMMEND_CACHE_STORAGE_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    // Cache failure should not block sourcing work.
  }
}

function formatPrice(candidate: Captured1688Candidate) {
  if (candidate.price_range) return candidate.price_range;
  if (candidate.price !== null && candidate.price !== undefined) return `¥${candidate.price.toFixed(2)}`;
  return '待采集';
}

function rawNumber(candidate: Captured1688Candidate, key: string) {
  const value = candidate.raw_data?.[key];
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
}

function formatMoneyValue(value?: number) {
  return value === undefined ? '-' : `¥${value.toFixed(2)}`;
}

function formatWeightValue(value?: number) {
  return value === undefined || value <= 0 ? '-' : `${value} kg`;
}

function formatSkuPrice(sku: Captured1688Sku) {
  return sku.price !== undefined && sku.price !== null ? `¥${Number(sku.price).toFixed(2)}` : undefined;
}

function formatSkuStock(sku: Captured1688Sku) {
  return sku.stock !== undefined && sku.stock !== null ? `库存 ${sku.stock}` : undefined;
}

function formatSkuWeight(sku: Captured1688Sku, candidate: Captured1688Candidate) {
  const skuWeight = Number(sku.weight_kg);
  if (Number.isFinite(skuWeight) && skuWeight > 0) return `${skuWeight} kg`;
  const candidateWeight = rawNumber(candidate, 'weight_kg');
  return candidateWeight !== undefined && candidateWeight > 0 ? `${candidateWeight} kg` : undefined;
}

function toStringArray(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0) : [];
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return values.reduce<string[]>((items, value) => {
    if (!value || items.includes(value)) return items;
    return [...items, value];
  }, []);
}

function normalizeProductImageGenerationCount(value: number | null | undefined) {
  const number = Number(value);
  if (!Number.isFinite(number)) return MAX_PRODUCT_IMAGE_GENERATION_COUNT;
  return Math.max(MIN_PRODUCT_IMAGE_GENERATION_COUNT, Math.min(MAX_PRODUCT_IMAGE_GENERATION_COUNT, Math.floor(number)));
}

function getCandidateImageUrls(candidate: Captured1688Candidate) {
  const rawGallery = toStringArray(candidate.raw_data?.gallery_image_urls);
  const topLevelGallery = toStringArray(candidate.gallery_image_urls);

  return uniqueStrings([candidate.main_image_url, ...topLevelGallery, ...rawGallery]);
}

function getCandidateMainImageUrl(candidate: Captured1688Candidate) {
  return getCandidateImageUrls(candidate)[0];
}

function getSkuImageUrl(_candidate: Captured1688Candidate, sku: Captured1688Sku, _index: number) {
  return sku.image_url || undefined;
}

function getDominantSkuPropName(skuList: Captured1688Sku[]) {
  const counts = new Map<string, number>();
  skuList.forEach((sku) => {
    Object.keys(sku.specs || {}).forEach((key) => {
      if (key !== '规格') counts.set(key, (counts.get(key) || 0) + 1);
    });
  });
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0]?.[0];
}

function getNormalizedSkuSpecs(sku: Captured1688Sku, dominantPropName?: string) {
  const specs = { ...(sku.specs || {}) };
  if (dominantPropName && specs['规格'] && !specs[dominantPropName]) {
    specs[dominantPropName] = specs['规格'];
    delete specs['规格'];
  }
  return specs;
}

function getSkuSpecText(sku: Captured1688Sku, index: number, dominantPropName?: string) {
  const specs = Object.entries(getNormalizedSkuSpecs(sku, dominantPropName))
    .map(([key, value]) => `${key}: ${value}`)
    .join(' / ');
  return specs || `SKU ${index + 1}`;
}

function getSkuOptionText(sku: Captured1688Sku, index: number, dominantPropName?: string) {
  const values = Object.values(getNormalizedSkuSpecs(sku, dominantPropName))
    .map((value) => String(value).trim())
    .filter(Boolean);
  const uniqueValues = uniqueStrings(values);
  return uniqueValues.join(' / ') || `SKU ${index + 1}`;
}

function getDisplaySkuList(candidate: Captured1688Candidate) {
  const skuList = candidate.sku_list || [];
  const strongSkus = skuList.filter(
    (sku) =>
      sku.price !== undefined ||
      sku.stock !== undefined ||
      (sku.sku_id && !sku.sku_id.startsWith('text-')) ||
      Object.keys(sku.specs || {}).length > 0,
  );
  return strongSkus.length > 0 ? strongSkus : skuList.slice(0, 30);
}

function getSkuSelectionKey(candidate: Captured1688Candidate, sku: Captured1688Sku, index: number, dominantPropName?: string) {
  return `${candidate.id}:${sku.sku_id || getSkuSpecText(sku, index, dominantPropName) || index}`;
}

function getSkuPriceNumber(sku: Captured1688Sku, candidate: Captured1688Candidate) {
  const skuPrice = Number(sku.price);
  if (Number.isFinite(skuPrice)) return skuPrice;

  const candidatePrice = Number(candidate.price);
  if (Number.isFinite(candidatePrice)) return candidatePrice;

  return rawNumber(candidate, 'unit_price_with_shipping');
}

function getSkuWeightNumber(sku: Captured1688Sku, candidate: Captured1688Candidate) {
  const skuWeight = Number(sku.weight_kg);
  if (Number.isFinite(skuWeight) && skuWeight > 0) return skuWeight;
  return rawNumber(candidate, 'weight_kg');
}

function formatNumberRange(values: Array<number | undefined>, formatter: (value: number) => string) {
  const validValues = values.filter((value): value is number => value !== undefined && Number.isFinite(value));
  if (validValues.length === 0) return '-';

  const min = Math.min(...validValues);
  const max = Math.max(...validValues);
  return min === max ? formatter(min) : `${formatter(min)} - ${formatter(max)}`;
}

function formatPositiveNumberRange(values: Array<number | undefined>, formatter: (value: number) => string) {
  const validValues = values.filter((value): value is number => value !== undefined && Number.isFinite(value) && value > 0);
  if (validValues.length === 0) return '-';

  const min = Math.min(...validValues);
  const max = Math.max(...validValues);
  return min === max ? formatter(min) : `${formatter(min)} - ${formatter(max)}`;
}

function sumKnownValues(values: Array<number | undefined>) {
  const validValues = values.filter((value): value is number => value !== undefined && Number.isFinite(value));
  if (validValues.length === 0) return undefined;
  return validValues.reduce((sum, value) => sum + value, 0);
}

function getCandidateSkuKeys(candidate: Captured1688Candidate) {
  const displaySkuList = getDisplaySkuList(candidate);
  const dominantPropName = getDominantSkuPropName(displaySkuList);
  return displaySkuList.map((sku, index) => getSkuSelectionKey(candidate, sku, index, dominantPropName));
}

function getCandidateLabel(candidate: Captured1688Candidate, candidateIndex: number) {
  return candidate.shop_name || candidate.offer_id || `货源 ${candidateIndex + 1}`;
}

function getSkuCombinationDisplayName(items: SkuCombinationItem[]) {
  return items.map((item) => item.optionText || item.specText).join('+');
}

function Smart1688KeywordRecommendations({ product }: { product: Product }) {
  const [keywordLoading, setKeywordLoading] = useState(false);
  const [recommendLoading, setRecommendLoading] = useState(false);
  const [summary, setSummary] = useState('');
  const [strategy, setStrategy] = useState('');
  const [keywords, setKeywords] = useState<Smart1688Keyword[]>([]);
  const [selectedKeywords, setSelectedKeywords] = useState<string[]>([]);
  const [customKeyword, setCustomKeyword] = useState('');
  const [items, setItems] = useState<Smart1688Recommendation[]>([]);
  const [previewItem, setPreviewItem] = useState<Smart1688Recommendation | null>(null);
  const [cacheLoaded, setCacheLoaded] = useState(false);
  const smartCacheKey = useMemo(() => getSmartRecommendProductKey(product), [product]);

  useEffect(() => {
    const cached = readSmartRecommendCache(product);
    if (cached) {
      setSummary(cached.summary);
      setStrategy(cached.strategy);
      setKeywords(cached.keywords);
      setSelectedKeywords(cached.selectedKeywords);
      setItems(cached.items);
      setCacheLoaded(true);
    } else {
      setSummary('');
      setStrategy('');
      setKeywords([]);
      setSelectedKeywords([]);
      setItems([]);
      setCacheLoaded(false);
    }
    setCustomKeyword('');
    setPreviewItem(null);
  }, [smartCacheKey]);

  const persistRecommendationCache = (patch: Partial<Smart1688RecommendationsResponse> & { selectedKeywords?: string[] }) => {
    writeSmartRecommendCache(product, {
      summary: patch.summary ?? summary,
      strategy: patch.strategy ?? strategy,
      keywords: patch.keywords ?? keywords,
      selectedKeywords: patch.selectedKeywords ?? selectedKeywords,
      items: patch.items ?? items,
    });
    setCacheLoaded(true);
  };

  const analyzeKeywords = async () => {
    setKeywordLoading(true);
    setItems([]);
    try {
      const result = await fetchSmart1688Keywords(product);
      const nextSelectedKeywords = result.keywords.map((item) => item.keyword);
      setSummary(result.summary);
      setStrategy(result.strategy);
      setKeywords(result.keywords);
      setSelectedKeywords(nextSelectedKeywords);
      persistRecommendationCache({ ...result, selectedKeywords: nextSelectedKeywords, items: [] });
      if (result.keywords.length === 0) {
        message.info('暂时没有分析出可用关键词');
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '关键词分析失败');
    } finally {
      setKeywordLoading(false);
    }
  };

  const addCustomKeyword = () => {
    const keyword = customKeyword.trim();
    if (!keyword) return;
    if (keywords.some((item) => item.keyword === keyword)) {
      setSelectedKeywords((current) => (current.includes(keyword) ? current : [...current, keyword]));
      setCustomKeyword('');
      return;
    }
    const nextKeyword: Smart1688Keyword = {
      keyword,
      intent: '人工补充关键词',
      reason: '由你手动添加后用于本地商品列表推荐。',
    };
    setKeywords((current) => [...current, nextKeyword]);
    setSelectedKeywords((current) => [...current, keyword]);
    setCustomKeyword('');
  };

  const toggleKeyword = (keyword: string, checked: boolean) => {
    setSelectedKeywords((current) => {
      if (checked) return current.includes(keyword) ? current : [...current, keyword];
      return current.filter((item) => item !== keyword);
    });
  };

  const loadRecommendations = async () => {
    const selectedKeywordObjects = keywords.filter((item) => selectedKeywords.includes(item.keyword));
    if (selectedKeywordObjects.length === 0) {
      message.warning('请先选择至少 1 个关键词');
      return;
    }

    setRecommendLoading(true);
    try {
      const result = await fetchSmart1688Recommendations(product, 12, selectedKeywordObjects);
      const nextSelectedKeywords = result.keywords
        .map((item) => item.keyword)
        .filter((keyword) => selectedKeywords.includes(keyword));
      setStrategy(result.strategy || strategy);
      setKeywords(result.keywords);
      setSelectedKeywords(nextSelectedKeywords);
      setItems(result.items);
      persistRecommendationCache({ ...result, selectedKeywords: nextSelectedKeywords });
      if (result.items.length === 0) {
        message.info('本地商品列表暂时没有匹配到推荐商品');
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '本地商品推荐失败');
    } finally {
      setRecommendLoading(false);
    }
  };

  const previewRecommendationImage = (item: Smart1688Recommendation) => {
    if (!item.main_image_url) {
      message.warning('这个推荐商品没有主图，不能预览');
      return;
    }
    setPreviewItem(item);
  };

  return (
    <section className="smart-recommend-panel smart-recommend-panel-wide">
      <div className="smart-recommend-head">
        <div>
          <Space size={6}>
            <BulbOutlined />
            <Text strong>智能推荐</Text>
            {cacheLoaded ? <Tag color="green">已缓存</Tag> : null}
          </Space>
          <Text className="smart-recommend-subtitle" type="secondary">
            先筛选 GPT 分析关键词，再从你的本地商品列表中回显可参考商品
          </Text>
        </div>
        <Space>
          <Button icon={<BulbOutlined />} loading={keywordLoading} onClick={analyzeKeywords}>
            {keywords.length > 0 ? '重新分析' : '分析关键词'}
          </Button>
          <Button
            disabled={keywords.length === 0}
            loading={recommendLoading}
            type="primary"
            onClick={loadRecommendations}
          >
            推荐商品
          </Button>
        </Space>
      </div>

      {summary || strategy ? (
        <Text className="smart-recommend-summary" type="secondary">
          {strategy || summary}
        </Text>
      ) : null}

      {keywords.length > 0 ? (
        <div className="smart-keyword-section">
          <div className="smart-keyword-toolbar">
            <Text strong>关键词筛选</Text>
            <Text type="secondary">已选 {selectedKeywords.length} 个</Text>
          </div>
          <div className="smart-keyword-grid">
            {keywords.map((item) => {
              const checked = selectedKeywords.includes(item.keyword);
              const searchUrl = item.searchUrl || build1688KeywordSearchUrl(item.keyword);
              return (
                <label className={`smart-keyword-card ${checked ? 'smart-keyword-card-active' : ''}`} key={item.keyword}>
                  <Checkbox checked={checked} onChange={(event) => toggleKeyword(item.keyword, event.target.checked)} />
                  <span>
                    <strong>{item.keyword}</strong>
                    <em>{item.reason || item.intent}</em>
                    <a
                      className="smart-keyword-search"
                      href={searchUrl}
                      rel="noopener noreferrer"
                      target="_blank"
                      onClick={(event) => event.stopPropagation()}
                    >
                      搜1688
                    </a>
                  </span>
                </label>
              );
            })}
          </div>
          <div className="smart-keyword-custom">
            <Input
              placeholder="手动补充关键词，例如：圆形药片盒"
              value={customKeyword}
              onChange={(event) => setCustomKeyword(event.target.value)}
              onPressEnter={addCustomKeyword}
            />
            <Button onClick={addCustomKeyword}>添加关键词</Button>
          </div>
        </div>
      ) : (
        <Empty
          className="sourcing-empty"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="先点击分析关键词，确认搜索方向后再推荐商品"
        >
          <Button type="primary" loading={keywordLoading} onClick={analyzeKeywords}>
            分析关键词
          </Button>
        </Empty>
      )}

      {recommendLoading ? (
        <Skeleton active paragraph={{ rows: 4 }} title={false} />
      ) : items.length > 0 ? (
        <div className="smart-recommend-list">
          {items.map((item) => (
            <button
              className="smart-recommend-card"
              key={item.id}
              type="button"
              onClick={() => previewRecommendationImage(item)}
              title={`点击预览主图：${item.reason}`}
            >
              <div className="smart-recommend-image">
                {item.main_image_url ? (
                  <Image
                    alt={item.title}
                    height={54}
                    preview={false}
                    referrerPolicy="no-referrer"
                    src={item.main_image_url}
                    width={54}
                  />
                ) : (
                  <span>商品</span>
                )}
              </div>
              <div className="smart-recommend-content">
                <div className="smart-recommend-title">{item.title}</div>
                <div className="smart-recommend-meta">
                  <Tag color="blue">图片预览</Tag>
                  <span>{item.keyword}</span>
                  {item.price ? <span>¥{Number(item.price).toFixed(2)}</span> : null}
                  {item.shop_name ? <span>{item.shop_name}</span> : null}
                </div>
              </div>
              <EyeOutlined className="smart-recommend-link-icon" />
            </button>
          ))}
        </div>
      ) : keywords.length > 0 ? (
        <Empty
          className="sourcing-empty"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="点击推荐商品后，这里会回显本地商品列表中的匹配商品"
        />
      ) : null}

      {previewItem?.main_image_url ? (
        <Image
          alt={previewItem.title}
          preview={{
            visible: true,
            src: previewItem.main_image_url,
            onVisibleChange: (visible) => {
              if (!visible) setPreviewItem(null);
            },
          }}
          referrerPolicy="no-referrer"
          src={previewItem.main_image_url}
          style={{ display: 'none' }}
        />
      ) : null}

    </section>
  );
}

export function Sourcing1688Panel({ product, onSearch, onRecordLinkEntry }: Props) {
  const [captureStarted, setCaptureStarted] = useState(false);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [capturedCandidates, setCapturedCandidates] = useState<Captured1688Candidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<Captured1688Candidate | undefined>();
  const [comboSourceId, setComboSourceId] = useState<string | undefined>();
  const [selectedSkuKeys, setSelectedSkuKeys] = useState<string[]>([]);
  const [selectedSkuCombos, setSelectedSkuCombos] = useState<SelectedSkuCombo[]>([]);
  const [pendingComboSkuKeys, setPendingComboSkuKeys] = useState<string[]>([]);
  const [skuComboModalOpen, setSkuComboModalOpen] = useState(false);
  const [comboModalSourcePickerId, setComboModalSourcePickerId] = useState<string | undefined>();
  const [comboModalSourceIds, setComboModalSourceIds] = useState<string[]>([]);
  const [activeComboModalSourceId, setActiveComboModalSourceId] = useState<string | undefined>();
  const [comboModalSkuKeys, setComboModalSkuKeys] = useState<string[]>([]);
  const [skuOrderModalOpen, setSkuOrderModalOpen] = useState(false);
  const [draggingSkuEntryId, setDraggingSkuEntryId] = useState<string | undefined>();
  const [finalSkuEntryOrderIds, setFinalSkuEntryOrderIds] = useState<string[]>([]);
  const [productImageGenerationCount, setProductImageGenerationCount] = useState(MAX_PRODUCT_IMAGE_GENERATION_COUNT);
  const [previewActiveEntryId, setPreviewActiveEntryId] = useState<string | undefined>();
  const [previewActiveImageUrl, setPreviewActiveImageUrl] = useState<string | undefined>();
  const [tab, setTab] = useState<PanelTab>('search');

  const keyword = useMemo(() => buildKeyword(product), [product]);
  const skuCombinationItems = useMemo<SkuCombinationItem[]>(
    () =>
      capturedCandidates.flatMap((candidate, candidateIndex) => {
        const displaySkuList = getDisplaySkuList(candidate);
        const dominantPropName = getDominantSkuPropName(displaySkuList);

        return displaySkuList.map((sku, index) => ({
          key: getSkuSelectionKey(candidate, sku, index, dominantPropName),
          candidate,
          candidateIndex,
          sku,
          index,
          specText: getSkuSpecText(sku, index, dominantPropName),
          optionText: getSkuOptionText(sku, index, dominantPropName),
          imageUrl: getSkuImageUrl(candidate, sku, index),
          price: getSkuPriceNumber(sku, candidate),
          weight: getSkuWeightNumber(sku, candidate),
        }));
      }),
    [capturedCandidates],
  );
  const availableSkuKeySet = useMemo(
    () => new Set(skuCombinationItems.map((item) => item.key)),
    [skuCombinationItems],
  );
  const skuCombinationItemMap = useMemo(
    () => new Map(skuCombinationItems.map((item) => [item.key, item])),
    [skuCombinationItems],
  );
  const selectedSkuKeySet = useMemo(() => new Set(selectedSkuKeys), [selectedSkuKeys]);
  const selectedSkuItems = useMemo(
    () => skuCombinationItems.filter((item) => selectedSkuKeySet.has(item.key)),
    [selectedSkuKeySet, skuCombinationItems],
  );
  const selectedSkuComboSummaries = useMemo(
    () =>
      selectedSkuCombos
        .map((combo) => ({
          ...combo,
          items: combo.skuKeys
            .map((key) => skuCombinationItemMap.get(key))
            .filter((item): item is SkuCombinationItem => Boolean(item)),
        }))
        .filter((combo) => combo.items.length > 0)
        .map((combo) => ({
          ...combo,
          displayName: getSkuCombinationDisplayName(combo.items) || combo.name,
        })),
    [selectedSkuCombos, skuCombinationItemMap],
  );
  const selectedComboSkuItems = useMemo(
    () => selectedSkuComboSummaries.flatMap((combo) => combo.items),
    [selectedSkuComboSummaries],
  );
  const selectedSourceCount = useMemo(
    () => new Set([...selectedSkuItems, ...selectedComboSkuItems].map((item) => item.candidate.id)).size,
    [selectedComboSkuItems, selectedSkuItems],
  );
  const selectedEntryCount = selectedSkuItems.length + selectedSkuComboSummaries.length;
  const selectedComponentSkuCount =
    selectedSkuItems.length + selectedSkuComboSummaries.reduce((sum, combo) => sum + combo.items.length, 0);
  const selectedPurchaseValues = useMemo(
    () => [
      ...selectedSkuItems.map((item) => item.price),
      ...selectedSkuComboSummaries.map((combo) => sumKnownValues(combo.items.map((item) => item.price))),
    ],
    [selectedSkuComboSummaries, selectedSkuItems],
  );
  const selectedWeightValues = useMemo(
    () => [
      ...selectedSkuItems.map((item) => item.weight),
      ...selectedSkuComboSummaries.map((combo) => sumKnownValues(combo.items.map((item) => item.weight))),
    ],
    [selectedSkuComboSummaries, selectedSkuItems],
  );
  const defaultFinalSkuEntries = useMemo<FinalSkuEntry[]>(
    () => [
      ...selectedSkuComboSummaries.map((combo) => ({
        id: combo.id,
        kind: 'combo' as const,
        name: combo.displayName,
        items: combo.items,
        imageUrl: combo.items.find((item) => item.imageUrl)?.imageUrl,
        price: sumKnownValues(combo.items.map((item) => item.price)),
        weight: sumKnownValues(combo.items.map((item) => item.weight)),
      })),
      ...selectedSkuItems.map((item) => ({
        id: `single-${item.key}`,
        kind: 'single' as const,
        name: item.optionText || item.specText,
        items: [item],
        imageUrl: item.imageUrl,
        price: item.price,
        weight: item.weight,
      })),
    ],
    [selectedSkuComboSummaries, selectedSkuItems],
  );
  const finalSkuEntries = useMemo<FinalSkuEntry[]>(() => {
    const entryMap = new Map(defaultFinalSkuEntries.map((entry) => [entry.id, entry]));
    const orderedEntries = finalSkuEntryOrderIds
      .map((id) => entryMap.get(id))
      .filter((entry): entry is FinalSkuEntry => Boolean(entry));
    const orderedIdSet = new Set(orderedEntries.map((entry) => entry.id));
    const newEntries = defaultFinalSkuEntries.filter((entry) => !orderedIdSet.has(entry.id));

    return [...orderedEntries, ...newEntries];
  }, [defaultFinalSkuEntries, finalSkuEntryOrderIds]);
  const comboSourceOptions = useMemo(
    () =>
      capturedCandidates.map((candidate, candidateIndex) => {
        const skuCount = getDisplaySkuList(candidate).length;
        const labelText = `货源 ${candidateIndex + 1} · ${getCandidateLabel(candidate, candidateIndex)} · SKU ${skuCount}`;
        const candidateImageUrl = getCandidateMainImageUrl(candidate);

        return {
          value: candidate.id,
          label: (
            <span className="source-select-option">
              <span className="source-select-thumb">
                {candidateImageUrl ? (
                  <Image
                    alt={candidate.title}
                    height={34}
                    preview={false}
                    referrerPolicy="no-referrer"
                    src={candidateImageUrl}
                    width={34}
                  />
                ) : (
                  <span>1688</span>
                )}
              </span>
              <span className="source-select-copy">
                <span className="source-select-title">{labelText}</span>
                <span className="source-select-subtitle">{candidate.title}</span>
              </span>
            </span>
          ),
          title: `${labelText} ${candidate.title}`,
        };
      }),
    [capturedCandidates],
  );
  const selectedComboCandidate = useMemo(
    () => capturedCandidates.find((candidate) => candidate.id === comboSourceId) ?? capturedCandidates[0],
    [capturedCandidates, comboSourceId],
  );
  const visibleComboCandidates = useMemo(
    () => (selectedComboCandidate ? [selectedComboCandidate] : []),
    [selectedComboCandidate],
  );
  const visibleComboSkuCount = selectedComboCandidate ? getDisplaySkuList(selectedComboCandidate).length : 0;
  const visibleComboSkuItems = useMemo<SkuCombinationItem[]>(() => {
    if (!selectedComboCandidate) return [];

    const candidateIndex = capturedCandidates.findIndex((item) => item.id === selectedComboCandidate.id);
    const displaySkuList = getDisplaySkuList(selectedComboCandidate);
    const dominantPropName = getDominantSkuPropName(displaySkuList);

    return displaySkuList.map((sku, index) => ({
      key: getSkuSelectionKey(selectedComboCandidate, sku, index, dominantPropName),
      candidate: selectedComboCandidate,
      candidateIndex,
      sku,
      index,
      specText: getSkuSpecText(sku, index, dominantPropName),
      optionText: getSkuOptionText(sku, index, dominantPropName),
      imageUrl: getSkuImageUrl(selectedComboCandidate, sku, index),
      price: getSkuPriceNumber(sku, selectedComboCandidate),
      weight: getSkuWeightNumber(sku, selectedComboCandidate),
    }));
  }, [capturedCandidates, selectedComboCandidate]);
  const selectableVisibleSkuKeys = useMemo(
    () => visibleComboSkuItems.filter((item) => !selectedSkuKeySet.has(item.key)).map((item) => item.key),
    [selectedSkuKeySet, visibleComboSkuItems],
  );
  const selectableVisibleSkuKeySet = useMemo(
    () => new Set(selectableVisibleSkuKeys),
    [selectableVisibleSkuKeys],
  );
  const pendingVisibleSkuKeys = useMemo(
    () => pendingComboSkuKeys.filter((key) => selectableVisibleSkuKeySet.has(key)),
    [pendingComboSkuKeys, selectableVisibleSkuKeySet],
  );
  const allVisibleSkusChecked =
    selectableVisibleSkuKeys.length > 0 && pendingVisibleSkuKeys.length === selectableVisibleSkuKeys.length;
  const visibleSkuCheckboxIndeterminate =
    pendingVisibleSkuKeys.length > 0 && pendingVisibleSkuKeys.length < selectableVisibleSkuKeys.length;
  const comboModalSourceCandidates = useMemo(
    () => capturedCandidates.filter((candidate) => comboModalSourceIds.includes(candidate.id)),
    [capturedCandidates, comboModalSourceIds],
  );
  const comboModalAvailableSourceOptions = useMemo(
    () => comboSourceOptions.filter((option) => !comboModalSourceIds.includes(option.value)),
    [comboModalSourceIds, comboSourceOptions],
  );
  const activeComboModalCandidate = useMemo(
    () => capturedCandidates.find((candidate) => candidate.id === activeComboModalSourceId) ?? comboModalSourceCandidates[0],
    [activeComboModalSourceId, capturedCandidates, comboModalSourceCandidates],
  );
  const activeComboModalCandidateIndex = activeComboModalCandidate
    ? capturedCandidates.findIndex((candidate) => candidate.id === activeComboModalCandidate.id)
    : -1;
  const activeComboModalDisplaySkuList = useMemo(
    () => (activeComboModalCandidate ? getDisplaySkuList(activeComboModalCandidate) : []),
    [activeComboModalCandidate],
  );
  const activeComboModalDominantPropName = useMemo(
    () => getDominantSkuPropName(activeComboModalDisplaySkuList),
    [activeComboModalDisplaySkuList],
  );
  const activeComboModalSourceSkuKeys = useMemo(
    () =>
      activeComboModalCandidate
        ? activeComboModalDisplaySkuList.map((sku, index) =>
            getSkuSelectionKey(activeComboModalCandidate, sku, index, activeComboModalDominantPropName),
          )
        : [],
    [activeComboModalCandidate, activeComboModalDisplaySkuList, activeComboModalDominantPropName],
  );
  const comboModalSkuKeySet = useMemo(() => new Set(comboModalSkuKeys), [comboModalSkuKeys]);
  const activeComboModalSelectedSkuKeys = useMemo(
    () => activeComboModalSourceSkuKeys.filter((key) => comboModalSkuKeySet.has(key)),
    [activeComboModalSourceSkuKeys, comboModalSkuKeySet],
  );
  const activeComboModalAllChecked =
    activeComboModalSourceSkuKeys.length > 0 &&
    activeComboModalSelectedSkuKeys.length === activeComboModalSourceSkuKeys.length;
  const activeComboModalIndeterminate =
    activeComboModalSelectedSkuKeys.length > 0 &&
    activeComboModalSelectedSkuKeys.length < activeComboModalSourceSkuKeys.length;
  const comboModalSelectedSkuItems = useMemo(
    () => comboModalSkuKeys.map((key) => skuCombinationItemMap.get(key)).filter((item): item is SkuCombinationItem => Boolean(item)),
    [comboModalSkuKeys, skuCombinationItemMap],
  );

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

  const deleteCapturedCandidate = async (candidate: Captured1688Candidate) => {
    try {
      await deleteCaptured1688Candidate(candidate.id);

      const remainingCandidates = capturedCandidates.filter((item) => item.id !== candidate.id);
      const keepSkuKey = (key: string) => {
        const item = skuCombinationItemMap.get(key);
        return item ? item.candidate.id !== candidate.id : true;
      };

      setCapturedCandidates(remainingCandidates);
      setSelectedCandidate((current) => (current?.id === candidate.id ? remainingCandidates[0] : current));
      setComboSourceId((current) => (current === candidate.id ? remainingCandidates[0]?.id : current));
      setSelectedSkuKeys((current) => current.filter(keepSkuKey));
      setPendingComboSkuKeys((current) => current.filter(keepSkuKey));
      setComboModalSkuKeys((current) => current.filter(keepSkuKey));
      setSelectedSkuCombos((current) => current.filter((combo) => combo.skuKeys.every(keepSkuKey)));
      setComboModalSourceIds((current) => current.filter((id) => id !== candidate.id));
      setActiveComboModalSourceId((current) => (current === candidate.id ? remainingCandidates[0]?.id : current));
      setComboModalSourcePickerId((current) => (current === candidate.id ? undefined : current));
      message.success('已删除采集货源');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除采集货源失败');
      throw error;
    }
  };

  const confirmDeleteCapturedCandidate = (candidate: Captured1688Candidate) => {
    Modal.confirm({
      title: '删除已采集货源？',
      content: '删除后该货源及相关 SKU 选择会从当前商品中移除。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => deleteCapturedCandidate(candidate),
    });
  };

  const bindCaptureSession = useCallback(
    async ({ showMessage = false }: { showMessage?: boolean } = {}) => {
      try {
        await setActive1688CaptureSession(product.id);
        setCaptureStarted(true);
        onSearch();
        if (showMessage) {
          message.success('已打开采集流程，请在插件侧边栏选择加入位置');
        }
      } catch (error) {
        setCaptureStarted(false);
        if (showMessage) {
          message.error(error instanceof Error ? error.message : '绑定采集商品失败');
        }
      }
    },
    [onSearch, product.id],
  );

  useEffect(() => {
    setCaptureStarted(false);
    setCapturedCandidates([]);
    setSelectedCandidate(undefined);
    setComboSourceId(undefined);
    setSelectedSkuKeys([]);
    setSelectedSkuCombos([]);
    setPendingComboSkuKeys([]);
    setSkuComboModalOpen(false);
    setComboModalSourcePickerId(undefined);
    setComboModalSourceIds([]);
    setActiveComboModalSourceId(undefined);
    setComboModalSkuKeys([]);
    setSkuOrderModalOpen(false);
    setDraggingSkuEntryId(undefined);
    setFinalSkuEntryOrderIds([]);
    setPreviewActiveEntryId(undefined);
    setPreviewActiveImageUrl(undefined);
    setTab('search');
    void loadCapturedCandidates();
    void bindCaptureSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product.id]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadCapturedCandidates();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [loadCapturedCandidates]);

  useEffect(() => {
    setSelectedSkuKeys((current) => {
      const next = current.filter((key) => availableSkuKeySet.has(key));
      return next.length === current.length ? current : next;
    });
    setPendingComboSkuKeys((current) => {
      const next = current.filter((key) => availableSkuKeySet.has(key));
      return next.length === current.length ? current : next;
    });
    setSelectedSkuCombos((current) =>
      current
        .map((combo) => {
          const nextSkuKeys = combo.skuKeys.filter((key) => availableSkuKeySet.has(key));
          return nextSkuKeys.length === combo.skuKeys.length ? combo : { ...combo, skuKeys: nextSkuKeys };
        })
        .filter((combo) => combo.skuKeys.length > 0),
    );
    setComboModalSkuKeys((current) => {
      const next = current.filter((key) => availableSkuKeySet.has(key));
      return next.length === current.length ? current : next;
    });
  }, [availableSkuKeySet]);

  useEffect(() => {
    setFinalSkuEntryOrderIds((current) => {
      const availableIds = defaultFinalSkuEntries.map((entry) => entry.id);
      const availableIdSet = new Set(availableIds);
      const next = [
        ...current.filter((id) => availableIdSet.has(id)),
        ...availableIds.filter((id) => !current.includes(id)),
      ];

      if (next.length === current.length && next.every((id, index) => id === current[index])) return current;
      return next;
    });
  }, [defaultFinalSkuEntries]);

  useEffect(() => {
    setComboSourceId((current) => {
      if (capturedCandidates.length === 0) return undefined;
      if (current && capturedCandidates.some((candidate) => candidate.id === current)) return current;
      return capturedCandidates[0].id;
    });
    setComboModalSourceIds((current) => current.filter((id) => capturedCandidates.some((candidate) => candidate.id === id)));
    setActiveComboModalSourceId((current) =>
      current && capturedCandidates.some((candidate) => candidate.id === current) ? current : undefined,
    );
  }, [capturedCandidates]);

  useEffect(() => {
    if (comboModalSourceIds.length === 0) {
      if (activeComboModalSourceId) setActiveComboModalSourceId(undefined);
      return;
    }
    if (activeComboModalSourceId && comboModalSourceIds.includes(activeComboModalSourceId)) return;
    setActiveComboModalSourceId(comboModalSourceIds[0]);
  }, [activeComboModalSourceId, comboModalSourceIds]);

  useEffect(() => {
    if (finalSkuEntries.length === 0) {
      setPreviewActiveEntryId(undefined);
      if (tab === 'preview') setTab('combo');
      return;
    }

    if (previewActiveEntryId && finalSkuEntries.some((entry) => entry.id === previewActiveEntryId)) return;
    setPreviewActiveEntryId(finalSkuEntries[0].id);
  }, [finalSkuEntries, previewActiveEntryId, tab]);

  useEffect(() => {
    if (tab === 'preview') {
      setTab(selectedEntryCount > 0 ? 'combo' : 'search');
    }
  }, [selectedEntryCount, tab]);

  const startCapture = async () => {
    await bindCaptureSession({ showMessage: true });
    void loadCapturedCandidates();
  };

  const toggleSkuSelection = (key: string) => {
    setSelectedSkuKeys((current) => {
      if (current.includes(key)) return current.filter((item) => item !== key);
      return [...current, key];
    });
    setPendingComboSkuKeys((current) => current.filter((item) => item !== key));
  };

  const togglePendingSkuSelection = (key: string, checked: boolean) => {
    setPendingComboSkuKeys((current) => {
      if (checked) return current.includes(key) ? current : [...current, key];
      return current.filter((item) => item !== key);
    });
  };

  const toggleAllVisibleSkus = (checked: boolean) => {
    setPendingComboSkuKeys((current) => {
      const visibleKeySet = new Set(selectableVisibleSkuKeys);
      if (!checked) return current.filter((key) => !visibleKeySet.has(key));

      const next = new Set(current);
      selectableVisibleSkuKeys.forEach((key) => next.add(key));
      return Array.from(next);
    });
  };

  const addPendingSkuSelection = () => {
    const keysToAdd = pendingComboSkuKeys.filter(
      (key) => availableSkuKeySet.has(key) && !selectedSkuKeySet.has(key),
    );

    if (keysToAdd.length === 0) return;

    setSelectedSkuKeys((current) => {
      const next = new Set(current);
      keysToAdd.forEach((key) => next.add(key));
      return Array.from(next);
    });
    setPendingComboSkuKeys((current) => current.filter((key) => !keysToAdd.includes(key)));
    message.success(`已加入 ${keysToAdd.length} 个 SKU`);
  };

  const openSkuCombinationModal = () => {
    const initialSourceIds = selectedComboCandidate ? [selectedComboCandidate.id] : capturedCandidates.slice(0, 1).map((candidate) => candidate.id);
    setComboModalSourceIds(initialSourceIds);
    setActiveComboModalSourceId(initialSourceIds[0]);
    setComboModalSourcePickerId(undefined);
    setComboModalSkuKeys([]);
    setSkuComboModalOpen(true);
  };

  const closeSkuCombinationModal = () => {
    setSkuComboModalOpen(false);
    setComboModalSourcePickerId(undefined);
    setComboModalSkuKeys([]);
  };

  const addComboModalSource = () => {
    if (!comboModalSourcePickerId) return;

    setComboModalSourceIds((current) =>
      current.includes(comboModalSourcePickerId) ? current : [...current, comboModalSourcePickerId],
    );
    setActiveComboModalSourceId(comboModalSourcePickerId);
    setComboModalSourcePickerId(undefined);
  };

  const removeComboModalSource = (sourceId: string) => {
    const nextSourceIds = comboModalSourceIds.filter((id) => id !== sourceId);
    const nextSourceIdSet = new Set(nextSourceIds);

    setComboModalSourceIds(nextSourceIds);
    setComboModalSkuKeys((current) =>
      current.filter((key) => {
        const item = skuCombinationItemMap.get(key);
        return item ? nextSourceIdSet.has(item.candidate.id) : false;
      }),
    );
    setActiveComboModalSourceId((current) => (current === sourceId ? nextSourceIds[0] : current));
  };

  const toggleComboModalSkuSelection = (key: string, checked: boolean) => {
    setComboModalSkuKeys((current) => {
      if (checked) return current.includes(key) ? current : [...current, key];
      return current.filter((item) => item !== key);
    });
  };

  const toggleAllComboModalSourceSkus = (candidate: Captured1688Candidate, checked: boolean) => {
    const candidateIndex = capturedCandidates.findIndex((item) => item.id === candidate.id);
    const sourceSkuKeys = getCandidateSkuKeys(candidate);
    const sourceSkuKeySet = new Set(sourceSkuKeys);

    setComboModalSkuKeys((current) => {
      if (!checked) return current.filter((key) => !sourceSkuKeySet.has(key));

      const next = new Set(current);
      sourceSkuKeys.forEach((key) => next.add(key));
      return Array.from(next);
    });

    if (candidateIndex >= 0) setSelectedCandidate(candidate);
  };

  const addSkuCombination = () => {
    const keysToAdd = comboModalSkuKeys.filter((key) => availableSkuKeySet.has(key));
    const comboItems = keysToAdd
      .map((key) => skuCombinationItemMap.get(key))
      .filter((item): item is SkuCombinationItem => Boolean(item));

    if (comboItems.length < 2) {
      message.warning('SKU 组合至少需要选择 2 个 SKU');
      return;
    }

    const comboName = getSkuCombinationDisplayName(comboItems) || `SKU组合 ${selectedSkuCombos.length + 1}`;

    setSelectedSkuCombos((current) => [
      ...current,
      {
        id: `sku-combo-${Date.now()}-${current.length + 1}`,
        name: comboName,
        skuKeys: keysToAdd,
      },
    ]);
    setSkuComboModalOpen(false);
    setComboModalSkuKeys([]);
    message.success(`已添加 ${comboName}`);
  };

  const removeSkuCombination = (comboId: string) => {
    setSelectedSkuCombos((current) => current.filter((combo) => combo.id !== comboId));
  };

  const reorderFinalSkuEntry = (sourceId: string, targetId: string) => {
    if (sourceId === targetId) return;

    setFinalSkuEntryOrderIds((current) => {
      const availableIds = finalSkuEntries.map((entry) => entry.id);
      const availableIdSet = new Set(availableIds);
      const orderedIds = [
        ...current.filter((id) => availableIdSet.has(id)),
        ...availableIds.filter((id) => !current.includes(id)),
      ];
      const sourceIndex = orderedIds.indexOf(sourceId);
      const targetIndex = orderedIds.indexOf(targetId);

      if (sourceIndex < 0 || targetIndex < 0) return current;

      const next = [...orderedIds];
      const [movedId] = next.splice(sourceIndex, 1);
      next.splice(targetIndex, 0, movedId);

      return next;
    });
  };

  const recordSelectedSkuLinks = () => {
    if (finalSkuEntries.length === 0) {
      message.warning('请先选择 SKU，再录入链接列表');
      return;
    }

    const recordId = `link-entry-${product.id}-${Date.now()}`;
    const createdAt = new Date().toISOString();
    const normalizedProductImageGenerationCount = normalizeProductImageGenerationCount(productImageGenerationCount);
    const sourceMap = new Map<string, LinkListSource>();
    finalSkuEntries.forEach((entry) => {
      entry.items.forEach((item) => {
        const candidate = item.candidate;
        if (sourceMap.has(candidate.id)) return;
        sourceMap.set(candidate.id, {
          id: candidate.id,
          title: candidate.title,
          productUrl: candidate.product_url,
          shopName: candidate.shop_name || undefined,
          shopUrl: candidate.shop_url || undefined,
          imageUrl: getCandidateMainImageUrl(candidate),
        });
      });
    });
    const sourceLinks = Array.from(sourceMap.values());
    const productMaterialImageUrls = uniqueStrings(
      finalSkuEntries.flatMap((entry) => entry.items.flatMap((item) => getCandidateImageUrls(item.candidate))),
    );
    const mainImageUrl =
      product.mainImageUrl ||
      finalSkuEntries.map((entry) => entry.imageUrl).find(Boolean) ||
      sourceLinks.map((source) => source.imageUrl).find(Boolean);
    const mainImageAssetId = `${recordId}-main-image`;
    const styleProfileId = `${recordId}-style-profile`;
    const productMaterialImageAssets: LinkListImageAsset[] = productMaterialImageUrls.map((imageUrl, index) => ({
      id: `${recordId}-material-image-${index + 1}`,
      role: 'product-material',
      sourceUrl: imageUrl,
      displayUrl: imageUrl,
      alt: `${product.title} material image ${index + 1}`,
    }));
    const carouselAssets = [
      { id: mainImageAssetId },
      ...productMaterialImageAssets.map((asset) => ({ id: asset.id })),
    ].slice(0, normalizedProductImageGenerationCount);
    const imageSlots: LinkListImageSlot[] = [
      {
        id: `${recordId}-slot-main`,
        type: 'main',
        order: 0,
        assetId: mainImageAssetId,
      },
      ...Array.from({ length: normalizedProductImageGenerationCount }, (_, index) => ({
        id: `${recordId}-slot-carousel-${index + 1}`,
        type: 'carousel' as const,
        order: index + 1,
        assetId: carouselAssets[index]?.id,
      })),
    ];

    onRecordLinkEntry({
      schemaVersion: 3,
      id: recordId,
      createdAt,
      productId: product.id,
      productTitle: product.title,
      productTitleEn: product.titleEn,
      category: product.category,
      categoryLevel1: product.categoryLevel1,
      categoryLevel2: product.categoryLevel2,
      categoryPath: product.categoryPath || product.category,
      mainImage: {
        id: mainImageAssetId,
        role: 'product-main',
        sourceUrl: mainImageUrl,
        displayUrl: mainImageUrl,
        alt: product.title,
      },
      productMaterialImages: productMaterialImageUrls.map((imageUrl, index) => ({
        id: `${recordId}-material-image-${index + 1}`,
        role: 'product-material',
        sourceUrl: imageUrl,
        displayUrl: imageUrl,
        alt: `${product.title} 素材图 ${index + 1}`,
      })),
      imageSlots,
      productImageGenerationCount: normalizedProductImageGenerationCount,
      styleProfile: {
        id: styleProfileId,
        name: '统一 SKU 商品图风格',
        provider: DEFAULT_IMAGE_PROVIDER,
        prompt: DEFAULT_STYLE_PROMPT,
        referenceImageAssetId: mainImageAssetId,
      },
      productImageUrl: product.mainImageUrl,
      productSourceUrl: product.sourceUrl,
      sourceLinks,
      skuEntries: finalSkuEntries.map((entry, index) => {
        const entryImageUrl = entry.imageUrl || entry.items.map((item) => item.imageUrl).find(Boolean);
        const imageAssetId = `${recordId}-sku-image-${index + 1}`;
        const componentSummary = entry.items
          .map((item) => `${item.optionText || item.specText}（${getCandidateLabel(item.candidate, item.candidateIndex)}）`)
          .join(' + ');
        const skuPrompt =
          entry.kind === 'combo'
            ? `先分析，再执行。先分析销售 SKU「${entry.name}」的组合关系和所有组件：${componentSummary}。执行时必须把这些组件放在同一张 SKU 图中，主体清楚、不遮挡、不融合成错误商品，并与商品 8 张主图保持统一画风。`
            : `先分析，再执行。先分析销售 SKU「${entry.name}」的真实规格、颜色、数量和细节：${componentSummary}。执行时生成与商品 8 张主图一致的电商 SKU 图，保留 SKU 可识别特征。`;
        return {
          id: entry.id,
          order: index + 1,
          kind: entry.kind,
          name: entry.name,
          imageAsset: {
            id: imageAssetId,
            role: 'sales-sku',
            sourceUrl: entryImageUrl,
            displayUrl: entryImageUrl,
            alt: entry.name,
          },
          imageEditTask: {
            id: `${recordId}-image-task-${index + 1}`,
            provider: DEFAULT_IMAGE_PROVIDER,
            mode: 'image-to-image',
            status: 'draft',
            inputImageUrl: entryImageUrl,
            prompt: skuPrompt,
            stylePrompt: DEFAULT_STYLE_PROMPT,
            referenceMainImageAssetId: mainImageAssetId,
            targetSkuEntryId: entry.id,
            workflow: {
              chatgptModel: 'gpt-image',
            },
            createdAt,
          },
          imageUrl: entryImageUrl,
          price: entry.price,
          weight: entry.weight,
          sourceSkuLinks: entry.items.map((item) => ({
            sourceId: item.candidate.id,
            sourceTitle: getCandidateLabel(item.candidate, item.candidateIndex),
            sourceProductUrl: item.candidate.product_url,
            sourceSkuId: item.sku.sku_id,
            sourceSkuKey: item.key,
            specText: item.specText,
            optionText: item.optionText || item.specText,
            imageUrl: item.imageUrl,
          })),
          componentSkus: entry.items.map((item) => ({
            name: item.optionText || item.specText,
            specText: item.specText,
            sourceId: item.candidate.id,
            sourceSkuId: item.sku.sku_id,
            sourceSkuKey: item.key,
            sourceTitle: getCandidateLabel(item.candidate, item.candidateIndex),
            sourceUrl: item.candidate.product_url,
            sourceImageUrl: getCandidateMainImageUrl(item.candidate),
            imageUrl: item.imageUrl,
            rawSpecs: item.sku.specs,
          })),
        };
      }),
      componentSkuCount: selectedComponentSkuCount,
    });
  };

  const open1688 = () => {
    window.open(build1688TitleSearchUrl(product), '_blank', 'noopener,noreferrer');
  };

  const selectedCandidateMainImageUrl = selectedCandidate ? getCandidateMainImageUrl(selectedCandidate) : undefined;
  const activePreviewSkuEntry = finalSkuEntries.find((entry) => entry.id === previewActiveEntryId) ?? finalSkuEntries[0];
  const previewMainImageUrl =
    product.mainImageUrl ||
    selectedCandidateMainImageUrl ||
    capturedCandidates.map((candidate) => getCandidateMainImageUrl(candidate)).find(Boolean);
  const previewGalleryUrls = uniqueStrings([
    previewMainImageUrl,
    product.mainImageUrl,
    selectedCandidateMainImageUrl,
    ...capturedCandidates.flatMap((candidate) => getCandidateImageUrls(candidate).slice(0, 2)),
  ]);
  const previewDisplayedImageUrl =
    previewActiveImageUrl && previewGalleryUrls.includes(previewActiveImageUrl)
      ? previewActiveImageUrl
      : previewMainImageUrl;
  const previewTitle = product.title || product.titleEn || activePreviewSkuEntry?.items[0]?.candidate.title || '商品标题';

  return (
    <div className="sourcing-panel">
      <Tabs
        activeKey={tab}
        items={[
          { key: 'search', label: '1688 采集' },
          { key: 'recommend', label: '智能推荐' },
          {
            key: 'combo',
            label: selectedEntryCount > 0 ? `SKU 选择 (${selectedEntryCount})` : 'SKU 选择',
            disabled: capturedCandidates.length === 0,
          },
          {
            key: 'preview',
            label: '商品预览',
            disabled: selectedEntryCount === 0,
          },
        ].filter((item) => item.key !== 'preview')}
        onChange={(key) => setTab(key as PanelTab)}
      />

      {tab === 'search' ? (
        <div className="sourcing-search">
          <div className="search-row">
            <Input value={keyword} readOnly />
            <Button onClick={open1688}>打开 1688</Button>
            <Button type="primary" onClick={startCapture}>
              刷新货源素材
            </Button>
          </div>

          <Card className="capture-guide" size="small">
            <Space direction="vertical" size={6}>
              <Text strong>采集流程</Text>
              <Text type="secondary">1. 点击打开 1688，或手动进入任意 1688 商品详情页。</Text>
              <Text type="secondary">2. 在 Chrome 采集器侧边栏预抓当前页。</Text>
              <Text type="secondary">3. 在插件里点击“加入采集列表”，再从采集列表中选择加入商品列表或货源素材。</Text>
            </Space>
          </Card>

          {capturedCandidates.length === 0 ? (
            <Empty
              className="sourcing-empty"
              description="还没有加入当前商品的 1688 货源素材。请在插件侧边栏先加入采集列表，再选择加入货源素材。"
            >
              <Space>
                <Button loading={loadingCandidates} onClick={loadCapturedCandidates} type="primary">
                  刷新货源素材
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
                      setComboSourceId(candidate.id);
                      setPendingComboSkuKeys([]);
                      setTab('combo');
                    }}
                  >
                    <div className="captured-candidate-layout">
                      <div className="candidate-image candidate-image-real">
                        {getCandidateImageUrls(candidate)[0] ? (
                          <Image
                            alt={candidate.title}
                            height={76}
                            preview={false}
                            referrerPolicy="no-referrer"
                            src={getCandidateImageUrls(candidate)[0]}
                            width={76}
                          />
                        ) : (
                          <span>1688 图</span>
                        )}
                      </div>
                      <div className="captured-candidate-content">
                        <div className="captured-candidate-head">
                          <div className="candidate-title">{candidate.title}</div>
                          <Button
                            className="captured-candidate-delete"
                            danger
                            size="small"
                            onClick={(event) => {
                              event.stopPropagation();
                              confirmDeleteCapturedCandidate(candidate);
                            }}
                          >
                            删除
                          </Button>
                        </div>
                        <div className="candidate-meta-line">
                          <Text strong className="price-red">
                            {formatPrice(candidate)}
                          </Text>
                          {rawNumber(candidate, 'unit_price_with_shipping') !== undefined ? (
                            <Tag color="red">含运费 {formatMoneyValue(rawNumber(candidate, 'unit_price_with_shipping'))}</Tag>
                          ) : null}
                          {rawNumber(candidate, 'weight_kg') !== undefined ? (
                            <Tag color="purple">重量 {formatWeightValue(rawNumber(candidate, 'weight_kg'))}</Tag>
                          ) : null}
                          <Tag color="blue">SKU {getDisplaySkuList(candidate).length}</Tag>
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
      ) : tab === 'recommend' ? (
        <Smart1688KeywordRecommendations product={product} />
      ) : tab === 'combo' ? (
        <div className="sku-combo-page">
          <Card
            className="sku-combo-source-card"
            extra={
              <Space className="sku-source-picker" size={8}>
                <Text type="secondary">货源</Text>
                <Select
                  className="sku-source-select"
                  optionFilterProp="title"
                  options={comboSourceOptions}
                  placeholder="选择货源"
                  popupMatchSelectWidth={false}
                  showSearch
                  value={selectedComboCandidate?.id}
                  onChange={(value) => {
                    setComboSourceId(value);
                    setPendingComboSkuKeys([]);
                    const candidate = capturedCandidates.find((item) => item.id === value);
                    if (candidate) setSelectedCandidate(candidate);
                  }}
                />
                <Tag color="blue">当前 SKU {visibleComboSkuCount}</Tag>
                <Button onClick={openSkuCombinationModal}>添加 SKU 组合</Button>
              </Space>
            }
            title="从已采集货源选择 SKU"
          >
            {skuCombinationItems.length === 0 ? (
              <Empty description="还没有可选择的 SKU。先采集几个 1688 货源。" />
            ) : (
              <>
                <div className="sku-combo-source-list">
                  {visibleComboCandidates.map((candidate) => {
                    const candidateIndex = capturedCandidates.findIndex((item) => item.id === candidate.id);
                    const displaySkuList = getDisplaySkuList(candidate);
                    const dominantPropName = getDominantSkuPropName(displaySkuList);
                    const candidateImageUrl = getCandidateMainImageUrl(candidate);

                    return (
                      <div className="sku-source-group" key={candidate.id}>
                        <div className="sku-source-head sku-source-summary">
                          <div className="candidate-image candidate-image-real sku-source-main-image">
                            {candidateImageUrl ? (
                              <Image
                                alt={candidate.title}
                                height={76}
                                preview={false}
                                referrerPolicy="no-referrer"
                                src={candidateImageUrl}
                                width={76}
                              />
                            ) : (
                              <span>1688 图</span>
                            )}
                          </div>
                          <div className="sku-source-head-content">
                            <div className="captured-candidate-head">
                              <div className="candidate-title">{candidate.title}</div>
                              <Button
                                className="captured-candidate-delete"
                                danger
                                size="small"
                                onClick={() => confirmDeleteCapturedCandidate(candidate)}
                              >
                                删除
                              </Button>
                            </div>
                            <div className="candidate-meta-line">
                              <Text strong className="price-red">
                                {formatPrice(candidate)}
                              </Text>
                              {rawNumber(candidate, 'unit_price_with_shipping') !== undefined ? (
                                <Tag color="red">含运费 {formatMoneyValue(rawNumber(candidate, 'unit_price_with_shipping'))}</Tag>
                              ) : null}
                              {rawNumber(candidate, 'weight_kg') !== undefined ? (
                                <Tag color="purple">重量 {formatWeightValue(rawNumber(candidate, 'weight_kg'))}</Tag>
                              ) : null}
                              <Tag color="blue">SKU {displaySkuList.length}</Tag>
                              {candidate.moq ? <Tag color="gold">MOQ {candidate.moq}</Tag> : null}
                            </div>
                            <Text type="secondary">{candidate.shop_name || getCandidateLabel(candidate, candidateIndex)}</Text>
                          </div>
                        </div>
                        <div className="sku-bulk-toolbar">
                          <Checkbox
                            checked={allVisibleSkusChecked}
                            disabled={selectableVisibleSkuKeys.length === 0}
                            indeterminate={visibleSkuCheckboxIndeterminate}
                            onChange={(event) => toggleAllVisibleSkus(event.target.checked)}
                          >
                            全选当前货源
                          </Checkbox>
                          <Text type="secondary">已勾选 {pendingVisibleSkuKeys.length} 个</Text>
                          <Button
                            disabled={pendingVisibleSkuKeys.length === 0}
                            type="primary"
                            onClick={addPendingSkuSelection}
                          >
                            加入已选 SKU
                          </Button>
                        </div>
                        <div className="sku-list">
                          {displaySkuList.map((sku, index) => {
                            const skuKey = getSkuSelectionKey(candidate, sku, index, dominantPropName);
                            const selected = selectedSkuKeySet.has(skuKey);
                            const pending = pendingComboSkuKeys.includes(skuKey);
                            const skuImageUrl = getSkuImageUrl(candidate, sku, index);

                            return (
                              <div
                                className={`sku-row sku-row-selectable ${selected ? 'sku-row-selected' : ''} ${pending ? 'sku-row-pending' : ''}`}
                                key={skuKey}
                                onClick={() => {
                                  if (!selected) togglePendingSkuSelection(skuKey, !pending);
                                }}
                              >
                                <div className="sku-main">
                                  <Checkbox
                                    aria-label={`选择 ${getSkuSpecText(sku, index, dominantPropName)}`}
                                    checked={pending}
                                    className="sku-check"
                                    disabled={selected}
                                    onClick={(event) => event.stopPropagation()}
                                    onChange={(event) => togglePendingSkuSelection(skuKey, event.target.checked)}
                                  />
                                  <div className="sku-image">
                                    {skuImageUrl ? (
                                      <Image
                                        alt={getSkuSpecText(sku, index, dominantPropName)}
                                        height={44}
                                        preview
                                        referrerPolicy="no-referrer"
                                        src={skuImageUrl}
                                        width={44}
                                      />
                                    ) : (
                                      <span>SKU</span>
                                    )}
                                  </div>
                                  <div className="sku-text">
                                    <Text strong>{getSkuSpecText(sku, index, dominantPropName)}</Text>
                                    <Text type="secondary">{getCandidateLabel(candidate, candidateIndex)}</Text>
                                  </div>
                                </div>
                                <div className="sku-meta">
                                  {formatSkuPrice(sku) ? (
                                    <Text strong className="price-red">
                                      {formatSkuPrice(sku)}
                                    </Text>
                                  ) : null}
                                  {formatSkuStock(sku) ? <Text type="secondary">{formatSkuStock(sku)}</Text> : null}
                                  {formatSkuWeight(sku, candidate) ? (
                                    <Text type="secondary">重量 {formatSkuWeight(sku, candidate)}</Text>
                                  ) : null}
                                  {selected ? <Tag color="blue">已加入</Tag> : null}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </Card>

          <Card
            className="sku-combo-result-card"
            extra={
              <Space size={8}>
                <Button disabled={finalSkuEntries.length === 0} size="small" onClick={() => setSkuOrderModalOpen(true)}>
                  SKU顺序预览
                </Button>
                <Button
                  disabled={selectedEntryCount === 0}
                  size="small"
                  onClick={() => {
                    setSelectedSkuKeys([]);
                    setSelectedSkuCombos([]);
                    setPendingComboSkuKeys([]);
                    setFinalSkuEntryOrderIds([]);
                    setSkuOrderModalOpen(false);
                  }}
                >
                  清空
                </Button>
              </Space>
            }
            title="已选 SKU"
          >
            {selectedEntryCount === 0 ? (
              <Empty description="先在左侧选择货源，再勾选 SKU 加入这里。" />
            ) : (
              <>
                <Space className="sku-combo-result-actions sku-combo-result-actions-top" direction="vertical" size={8}>
                  <Button block onClick={() => setTab('preview')}>
                    预览商品页
                  </Button>
                  <Button
                    block
                    className="sku-combo-confirm"
                    type="primary"
                    onClick={recordSelectedSkuLinks}
                  >
                    录入链接列表
                  </Button>
                </Space>
                <div className="sku-combo-summary">
                  <div>
                    <Text type="secondary">已选项</Text>
                    <strong>{selectedEntryCount}</strong>
                  </div>
                  <div>
                    <Text type="secondary">SKU 数</Text>
                    <strong>{selectedComponentSkuCount}</strong>
                  </div>
                  <div>
                    <Text type="secondary">货源数</Text>
                    <strong>{selectedSourceCount}</strong>
                  </div>
                  <div>
                    <Text type="secondary">采购价范围</Text>
                    <strong>{formatNumberRange(selectedPurchaseValues, (value) => `¥${value.toFixed(2)}`)}</strong>
                  </div>
                  <div>
                    <Text type="secondary">重量范围</Text>
                    <strong>{formatPositiveNumberRange(selectedWeightValues, (value) => `${value} kg`)}</strong>
                  </div>
                  <div>
                    <Text type="secondary">商品图数量</Text>
                    <InputNumber
                      max={MAX_PRODUCT_IMAGE_GENERATION_COUNT}
                      min={MIN_PRODUCT_IMAGE_GENERATION_COUNT}
                      size="small"
                      value={productImageGenerationCount}
                      onChange={(value) => setProductImageGenerationCount(normalizeProductImageGenerationCount(value))}
                    />
                  </div>
                </div>
                {selectedSkuComboSummaries.length > 0 ? (
                  <div className="sku-combo-group-list">
                    {selectedSkuComboSummaries.map((combo) => (
                      <div className="sku-combo-group-card" key={combo.id}>
                        <div className="sku-combo-group-head">
                          <div>
                            <Text strong>{combo.displayName}</Text>
                            <Text type="secondary"> · {combo.items.length} 个 SKU</Text>
                          </div>
                          <Space size={6}>
                            <Tag color="purple">SKU组合</Tag>
                            <Button size="small" onClick={() => removeSkuCombination(combo.id)}>
                              移除组合
                            </Button>
                          </Space>
                        </div>
                        <div className="sku-combo-picked-list">
                          {combo.items.map((item) => (
                            <div className="sku-combo-picked-row" key={item.key}>
                              <div className="sku-main">
                                <div className="sku-image">
                                  {item.imageUrl ? (
                                    <Image
                                      alt={item.specText}
                                      height={44}
                                      preview
                                      referrerPolicy="no-referrer"
                                      src={item.imageUrl}
                                      width={44}
                                    />
                                  ) : (
                                    <span>SKU</span>
                                  )}
                                </div>
                                <div className="sku-text">
                                  <Text strong>{item.optionText}</Text>
                                  <Text type="secondary">{getCandidateLabel(item.candidate, item.candidateIndex)}</Text>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
                {selectedSkuItems.length > 0 ? (
                  <div className="sku-combo-picked-list">
                    {selectedSkuItems.map((item) => (
                      <div className="sku-combo-picked-row" key={item.key}>
                        <div className="sku-main">
                          <div className="sku-image">
                            {item.imageUrl ? (
                              <Image
                                alt={item.specText}
                                height={44}
                                preview
                                referrerPolicy="no-referrer"
                                src={item.imageUrl}
                                width={44}
                              />
                            ) : (
                              <span>SKU</span>
                            )}
                          </div>
                          <div className="sku-text">
                            <Text strong>{item.optionText}</Text>
                            <Text type="secondary">{getCandidateLabel(item.candidate, item.candidateIndex)}</Text>
                          </div>
                        </div>
                        <Button size="small" onClick={() => toggleSkuSelection(item.key)}>
                          移除
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : null}
                <Space className="sku-combo-result-actions" direction="vertical" size={8}>
                  <Button block onClick={() => setTab('preview')}>
                    预览商品页
                  </Button>
                  <Button
                    block
                    className="sku-combo-confirm"
                    type="primary"
                    onClick={recordSelectedSkuLinks}
                  >
                    录入链接列表
                  </Button>
                </Space>
              </>
            )}
          </Card>
        </div>
      ) : tab === 'preview' ? (
        <div className="temu-preview-page">
          {finalSkuEntries.length === 0 ? (
            <Empty description="先选择 SKU，再查看商品页预览。" />
          ) : (
            <div className="temu-preview-shell">
              <div className="temu-preview-gallery">
                <div className="temu-preview-thumbs">
                  {previewGalleryUrls.slice(0, 10).map((imageUrl, index) => (
                    <button
                      aria-label={`主图 ${index + 1}`}
                      className={`temu-preview-thumb ${imageUrl === previewDisplayedImageUrl ? 'temu-preview-thumb-active' : ''}`}
                      key={`${imageUrl}-${index}`}
                      type="button"
                      onClick={() => setPreviewActiveImageUrl(imageUrl)}
                    >
                      <Image
                        alt={`主图 ${index + 1}`}
                        height={62}
                        preview={false}
                        referrerPolicy="no-referrer"
                        src={imageUrl}
                        width={62}
                      />
                    </button>
                  ))}
                </div>
                <div className="temu-preview-main-image">
                  {previewDisplayedImageUrl ? (
                    <Image
                      alt={previewTitle}
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
              </div>

              <div className="temu-preview-info">
                <Typography.Title className="temu-preview-title" level={3}>
                  {previewTitle}
                </Typography.Title>
                <div className="temu-preview-section">
                  <Text strong className="temu-preview-section-title">
                    SKU
                  </Text>
                  <div className="temu-preview-sku-grid">
                    {finalSkuEntries.map((entry) => {
                      const active = activePreviewSkuEntry?.id === entry.id;

                      return (
                        <button
                          className={`temu-preview-sku-option ${active ? 'temu-preview-sku-option-active' : ''}`}
                          key={entry.id}
                          type="button"
                          onClick={() => {
                            setPreviewActiveEntryId(entry.id);
                            if (entry.imageUrl) setPreviewActiveImageUrl(entry.imageUrl);
                          }}
                        >
                          <span className="temu-preview-sku-image">
                            {entry.imageUrl ? (
                              <Image
                                alt={entry.name}
                                height={44}
                                preview={false}
                                referrerPolicy="no-referrer"
                                src={entry.imageUrl}
                                width={44}
                              />
                            ) : (
                              'SKU'
                            )}
                          </span>
                          <span className="temu-preview-sku-name">{entry.name}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : selectedCandidate ? (
        <div className="candidate-detail-page">
          <div className="detail-gallery">
            <div className="detail-hero-image detail-hero-image-real">
              {selectedCandidateMainImageUrl ? (
                <Image
                  alt={selectedCandidate.title}
                  height="100%"
                  preview={false}
                  referrerPolicy="no-referrer"
                  src={selectedCandidateMainImageUrl}
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
              <Tag color="green">SKU {getDisplaySkuList(selectedCandidate).length}</Tag>
              {selectedCandidate.offer_id ? <Tag>Offer {selectedCandidate.offer_id}</Tag> : null}
            </Space>
            <div className="detail-metrics">
              <div>
                <Text type="secondary">采购价</Text>
                <strong className="price-large">{formatPrice(selectedCandidate)}</strong>
              </div>
              <div>
                <Text type="secondary">含运费单件</Text>
                <strong>{formatMoneyValue(rawNumber(selectedCandidate, 'unit_price_with_shipping'))}</strong>
              </div>
              <div>
                <Text type="secondary">重量</Text>
                <strong>{formatWeightValue(rawNumber(selectedCandidate, 'weight_kg'))}</strong>
              </div>
              <div>
                <Text type="secondary">运费</Text>
                <strong>{formatMoneyValue(rawNumber(selectedCandidate, 'shipping_fee'))}</strong>
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
            <Card
              extra={
                <Text type="secondary">
                  主图 {getCandidateImageUrls(selectedCandidate).length} / SKU 图{' '}
                  {getDisplaySkuList(selectedCandidate).filter((sku) => sku.image_url).length}
                </Text>
              }
              size="small"
              title="SKU 数据"
            >
              {getDisplaySkuList(selectedCandidate).length === 0 ? (
                <Text type="secondary">插件暂未采集到 SKU 明细。</Text>
              ) : (
                <div className="sku-list">
                  {getDisplaySkuList(selectedCandidate).map((sku, index, displaySkuList) => {
                    const dominantPropName = getDominantSkuPropName(displaySkuList);
                    const skuImageUrl = getSkuImageUrl(selectedCandidate, sku, index);
                    const skuKey = getSkuSelectionKey(selectedCandidate, sku, index, dominantPropName);
                    const selected = selectedSkuKeySet.has(skuKey);
                    return (
                      <div className={`sku-row sku-row-selectable ${selected ? 'sku-row-selected' : ''}`} key={skuKey}>
                        <div className="sku-main">
                          <div className="sku-image">
                            {skuImageUrl ? (
                              <Image
                                alt={getSkuSpecText(sku, index, dominantPropName)}
                                height={44}
                                preview
                                referrerPolicy="no-referrer"
                                src={skuImageUrl}
                                width={44}
                              />
                            ) : (
                              <span>SKU</span>
                            )}
                          </div>
                          <div className="sku-text">
                            <Text strong>{getSkuSpecText(sku, index, dominantPropName)}</Text>
                          </div>
                        </div>
                        <div className="sku-meta">
                          {formatSkuPrice(sku) ? (
                            <Text strong className="price-red">
                              {formatSkuPrice(sku)}
                            </Text>
                          ) : null}
                          {formatSkuStock(sku) ? <Text type="secondary">{formatSkuStock(sku)}</Text> : null}
                          {formatSkuWeight(sku, selectedCandidate) ? (
                            <Text type="secondary">重量 {formatSkuWeight(sku, selectedCandidate)}</Text>
                          ) : null}
                          <Button size="small" type={selected ? 'primary' : 'default'} onClick={() => toggleSkuSelection(skuKey)}>
                            {selected ? '已加入' : '加入已选'}
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
            <Space className="detail-actions">
              <Button onClick={() => setTab('search')}>返回采集列表</Button>
              <Button onClick={() => window.open(selectedCandidate.product_url, '_blank', 'noopener,noreferrer')}>
                打开 1688 原页
              </Button>
              <Button disabled={selectedEntryCount === 0} onClick={() => setTab('combo')}>
                查看已选 SKU
              </Button>
              <Button type="primary">确认使用该货源</Button>
            </Space>
          </div>
        </div>
      ) : null}
      <Modal
        footer={
          <Button type="primary" onClick={() => setSkuOrderModalOpen(false)}>
            完成
          </Button>
        }
        open={skuOrderModalOpen}
        title="SKU顺序预览"
        width={720}
        onCancel={() => {
          setSkuOrderModalOpen(false);
          setDraggingSkuEntryId(undefined);
        }}
      >
        <div className="sku-order-modal-body">
          <Text strong className="sku-order-section-title">
            SKU
          </Text>
          {finalSkuEntries.length === 0 ? (
            <Empty description="先添加 SKU，再调整顺序。" />
          ) : (
            <div
              className="sku-order-option-grid"
              onMouseLeave={() => setDraggingSkuEntryId(undefined)}
              onMouseUp={() => setDraggingSkuEntryId(undefined)}
            >
              {finalSkuEntries.map((entry) => {
                const active = activePreviewSkuEntry?.id === entry.id;

                return (
                  <button
                    className={`sku-order-option ${active ? 'sku-order-option-active' : ''} ${
                      draggingSkuEntryId === entry.id ? 'sku-order-option-dragging' : ''
                    }`}
                    type="button"
                    onClick={() => {
                      setPreviewActiveEntryId(entry.id);
                      if (entry.imageUrl) setPreviewActiveImageUrl(entry.imageUrl);
                    }}
                  draggable
                  key={entry.id}
                  onDragEnd={() => setDraggingSkuEntryId(undefined)}
                  onDragEnter={() => {
                    if (draggingSkuEntryId) reorderFinalSkuEntry(draggingSkuEntryId, entry.id);
                  }}
                  onDragOver={(event) => {
                    event.preventDefault();
                    event.dataTransfer.dropEffect = 'move';
                  }}
                  onDragStart={(event) => {
                    setDraggingSkuEntryId(entry.id);
                    event.dataTransfer.effectAllowed = 'move';
                    event.dataTransfer.setData('text/plain', entry.id);
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    const sourceId = event.dataTransfer.getData('text/plain') || draggingSkuEntryId;
                    if (sourceId) reorderFinalSkuEntry(sourceId, entry.id);
                    setDraggingSkuEntryId(undefined);
                  }}
                  onMouseDown={() => setDraggingSkuEntryId(entry.id)}
                  onMouseEnter={(event) => {
                    if (event.buttons === 1 && draggingSkuEntryId) reorderFinalSkuEntry(draggingSkuEntryId, entry.id);
                  }}
                >
                  <span className="sku-order-option-image">
                    {entry.imageUrl ? (
                      <Image
                        alt={entry.name}
                        height={40}
                        preview={false}
                        referrerPolicy="no-referrer"
                        src={entry.imageUrl}
                        width={40}
                      />
                    ) : (
                      'SKU'
                    )}
                  </span>
                  <span className="sku-order-option-name">{entry.name}</span>
                </button>
                );
              })}
            </div>
          )}
        </div>
      </Modal>
      <Modal
        destroyOnHidden
        okButtonProps={{ disabled: comboModalSkuKeys.length < 2 }}
        okText="添加组合"
        open={skuComboModalOpen}
        title="添加 SKU 组合"
        width={880}
        onCancel={closeSkuCombinationModal}
        onOk={addSkuCombination}
      >
        <div className="sku-combo-modal-body">
          <div className="sku-combo-modal-picker">
            <Text strong>添加货源</Text>
            <div className="sku-combo-modal-add-source">
              <Select
                className="sku-combo-modal-source-select"
                optionFilterProp="title"
                options={comboModalAvailableSourceOptions}
                placeholder="选择要添加的货源"
                value={comboModalSourcePickerId}
                onChange={setComboModalSourcePickerId}
              />
              <Button disabled={!comboModalSourcePickerId} type="primary" onClick={addComboModalSource}>
                添加货源
              </Button>
            </div>
          </div>
          <Space wrap>
            <Tag color="blue">已选货源 {comboModalSourceIds.length}</Tag>
            <Tag color="purple">组合内 SKU {comboModalSelectedSkuItems.length}</Tag>
          </Space>

          {comboModalSourceCandidates.length === 0 ? (
            <Empty description="先添加一个或多个货源，再勾选要组合的 SKU。" />
          ) : (
            <>
              <div className="sku-combo-modal-source-tabs">
                {comboModalSourceCandidates.map((candidate) => {
                  const candidateIndex = capturedCandidates.findIndex((item) => item.id === candidate.id);
                  const sourceSkuKeys = getCandidateSkuKeys(candidate);
                  const selectedSourceSkuCount = sourceSkuKeys.filter((key) => comboModalSkuKeySet.has(key)).length;
                  const active = activeComboModalCandidate?.id === candidate.id;
                  const candidateImageUrl = getCandidateMainImageUrl(candidate);

                  return (
                    <div
                      className={`sku-combo-modal-source-chip ${active ? 'sku-combo-modal-source-chip-active' : ''}`}
                      key={candidate.id}
                    >
                      <button
                        className="sku-combo-modal-source-tab"
                        type="button"
                        onClick={() => setActiveComboModalSourceId(candidate.id)}
                      >
                        <span className="source-select-thumb sku-combo-modal-source-thumb">
                          {candidateImageUrl ? (
                            <Image
                              alt={candidate.title}
                              height={34}
                              preview={false}
                              referrerPolicy="no-referrer"
                              src={candidateImageUrl}
                              width={34}
                            />
                          ) : (
                            <span>1688</span>
                          )}
                        </span>
                        <span className="sku-combo-modal-source-name">
                          {`货源 ${candidateIndex + 1} · ${getCandidateLabel(candidate, candidateIndex)}`}
                        </span>
                        <span className="sku-combo-modal-source-count">已选 {selectedSourceSkuCount}</span>
                      </button>
                      <button
                        aria-label={`移除货源 ${candidateIndex + 1}`}
                        className="sku-combo-modal-source-remove"
                        type="button"
                        onClick={() => removeComboModalSource(candidate.id)}
                      >
                        ×
                      </button>
                    </div>
                  );
                })}
              </div>

              {activeComboModalCandidate ? (
                <div className="sku-combo-modal-source">
                  <div className="sku-source-head">
                    <div className="sku-combo-modal-source-heading">
                      <span className="source-select-thumb sku-combo-modal-source-heading-thumb">
                        {getCandidateMainImageUrl(activeComboModalCandidate) ? (
                          <Image
                            alt={activeComboModalCandidate.title}
                            height={44}
                            preview={false}
                            referrerPolicy="no-referrer"
                            src={getCandidateMainImageUrl(activeComboModalCandidate)}
                            width={44}
                          />
                        ) : (
                          <span>1688</span>
                        )}
                      </span>
                      <div>
                        <Text strong>{getCandidateLabel(activeComboModalCandidate, activeComboModalCandidateIndex)}</Text>
                        <Text type="secondary"> · {activeComboModalCandidate.title}</Text>
                      </div>
                    </div>
                    <Space size={6}>
                      <Tag>SKU {activeComboModalDisplaySkuList.length}</Tag>
                      <Tag color="red">{formatPrice(activeComboModalCandidate)}</Tag>
                    </Space>
                  </div>
                  <div className="sku-combo-modal-toolbar">
                    <Checkbox
                      checked={activeComboModalAllChecked}
                      disabled={activeComboModalSourceSkuKeys.length === 0}
                      indeterminate={activeComboModalIndeterminate}
                      onChange={(event) => toggleAllComboModalSourceSkus(activeComboModalCandidate, event.target.checked)}
                    >
                      全选该货源
                    </Checkbox>
                    <Text type="secondary">已选 {activeComboModalSelectedSkuKeys.length} 个</Text>
                  </div>
                  <div className="sku-list sku-combo-modal-shared-list">
                    {activeComboModalDisplaySkuList.map((sku, index) => {
                      const skuKey = getSkuSelectionKey(
                        activeComboModalCandidate,
                        sku,
                        index,
                        activeComboModalDominantPropName,
                      );
                      const selected = comboModalSkuKeySet.has(skuKey);
                      const skuImageUrl = getSkuImageUrl(activeComboModalCandidate, sku, index);

                      return (
                        <div
                          className={`sku-row sku-row-selectable ${selected ? 'sku-row-pending' : ''}`}
                          key={skuKey}
                          onClick={() => toggleComboModalSkuSelection(skuKey, !selected)}
                        >
                          <div className="sku-main">
                            <Checkbox
                              aria-label={`选择 ${getSkuSpecText(sku, index, activeComboModalDominantPropName)}`}
                              checked={selected}
                              className="sku-check"
                              onClick={(event) => event.stopPropagation()}
                              onChange={(event) => toggleComboModalSkuSelection(skuKey, event.target.checked)}
                            />
                            <div className="sku-image">
                              {skuImageUrl ? (
                                <Image
                                  alt={getSkuSpecText(sku, index, activeComboModalDominantPropName)}
                                  height={44}
                                  preview
                                  referrerPolicy="no-referrer"
                                  src={skuImageUrl}
                                  width={44}
                                />
                              ) : (
                                <span>SKU</span>
                              )}
                            </div>
                            <div className="sku-text">
                              <Text strong>{getSkuSpecText(sku, index, activeComboModalDominantPropName)}</Text>
                              <Text type="secondary">
                                {getCandidateLabel(activeComboModalCandidate, activeComboModalCandidateIndex)}
                              </Text>
                            </div>
                          </div>
                          <div className="sku-meta">
                            {formatSkuPrice(sku) ? (
                              <Text strong className="price-red">
                                {formatSkuPrice(sku)}
                              </Text>
                            ) : null}
                            {formatSkuStock(sku) ? <Text type="secondary">{formatSkuStock(sku)}</Text> : null}
                            {formatSkuWeight(sku, activeComboModalCandidate) ? (
                              <Text type="secondary">重量 {formatSkuWeight(sku, activeComboModalCandidate)}</Text>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </>
          )}
        </div>
      </Modal>
    </div>
  );
}
