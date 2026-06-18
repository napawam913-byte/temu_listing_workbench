# 生图到导出 Excel 流程文档

更新日期：2026-06-18

本文档记录当前新版业务流程：从商品图片生成，到店小秘 Temu Excel 导出。当前版本已经把“标题生成”合并进“图片理解 / 商品分析”阶段，导出 Excel 时不再单独调用标题生成 API。

## 1. 总体结论

按单个商品、一次正常成功、不触发重试计算：

| 流程 | AI API 调用次数 | 说明 |
| --- | ---: | --- |
| 生图 | 4 次 | 图片理解 1 次，提示词规划 2 次，图片生成 1 次 |
| 导出 Excel | 通常 2 到 4+ 次 | 产品属性 2 次起，SKU 翻译和复杂类目会增加调用 |
| 生图 + 导出合计 | 最少 6 次，常见 7 次，复杂情况 8 次以上 | 不含失败重试、超时重试、上游 502/503 重试 |

标题生成当前为 0 次单独调用，因为标题已在生图第一步“图片理解 / 商品分析”里生成。

## 2. 生图流程

入口模块：

- `backend/app/api/routes_visual_generation.py`
- `backend/app/modules/visual_generation/service.py`
- `backend/app/modules/visual_generation/planner.py`

核心执行函数：

- `create_visual_task`
- `run_visual_task_pipeline`
- `plan_visual_task`
- `generate_visual_task`
- `split_visual_task`

### 2.1 任务输入

模块：

- `routes_visual_generation.py`
- `visual_generation/service.py::create_visual_task`

做的事：

- 创建视觉任务。
- 保存商品标题、SKU、参考图、SKU 图片绑定、组合 SKU 绑定、布局信息。
- 决定本次是 3x3 九宫格、2x2 四宫格，还是其他布局。
- 如果是不同货源组合 SKU，使用前端绑定弹窗确认的图片参数和 SKU 组件关系。

AI API 调用：0 次。

提示词：无。

### 2.2 阶段一：图片理解 / 商品分析 / 标题生成

模块：

- `visual_generation/planner.py::request_product_analysis`
- `visual_generation/planner.py::build_product_analysis_instruction`

后台配置：

- `OPENAI_VISUAL_ANALYSIS_MODEL`
- 默认温度：`0.1`

输入：

- 商品标题。
- 商品英文标题。
- SKU 名称。
- SKU 绑定关系。
- 参考图片。
- 组合 SKU 组件关系。
- 用户选择的图片参数。

做的事：

- 分析参考图中的商品主体、形状、颜色、材质、数量、结构、表面质感、风险元素。
- 对不同参考图分别识别，避免把 A 货源标题借给 B 货源图片。
- 对外观、材质、形状、颜色、数量、结构使用图片作为最高权威。
- 标题、SKU、sourceTitle 只辅助判断功能、用途、场景、数量和卖点，不允许覆盖图片事实。
- 直接生成最终标题：
  - `productIdentity.title_cn`
  - `productIdentity.title_en`
- 生成 SKU 标准名：
  - `productIdentity.skus[].standard_name`
- 生成后续生图必须保留和禁止改变的规则：
  - `mustPreserve`
  - `doNotChange`
  - `referenceAnalyses`

使用提示词：

- `build_product_analysis_instruction`
- 内部已迁移原“标题生成”规则。
- 核心规则是：图片决定商品外貌、材质、结构；标题只辅助功能和用途；结果必须返回最终中英标题。

AI API 调用：1 次，多模态文本 + 图片。

输出用途：

- 前端回显图片理解结果。
- 生图规划使用。
- 导出 Excel 使用最终标题。
- SKU 变体和组合关系使用。

### 2.3 阶段二：九宫格 / 四宫格任务规划

模块：

- `visual_generation/planner.py::request_prompt_plan`
- `visual_generation/planner.py::build_prompt_plan_instruction`

后台配置：

- `OPENAI_VISUAL_PROMPT_MODEL`
- 温度：`0.6`

做的事：

- 根据阶段一结果规划需要生成哪些图。
- 3x3 默认规划 9 张：
  - 主图
  - 效果图
  - 人物场景
  - 场景图
  - 细节图
  - 尺寸结构
  - 对比图
  - 组合包装
  - 卖点图
- 2x2 默认规划 4 张。
- 根据商品类型和 SKU 绑定决定每格展示重点。
- 不让模型随意改变商品材质、样貌、数量和绑定关系。

使用提示词：

- `build_prompt_plan_instruction`

AI API 调用：1 次，文本。

输出：

- `visualTaskPlan`
- 每个格子的 `slotType`
- 每个格子的 `title`
- 每个格子的 `purpose`
- 整体风格方向。

### 2.4 阶段三：每格最终提示词生成

模块：

- `visual_generation/planner.py::request_prompt_plan`
- `visual_generation/planner.py::build_panel_prompt_instruction`

后台配置：

- `OPENAI_VISUAL_PROMPT_MODEL`
- 温度：`0.6`

做的事：

