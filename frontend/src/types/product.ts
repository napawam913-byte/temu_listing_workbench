export type ProductStatus = 'active' | 'deleted' | 'sourced';

export type Product = {
  id: string;
  title: string;
  titleEn?: string;
  category: string;
  categoryLevel1?: string;
  categoryLevel2?: string;
  categoryPath?: string;
  price: number;
  sales: number;
  gmv: number;
  reviewCount: number;
  listedAt: string;
  growthRate: number;
  sourceRow: number;
  period: '近7天' | '近30天';
  status: ProductStatus;
  imageTone: 'blue' | 'red' | 'green';
  mainImageUrl?: string;
  sourceUrl?: string;
};

export type SourcingCandidate = {
  id: string;
  title: string;
  price: number;
  matchRate: number;
  tag: '同款' | '相似款';
  moq: number;
  shippingFee: number;
  weightKg: number;
  shopName: string;
  selected?: boolean;
};

export type ImportSource = 'yunqi' | 'temu' | '1688' | 'custom';
