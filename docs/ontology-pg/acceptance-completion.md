# 语义闭包补充验收记录

本记录补充 `semantic-context-progress.md`，不覆盖前次 1418 项测试及历史模型试评。实现基线为 `dfcb760eca96483ca5d0f3d27b755ba59c4f963d`；本轮功能与布局修正提交为 `8bd64a75b4fad3dd4f3ce0cb221b56977213544c`。日期：2026-09-17。

**状态：剩余核心代码、离线回归和浏览器验收已完成；真实模型对照及依赖该证据的发布／启用仍被模型凭证阻塞。不能将此记录解释为所有上线条件已满足。**

## 1. 完成的增量

| 原缺口 | 交付与验收 |
|---|---|
| 覆盖与相关性指标 | 新增独立人工规格 oracle，统计必需定义覆盖、状态定义覆盖、缺失与无依据的额外定义；缺失证据返回未计量，不返回虚假的 100% |
| 构造与调用计数 | 新增 context_attempt_id；静态构造成功后整体 payload 超限只算一次失败；模型尚未请求的失败不计入模型调用 |
| 完整输入预算 | preflight-guidance 复用实际 Runtime 的 task_payload、guidance_input 和 JSON 字节计量，包括事实、方案和近期事件 |
| 浏览器链路 | 真实 Chromium、构建后的零售页面、真实模拟 Backend／会话／SSE／审批卡片／执行保护；只有模型响应使用脚本 fixture |
| 历史与失败显示 | 按任务、修订号、回合和阶段区分当前／历史语义；最新失败不会被旧成功记录遮蔽，切换会话清理旧界面状态 |
| 窄屏布局 | 修复隐式 grid 最小内容宽度导致的横向溢出；检查文档和实际 .portal-main 滚动容器，而不仅检查 body |
| 真实模型执行入口 | 增加受调用数、返回 token、单次请求大小和时间限制的 live_acceptance CLI；工作流仅手动选择 smoke/validation 时调用模型 |
| 不完整模型计量 | 缺失、负数、错误类型的 usage 阻止后续付费请求，不以零消耗代替未知费用 |

本轮没有新增向量库、改变 PG 拓扑、替换 Runtime、扩大工具权限或修改业务审批规则。可选 render、静态缓存及新业务场景仍不在必要交付范围。

## 2. 实际离线结果

| 检查 | 结果 |
|---|---|
| 本地 Python 3.13 全仓测试 | 1433 passed、1 skipped、2 warnings |
| 独立语义验证 | 236 项语义测试通过 |
| 执行安全验证 | 51 项通过；与上述测试集部分重叠，不加总成唯一测试数 |
| Ruff 与格式 | 通过，253 个 Python 文件格式检查 |
| 仓库一致性 | scripts/check.py 通过 |
| 静态语义预检 | 保留原有 135 个组合 |
| 完整指导输入预检 | 810 个合成组合：675 个普通输入被接受、135 个故意超限输入被正确拒绝 |
| 独立定义审计 | 810 个构造结果均符合预期依赖；缺少必需定义 0、无依据额外定义 0 |

810 = 15 节点 × 3 种 hop × 3 种目标类型 × 6 种数据形态。形态包括完整事实、等待审批、冲突、过期、较长字段和故意超限。它们是结构化压力组合，**不是 810 个可达业务状态，也不是 810 次真实模型任务**。预算失败保留执行检查，不自动提高模型预算。

功能提交的 CI 入口：