- 把阶段二规划转换成每一格具体英文生图提示词。
- 每个 panel 都会带入：
  - 商品理解结果。
  - 参考图绑定关系。
  - SKU 绑定关系。
  - 组合 SKU 组件关系。
  - 必须保留项。
  - 禁止改变项。
  - 安全文案规则。
- 如果有图片文案，要求客观、安全、可读，不允许价格、折扣、评分、医疗、认证、绝对化承诺等风险词。

使用提示词：

- `build_panel_prompt_instruction`

AI API 调用：1 次，文本。

输出：

- `panelPromptPlan`
- 每个格子的最终英文提示词。
- 每个格子的负面约束。
- 每个格子的安全说明。

### 2.5 阶段四：母图生图

模块：

- `visual_generation/service.py::generate_visual_task`
- `visual_generation/planner.py::build_mother_prompt_from_plan`
- `visual_generation/clients.py`

后台配置：

- `OPENAI_IMAGE_MODEL`
- `VISUAL_IMAGE_SIZE`
- `VISUAL_USE_REFERENCE_IMAGE`
- `VISUAL_IMAGE_REQUEST_TIMEOUT_SECONDS`

做的事：

- 把每格 panel prompt 合成最终母图提示词。
- 调用图片生成接口生成一张完整母图。
- 如果开启图生图参考，则传入参考图参数。
- 当前初凡 AI 图片模型通常使用 `gpt-image-2-1k`。
- 生成结果保存到 `storage/visual_generation/.../mother_image.png`。

使用提示词：

- `build_mother_prompt_from_plan`

AI API 调用：1 次，图片生成。

输出：

- 一张 3x3 或 2x2 母图。

### 2.6 阶段五：切图与回写

模块：

- `visual_generation/service.py::split_visual_task`

做的事：

- 本地把母图按布局切成 9 张或 4 张。
- 根据配置应用：
  - `VISUAL_SPLIT_TARGET_SIZE`
  - `VISUAL_SPLIT_FORMAT`
  - `VISUAL_SPLIT_QUALITY`
  - `VISUAL_SPLIT_SAFE_MARGIN_RATIO`
  - `VISUAL_SPLIT_SHARPEN`
- 可选上传 OSS。
- 回写到链接列表商品图位。

AI API 调用：0 次。

## 3. 导出 Excel 流程

入口模块：

- `backend/app/modules/exports/dianxiaomi_export_tasks.py`
- `backend/app/modules/exports/dianxiaomi_temu.py`
- `backend/app/modules/exports/product_attributes.py`
- `backend/app/modules/creative_generation/listing_title_optimizer.py`

核心执行函数：

- `export_dianxiaomi_temu_template`
- `build_template_rows_for_export_records`
- `build_template_rows`
- `get_product_attribute_for_export_record`
- `translate_variant_values_to_english`

### 3.1 读取商品与图片

模块：

- `dianxiaomi_temu.py::build_template_rows`

做的事：

- 读取商品记录。
- 读取 SKU 列表。
- 读取主图、轮播图、SKU 图。
- 读取阶段一生成的最终标题：
  - `visualGeneratedTitleCn`
  - `visualGeneratedTitleEn`
  - 或 `visualProductIdentity.title_cn/title_en`
- 如果没有视觉生成标题，才回退到原始商品标题。

AI API 调用：0 次。

注意：

- 当前导出流程不再调用单独标题生成 API。
- `optimize_listing_titles` 不再参与导出标题生成。

### 3.2 产品属性：类目意图识别

模块：

- `product_attributes.py::request_category_intent_ai`

后台配置：

- `OPENAI_PRODUCT_ATTRIBUTE_MODEL`
- 温度：`0.05`

做的事：

- 根据最终导出标题、SKU、来源标题、参考图，判断真实商品身份。
- 生成类目匹配信号：
  - 商品类型
  - 核心关键词
  - 材质
  - 使用场景
  - 应排除的误导词
- 避免被来源标题里的营销词、物流词、礼品词、容器词误导。

使用提示词：

- `request_category_intent_ai` 内部构造的类目意图识别提示词。

AI API 调用：通常 1 次。

### 3.3 产品属性：候选类目选择

模块：

- `product_attributes.py::request_category_branch_ai`

后台配置：

- `OPENAI_PRODUCT_ATTRIBUTE_MODEL`
- 温度：`0.05`

做的事：

- 本地类目库会先用向量召回候选类目。
- 如果候选类目不够明确，交给模型从候选列表里选最合适的一个。
- 模型只能在候选项里选，不允许编造类目。

使用提示词：

- `request_category_branch_ai` 内部构造的候选类目选择提示词。

AI API 调用：0 到多次。

说明：

- 简单商品可能不需要额外调用。
- 类目树复杂、向量结果不稳定时，会增加调用。

### 3.4 产品属性：属性值填写

模块：

- `product_attributes.py::request_product_attribute_ai`

后台配置：

- `OPENAI_PRODUCT_ATTRIBUTE_MODEL`
- 温度：`0.05`

做的事：

- 根据最终标题、SKU、类目、候选属性字段，填写店小秘/TEMU 商品属性。
- 红线属性保守处理：
  - 液体
  - 电池
  - 带电
  - 燃料
  - 打火机
  - 医疗/认证等敏感属性
