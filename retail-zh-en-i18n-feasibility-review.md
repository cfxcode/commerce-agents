**结论**

有条件可做。

只为当前 `retail` 示例提供中文和英文时，架构改动不大，主要工作是收拢散落文案、让格式化函数接收 locale，并把语言偏好传给模型。若“完整国际化”还包括 87 个商品、订单、政策和商家演示数据的中英双语内容，工作量会从中等增加到中等偏大。

**需求摘要**

- 目标：为 retail 商城前台和商家后台提供简体中文、英文两种语言，并允许用户切换。
- 用户价值：中文用户可以完整使用界面、组件卡片、订单与购物车流程，同时仍保留英文演示能力。
- 成功标准：所有可见界面文案、日期、数字、货币、无障碍标签和模型回复随语言切换；刷新后保留选择；中英文核心流程均可用。
- 隐含假设：首期只改 `examples/retail` 的前台与商家后台；URL 不要求 `/zh-CN`、`/en-US` 路由；不要求把其他三个 vertical 同步国际化。

**代码现状**

- 相关模块：
  - 零售前台入口在 [`examples/retail/storefront-web/app/page.tsx`](examples/retail/storefront-web/app/page.tsx)，商家后台在 `examples/retail/merchant-web/`。
  - 两端共用 `examples/web-shared/` 的 Shell、订单、购物车、聊天、活动面板和格式化工具。
  - 模型提示词由 [`shopping-agent/core/shopping_agent/prompt.py`](shopping-agent/core/shopping_agent/prompt.py) 和 merchant 对应模块生成。
  - 会话上下文 [`ShoppingSessionContext`](shopping-agent/core/shopping_agent/types.py) 目前没有 locale/language 字段。
- 已有能力：
  - React/Next.js 组件边界清晰，共享组件集中，适合增加统一 Locale Provider。
  - 日期、金额、数字主要经过 `examples/web-shared/format.ts`，有较好的集中改造入口。
  - 模型本身可以理解中文，当前真实模型链路已经能够处理 Unicode 文本。
- 主要缺口：
  - 没有 i18n 包、语言字典或 locale 上下文。
  - 页面 `<html lang="en">`、`Intl.NumberFormat("en-US")`、`toLocaleDateString("en-US")` 均固定为英文。
  - UI 文案、工具活动提示、无障碍标签、模型建议 chips 分散在组件内。
  - 前端 session/chat 请求和后端 agent session context 都没有携带语言偏好。
  - 商品、政策、订单、营销和指标 fixtures 是英文内容，不会仅靠翻译 UI 自动变成中文。
- 关键证据：
  - retail 与共享前端共 74 个 TypeScript/TSX 文件，其中约 54 个文件包含疑似用户可见英文字符串。
  - [`examples/web-shared/format.ts`](examples/web-shared/format.ts) 将金额和数字固定为 `en-US`。
  - 两个 [`layout.tsx`](examples/retail/storefront-web/app/layout.tsx) 都固定输出 `lang="en"`，字体也只声明了 `latin` subset。
  - `examples/retail/data/catalog.json` 有 87 个商品，`policies.json` 有 11 条政策；商品文件约 2185 行，是内容翻译的主要增量。

**合理性评估**

- 产品和工作流：中英双语与演示项目定位兼容，语言切换应放在两个 Shell 的顶部，并在前台与商家后台共享同一持久化偏好。
- 架构和数据流：推荐一个共享、类型安全的 locale 层，默认英文以保持其他 vertical 不变。locale 同时进入格式化函数和 API 会话上下文，模型回复语言才可稳定一致。
- 权限、安全、计费：没有新的权限或数据库要求。模型调用次数不变；中文 token 用量可能略有差异，但不会引入新的计费路径。
- i18n、数据库、兼容性：无需数据库迁移。共享组件必须保留默认英文，否则 travel、telecom、entertainment 的构建可能回归。中文字体应使用系统 CJK 字体回退或增加合适字体，不应只依赖 Latin Web Font。

**可行性评估**