- [全仓 CI](https://github.com/cfxcode/commerce-agents/actions/runs/35178650448)
- [语义检索、完整输入预检与证据 CI](https://github.com/cfxcode/commerce-agents/actions/runs/35178650431)
- [浏览器 CI](https://github.com/cfxcode/commerce-agents/actions/runs/35178650438)

结果应以各运行中实际完成的 job、日志和 artifact 为准。后续文档提交不改变上述功能源码；PR Checks 展示其最终复验状态。

## 3. 浏览器结果与范围

浏览器运行 `35178650438` 的 6 个案例全部通过：

| 语言／宽度 | 路径 | 实际模拟终态 |
|---|---|---|
| 英文 1440px | 批准 | 库存 12→90，SUCCESS，待处理 0 |
| 中文 1440px | 丢弃 | 库存保持 12，DECLINED，待处理 0 |
| 中文 390px | 批准 | 库存 12→90，SUCCESS，待处理 0 |
| 英文 390px | 丢弃 | 库存保持 12，DECLINED，待处理 0 |
| 英文 1440px | 语义超限后批准 | 有降级说明，原审批和执行保护仍生效，库存 90 |
| 中文 390px | 语义超限后丢弃 | 显示 SEMANTIC_BUDGET_EXCEEDED，库存保持 12 |

检查包括实际按钮点击、事前库存未改变、应用／丢弃结果、历史语义标记、定义依赖展开、错误提示、页面异常与嵌套容器宽度。另已查看桌面英文、窄屏中文历史状态和降级状态截图，确认标题、正文、摘要、折叠控件和错误提示可读。

证据 artifact：`10479162979`；下载 ZIP SHA256：`11f668008cae166606ceb1101a0509c607a81eacd1302dfe262b53610b08edeb`。包含 report.json、预览／语义截图及虚构 fixture 日志，Actions 保留 7 天。

这些测试运行的是实际浏览器与实际模拟业务代码，**主模型和指导模型的回复均为脚本**。真实模型调用数为 0；不验证模型推理效果，不等于真实手机、Safari／Firefox 或生产认证验收。外部商品图片不属于此次控制流验收。

首轮移动端因脚本使用了桌面控件名称失败；已改为移动端实际可访问名称。随后视觉检查发现 grid 的嵌套横向溢出，已修复并增加相应断言。失败运行保留，不以重试替换原始失败记录。

## 4. 唯一外部阻塞链：模型配置 → 真实评测 → 发布启用

实际 GitHub Actions 配置探测显示缺少：

- `ANTHROPIC_API_KEY`
- `COMMERCE_MODEL`

没有发出真实模型请求，没有提交真实模型验收报告，没有将 fixture 数据替代留出评测，也没有发布或切换 active。

通过仓库 Secrets 提供 API Key；模型可存为 Actions Variable 或 Secret。自有 Anthropic 兼容网关还需提供 `ANTHROPIC_BASE_URL`。不要将密钥提交源码、评论、日志、截图或聊天。非 Claude 模型未给出端点时拒绝猜测；官方端点模式不会把空字符串当成有效 base URL。

本地入口可以直接用于审查分支：

```bash
python -m commerce_reasoning.live_acceptance --check-only
python -m commerce_reasoning.live_acceptance \
  --max-calls 120 --max-tokens 400000 \
  --out runtime/live-semantic-smoke
# 冒烟正常后，运行同样的冒烟并继续独立验证；使用审查过的最大边界。
python -m commerce_reasoning.live_acceptance --validation \
  --max-calls 500 --max-tokens 2000000 \
  --out runtime/live-semantic-validation
```

退出码 78 表示缺少外部配置。CLI 不读取或猜测用户的私有密钥。工作流合并后可以使用手动入口：默认 check 不调用模型；smoke / validation 由操作者明确选择。PR 事件只检查配置存在性，**prerequisites job 为绿色不表示模型评测通过**。

调用上限是请求数与 token 停止阈值，不是金额上限；真实 usage 返回后才知道消耗，因此最后一个在途请求可能跨过累计 token 阈值。单次输出上限 2000，输入封套 250 KB，整轮 30 分钟，不做 SDK 重试。未知计量停止后续付费调用。对照失败或预算耗尽均不自动接受候选。

发布仍需原有的语义验证、模型报告比较、审查身份与版本绑定。`live_acceptance` 和工作流不自动合并、发布或激活。当前 `knowledge/releases/**`、active 指针和 `configs/reasoning.yaml` 保持不变，默认 legacy 未改变。

## 5. 验收结论

- 核心语义配置、构建器、检索接入、独立审计、输入预算和浏览器链路：已实现并验证。
- 真实 P_legacy/P_closure 效果比较：阻塞于外部模型配置。
- 真实语义发布／启用：等待真实比较通过，不绕过门槛。
- 可选 render／缓存／新场景：按原计划延后，不属于本次必要缺口。

不能宣称“全部上线验收完成”，也不能宣称语义闭包已经提高 Agent 成功率。
