export type LinkListSchemaVersion = 3;
export type LinkListImageProvider = 'chatgpt' | 'plugin_chatgpt_web' | 'comfyui';
export type LinkListImageEditStatus = 'draft' | 'queued' | 'running' | 'done' | 'failed';
export type LinkListImageRole = 'product-main' | 'product-material' | 'sales-sku';

export type LinkListImageAsset = {
  id: string;
  role: LinkListImageRole;
  sourceUrl?: string;
  sourceCloudUrl?: string;
  displayUrl?: string;
  displayCloudUrl?: string;
  editedUrl?: string;
  editedCloudUrl?: string;
  storageKey?: string;
  alt?: string;
};

export type LinkListImageSlotType = 'main' | 'carousel' | 'sku';

export type LinkListImageSlot = {
  id: string;
  type: LinkListImageSlotType;
  order: number;
  assetId?: string;
  skuEntryId?: string;
  locked?: boolean;
};

export type LinkListImageEditTask = {
  id: string;
  provider: LinkListImageProvider;
  mode: 'image-to-image';
  status: LinkListImageEditStatus;
  inputImageUrl?: string;
  outputImageUrl?: string;
  prompt: string;
  stylePrompt: string;
  referenceMainImageAssetId?: string;
  targetSkuEntryId?: string;
  workflow?: {
    chatgptModel?: string;
    comfyuiWorkflowId?: string;
    comfyuiNodeMap?: Record<string, string>;
    jobId?: string;
    seed?: number;
    params?: Record<string, unknown>;
  };
  createdAt: string;
  updatedAt?: string;
};

export type LinkListStyleProfile = {
  id: string;
  name: string;
  provider: LinkListImageProvider;
  prompt: string;
  negativePrompt?: string;
  referenceImageAssetId?: string;
};

export type LinkListSource = {
  id: string;
  title: string;
  productUrl: string;
  shopName?: string;
  shopUrl?: string;
  imageUrl?: string;
};

export type LinkListComponentSku = {
  name: string;
  specText: string;
  originalName?: string;
  visualGeneratedName?: string;
  sourceId?: string;
  sourceSkuId?: string;
  sourceSkuKey?: string;
  sourceTitle: string;
  sourceUrl: string;
  sourceImageUrl?: string;
  imageUrl?: string;
  rawSpecs?: Record<string, string>;
};

export type LinkListSourceSkuLink = {
  sourceId: string;
  sourceTitle: string;
  sourceProductUrl: string;
  sourceSkuId?: string;
  sourceSkuKey: string;
  specText: string;
  optionText: string;
  imageUrl?: string;
};

export type LinkListSkuEntry = {
  id: string;
  order: number;
  kind: 'single' | 'combo';
  name: string;
  originalName?: string;
  visualGeneratedName?: string;
  visualGeneratedNameSource?: string;
  visualGeneratedNameTaskId?: string;
  imageAsset?: LinkListImageAsset;
  imageEditTask?: LinkListImageEditTask;
  imageUrl?: string;
  price?: number;
  weight?: number;
  sourceSkuLinks?: LinkListSourceSkuLink[];
  componentSkus: LinkListComponentSku[];
};

export type LinkListCreativeJobSummary = {
  id: string;
  provider: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  imageIndex: number;
  imageKind: string;
  imageLabel: string;
  targetSkuEntryId?: string | null;
  resultImageUrl?: string | null;
  analysisText?: string | null;
  updatedAt: string;
};

export type LinkListRecord = {
  schemaVersion?: LinkListSchemaVersion;
  id: string;
  createdAt: string;
  productId: string;
  productTitle: string;
  productTitleEn?: string;
  attributeTitle?: string;
  attributeTitleEn?: string;
  visualGeneratedTitleCn?: string;
  visualGeneratedTitleEn?: string;
  visualGeneratedProductType?: string;
  visualProductIdentity?: Record<string, unknown>;
  visualProductIdentityTaskId?: string;
  visualProductIdentityUpdatedAt?: string;
  category?: string;
  categoryLevel1?: string;
  categoryLevel2?: string;
  categoryPath?: string;
  categoryId?: string;
  temuCategoryId?: string;
  dxmCategoryId?: string;
  mainImage?: LinkListImageAsset;
  productMaterialImages?: LinkListImageAsset[];
  imageSlots?: LinkListImageSlot[];
  productImageGenerationCount?: number;
  styleProfile?: LinkListStyleProfile;
  productImageUrl?: string;
  productSourceUrl?: string;
  sourceLinks: LinkListSource[];
  skuEntries: LinkListSkuEntry[];
  componentSkuCount: number;
  creativeJobs?: LinkListCreativeJobSummary[];
};