- 复杂度：
  - 仅 retail 双端 UI、格式化、无障碍文本和模型回复双语：中等，约 4～6 个工程日，加 1～2 个测试日。
  - 再翻译全部 retail 演示数据，并逐条校对商品、政策和商家内容：额外约 3～5 个工程/内容日。
  - 若四个 vertical 全部双语：预计 3～5 周，不能按 retail 的数字简单乘四，因为共享层可复用，但各 vertical 的组件和数据不同。
- 主要改动面：locale 状态与持久化、共享字典、零售专属字典、日期/金额/复数格式化、两个语言选择器、HTML lang、模型语言约束、fixtures 的本地化字段和测试。
- 依赖或迁移：两个语言且没有本地化路由/SEO要求时，不必引入大型 i18n 框架；一个类型安全的 `LocaleProvider + dictionaries + Intl` 足够。若未来需要 locale URL、服务端 metadata 或更多语言，再引入 `next-intl` 更合理。
- 主要风险：漏翻动态卡片和 aria-label；模型根据用户输入语言而非界面语言回复；中文下复数函数仍拼英文；共享格式化函数改签名后影响八个 Web App；商品内容中英混排造成“界面中文但内容英文”的不完整体验。

**简单实现方案**

- 最小可行路径：
  1. 在 `web-shared` 增加 `LocaleProvider`、`useI18n()`、`Locale = "en" | "zh-CN"` 和共享字典，默认 `en`。
  2. 在 retail 两个 app 增加各自的业务字典与语言切换器，用 cookie 或 localStorage 保存选择；初始化后同步 `document.documentElement.lang`。
  3. 将共享 `formatMoney/formatDate/formatNumber/plural` 改为显式或上下文 locale，中文使用 `zh-CN` 的 `Intl` 规则。
  4. 把 storefront、merchant、generative cards、活动提示和 aria-label 的硬编码英文替换为字典键。
  5. session 创建或 chat 请求携带 locale，后端把它放入动态 Session context，明确要求模型及 presentation 字段使用所选语言。将语言放动态 context 可避免为每种语言复制 agent，并减少静态提示缓存破坏。
  6. 若要求内容也完整双语，为 fixtures 增加 `title_i18n`/`description_i18n` 等结构，后端按 session locale 返回对应文本；不要在前端临时机器翻译业务数据。
- 涉及层级：Next.js layout/page、共享 React 组件、API client/session schema、FastAPI session/context、agent 动态 prompt、JSON fixtures。
- 测试建议：
  - 两种语言分别覆盖首页、搜索、比较、购物车、订单、结账摘要、商家审批和分析卡片。
  - 检查日期、金额、复数、空状态、错误状态、loading 文案及所有 aria-label。
  - 增加一次中文 smoke chat，断言工具调用仍正确且最终文本、suggestion chips 为中文。
  - 运行全部八个 Web App build，确认共享层默认英文没有破坏其他 vertical。

**指出问题**

- 需求矛盾：无直接矛盾，但“完整国际化”可能表示仅 UI，也可能包括全部商品和业务数据；两者工期相差约一倍。
- 缺失信息：尚未明确是否需要中文商品/政策内容、默认语言、语言选择是否跨前台与后台共享、是否需要带 locale 的 URL。
- 边界条件：用户切换语言后，既有聊天记录不应被重写；新回复改用新语言即可。商品品牌、SKU、订单号等标识不翻译。货币仍应使用数据中的 USD，而不是因中文界面自动改成人民币。
- 潜在回归：共享组件被其他 vertical 使用；若翻译改造没有英文默认值，会导致其他七个 App 编译或运行失败。

**改进建议**

- 更小范围方案：先完成 retail 商城前台双语，保留商品原文；约 2～3 个工程日即可得到可演示版本。
- 替代方案：如果只希望中文展示，可一次性硬编码中文，成本更低，但之后恢复双语会重复修改，不建议作为正式方案。
- 拆期建议：
  - 第一期：语言基础设施、前台/后台 UI、格式化、模型回复。
  - 第二期：商品、政策、订单和商家 fixtures 双语化与内容校对。
  - 第三期：确认需要后再扩展另外三个 vertical 或 locale 路由。

**待确认问题**

- “完整”是否包含 87 个商品、政策、订单和商家演示数据的中文翻译？
- 只改当前 retail，还是四个 vertical 都要支持中英文？
- 默认语言按浏览器自动选择，还是固定中文？