- 如果标题、SKU、图片没有明确证明，则优先选择否、无、不适用。

使用提示词：

- `request_product_attribute_ai` 内部构造的产品属性填写提示词。

AI API 调用：1 次。

### 3.5 SKU 变体英文翻译

模块：

- `listing_title_optimizer.py::translate_variant_values_to_english`
- `listing_title_optimizer.py::generate_variant_values_with_ai`

后台配置：

- 当前使用通用文本模型配置。

做的事：

- 把 SKU 变体值转换为适合店小秘模板的简洁英文。
- 如果 SKU 已经是可用英文，可能不调用 AI。
- 如果 SKU 是中文、组合 SKU、或需要结合图片和来源标题判断，则调用 AI。
- 组合 SKU 会尽量保留 `+` 结构，例如 `Pet Bowl+Feeding Mat`。

使用提示词：

- `generate_variant_values_with_ai` 内部构造的 SKU 变体英文值生成提示词。

AI API 调用：0 或 1 次。

### 3.6 写入店小秘 Excel

模块：

- `dianxiaomi_temu.py::export_dianxiaomi_temu_template`

做的事：

- 打开店小秘 Temu 半托管模板。
- 写入：
  - 中文标题
  - 英文标题
  - 主图
  - 轮播图
  - SKU 图
  - SKU 变体
  - 类目 ID
  - 产品属性
  - 重量、尺寸、库存等默认值
- 保存导出文件到 `storage/exports`。

AI API 调用：0 次。

## 4. API 调用次数汇总

### 4.1 单商品生图

| 阶段 | 次数 |
| --- | ---: |
| 图片理解 / 商品分析 / 标题生成 | 1 |
| 九宫格或四宫格任务规划 | 1 |
| 每格最终提示词生成 | 1 |
| 母图生图 | 1 |
| 切图与回写 | 0 |
| 合计 | 4 |

### 4.2 单商品导出 Excel

| 阶段 | 次数 |
| --- | ---: |
| 读取商品、图片、SKU | 0 |
| 类目意图识别 | 1 |
| 候选类目选择 | 0 到多次 |
| 产品属性填写 | 1 |
| SKU 变体英文翻译 | 0 或 1 |
| 写入 Excel | 0 |
| 合计 | 通常 2 到 4+ |

### 4.3 生图 + 导出合计

| 情况 | 调用次数 |
| --- | ---: |
| 最少情况 | 6 次 |
| 常见情况 | 7 次 |
| 复杂类目 / SKU 翻译 / 候选类目多轮 | 8 次以上 |

不计入上述次数的情况：

- 上游 502 / 503 / 429 / 超时后的重试。
- 请求过大后使用压缩上下文再请求。
- 用户手动重跑生图。
- 批量导出多个商品。

批量导出估算：

```text
总调用次数 ≈ 商品数 × 单商品导出调用次数
```

如果商品已经完成生图，再批量导出 5 个商品：

```text
常见导出调用 ≈ 5 × 3 = 15 次
```

如果从生图到导出都执行 5 个商品：

```text
常见总调用 ≈ 5 × 7 = 35 次
```

## 5. 当前提示词来源

| 阶段 | 提示词来源 |
| --- | --- |
| 标题拆分 | `admin_prompt_configs.py::_title_split_prompt_content` / `sourcing_1688/title_keywords.py` |
| 智能推荐 | `admin_prompt_configs.py::_recommendation_prompt_content` / `sourcing_1688/smart_recommendations.py` |
| 产品属性填写 | `exports/product_attributes.py::request_product_attribute_ai` |
| 图片理解 / 商品分析 / 标题生成 | `visual_generation/planner.py::build_product_analysis_instruction` |
| 提示词任务规划 | `visual_generation/planner.py::build_prompt_plan_instruction` |
| 每格最终提示词 | `visual_generation/planner.py::build_panel_prompt_instruction` |
| 母图生图提示词 | `visual_generation/planner.py::build_mother_prompt_from_plan` |
| SKU 变体英文翻译 | `creative_generation/listing_title_optimizer.py::generate_variant_values_with_ai` |

## 6. 当前关键规则

1. 图片理解阶段同时负责最终标题生成。
2. 导出 Excel 不再单独调用标题生成 API。
3. 商品外观、材质、形状、颜色、数量、结构以参考图为最高权威。
4. 标题、SKU、sourceTitle 只辅助功能、用途、场景和卖点，不允许覆盖图片事实。
5. 不同货源组合 SKU 必须使用绑定弹窗确认的图片和 SKU 组件关系。
6. 组合 SKU 以 `+` 拆分组件，并分别绑定对应图片参数。
7. 生图阶段如果开启参考图，会把用户选择的参考图作为图片参数传给图片生成接口。
8. 导出阶段产品属性包含红线规则，液体、带电、电池、燃料等不明确时优先选择否、无、不适用。
9. SKU 变体英文翻译不是标题生成，只负责把 SKU 值清洗成店小秘模板可用的英文短值。

