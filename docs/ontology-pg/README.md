# Ontology / PG 零售商家实现

实现范围是零售 Merchant 的 Messages API、单个商品或规格的补货任务。Shopping、SDK、Managed Agents 和其他行业保持原默认执行方式。补货仅改变本地模拟库存，不产生采购单、付款或供应商到货。

## 安装与启动

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m commerce_reasoning.cli validate-knowledge --config configs/reasoning.yaml
python3 scripts/run_demo.py retail --merchant
```

当前零售配置为 `enabled: true`、`variant: P`，默认使用已发布的人工 PG 生成每轮指导。每次指导调用的超时上限为 `guidance_timeout_s: 30` 秒；指导模型未单独指定时沿用主助手模型。关闭指导、切回 C0：

```bash
COMMERCE_REASONING_ENABLED=0 python3 scripts/run_demo.py retail --merchant
```

开关在后端启动时读取；修改后需重启零售 API，复用已运行的 API 不会更新配置。重新开启可使用 `COMMERCE_REASONING_ENABLED=1`。C0 保留 Skill、计算工具、证据和全部审批检查。后端重启会重置内存中的演示库存和会话。

`COMMERCE_REASONING_CONFIG` 可指定独立 ReasoningConfig 文件。模型和网关沿用现有 `.env` 与 `COMMERCE_MODEL`；未指定指导模型时继承 Solver。执行保护不随 PG 关闭。零售配置始终要求宿主批准。

示例请求：“检查 AR-2102，按30天覆盖量计算补货并暂存预览，等待卡片批准。”未指定目标或天数时先澄清。普通商品与具体规格可以计算，商品族必须先选择规格。

## 行为与边界

1. 读取完整商品与完整待处理队列。告警和商品描述不授予写入来源资格。
2. `calculate_restock_plan(listing_id, target_days)` 从当前事实计算 `max(0, ceil(sales_last_30d × target_days / 30) − stock)`。天数为 1–365 的整数；未知销量不同于零销量。
3. 暂存只接受当前正向方案的目标和数量。方案默认有效 300 秒，观察默认有效 60 秒；源数据有效性还需 Backend 明确声明，读取时间不伪装成源更新时间。
4. 同一目标有待处理库存变更时阻断新暂存。审批绑定预览摘要、任务版本和库存 revision；聊天文本无法批准。
5. 宿主通过同一执行服务应用，受锁提交账本、库存、目录及回执，再重新读取验证。重复请求返回已记录结果；结果未知时只做核对。

`stage_inventory_action` 参数保持原形状，plan_id 存在服务端侧表。审批事件独立于 `staged / applied / discarded` 三种变更状态。一次用户回合可能结束于等待、澄清或拒绝，不代表库存已经改变。

串行调度按模型返回的工具顺序执行。合法图外动作可继续运行并留下事件；PG 条件不能授予权限。指导每轮只加入请求副本，不累积到持久会话或用户 memory。

本实现的事务边界是**单进程模拟状态**。SQLite 保存审计与侧表，业务库存仍在内存；每次启动采用新的 environment_id，旧审批不会被新环境复用。它不提供跨进程一次性提交保证，也不自动恢复上次进程的库存。

## 调试与审计

零售工作台“推理调试 / Reasoning”提供任务、当前图位置、事实有效性、补货公式、指导和实际执行事件。页面只读，支持中英文，显示期间每 2 秒刷新。未知值明确显示为未知。PG 指导面板显示最近记录中的成功／降级次数、最近失败原因，以及最近一次成功指导；过往指导明确标记为历史，不会重新注入当前模型请求。

指导输出按 JSON Schema、动作／证据／边引用和权限声明校验。明确的否定式提醒（如“不能声称已批准”）可以通过，肯定式批准声明和改变权限的指令仍会被拒绝。`guidance_failed` 记录 `failure_kind`、`failure_reason`、字段校验错误、实际耗时和超时配置，区分 JSON、schema、引用、权限声明、上下文预算和模型服务错误。

所有接口继续使用 `X-Session-Id`：

| 接口 | 用途 |
|---|---|
| `GET /api/merchant/reasoning/tasks` | 当前会话任务列表 |
| `GET /api/merchant/reasoning/tasks/{task_id}` | 事实、方案、PG 与事件快照 |
| `GET /api/merchant/reasoning/tasks/{task_id}/events?after=0&limit=100` | 按序读取事件；最多 200 条 |
| `POST /api/merchant/changes/{id}/apply` | 零售请求体携带卡片的 `preview_digest` |

调试接口不能读取其他会话或商家的任务。临时批准标记在异常路径同样清理。后台已有认证边界仍是演示会话机制，不是生产认证系统。

默认审计位置为 `runtime/reasoning.sqlite`，文件权限为 0600，不纳入 Git。`records` 使用 `(environment_id, merchant_id, kind, id)` 复合键，按类型保存任务、观察、方案、审批、请求和执行回执；`events` 是只追加事件序列。请求副本保存在私有存储中，排除模型思考块；对外调试仅提供受限事件与请求摘要，不提供私有请求正文。

失败指导的输入与模型文本输出保存在私有 `guidance_failures` 记录中，按失败事件 ID 关联，不进入调试 API、对话历史或后续模型请求；前端只显示错误类别和字段路径，不显示原始失败输出。

```bash
python3 -m commerce_reasoning.cli replay --trace runtime/evaluations/<run_id>/T01.jsonl
```

重放命令只展示审计轨迹，不重新执行工具。

## 评测

```bash
python3 -m pytest commerce-reasoning/tests
python3 -m commerce_reasoning.cli evaluate --manifest evals/commerce_reasoning/manifests/pilot.json --variant C0
python3 -m commerce_reasoning.cli evaluate --manifest evals/commerce_reasoning/manifests/pilot.json --variant O
python3 -m commerce_reasoning.cli evaluate --manifest evals/commerce_reasoning/manifests/pilot.json --variant T
python3 -m commerce_reasoning.cli evaluate --manifest evals/commerce_reasoning/manifests/pilot.json --variant P
```

公开回归集有 T01–T24。每个 case 重建 Backend、账本、会话、memory、固定时钟及 SQLite，覆盖未知/零销量、规格、来源、冲突、审批、版本、幂等、失败提交、提示注入与跨租户请求。

四组共用模型、串行策略、执行检查和预算，统一关闭 analysis。O 提供语义事实；T 把同源局部步骤作为文本；P 保留局部图拓扑。C0 仍使用同一计算工具与检查，不能将执行强化的收益归因给 PG。

结果写入 `runtime/evaluations/<run_id>/`：JSON 报告、Markdown 摘要、每例 JSONL 和 SQLite。基础设施失败单独计数，不删除失败尝试；成功率附 Wilson 区间。未返回的模型 usage 不估造，发生未计量调用时成本报告只能提供已知 token 下界。没有价格配置不推算金额。单次试评不支持统计显著的效果声明。

训练、验证、最终测试 manifest 按场景族隔离，另有结构校验防止组间重叠；这些是人工设计的小语料，不宣称代表真实业务分布。公开 pilot 不作为未见测试集。验证清单默认每例重复三次。

## 离线候选与发布

```bash
python3 -m commerce_reasoning.cli evolve --config configs/evolution.yaml --training runtime/training-diagnostics.json --dry-run
python3 -m commerce_reasoning.cli evolve --config configs/evolution.yaml --patch runtime/proposal.json --dry-run
```

诊断必须标记 `role=training`。Refiner 只得到训练诊断、固定动作和谓词、当前图及拒绝摘要。候选只允许新增/删除节点或边、修改边属性；修改基线哈希、权限字段、未知动作、不可达出口等都会被拒绝。模型输出保留在候选目录，不改变 active 指针。

验证候选时，将候选图路径放入另一份 ReasoningConfig；分别用 P、E 对同一验证清单评测。安全回归证据需绑定候选图哈希：

```bash
python3 -m commerce_reasoning.cli verify-safety --config configs/candidate.yaml --out runtime/safety.json
python3 -m commerce_reasoning.cli validate-candidate --baseline runtime/baseline/report.json --candidate runtime/candidate/report.json --safety-report runtime/safety.json --out runtime/candidate-validation.json
python3 -m commerce_reasoning.cli publish --config configs/candidate.yaml --validation runtime/candidate-validation.json --approved-by '<reviewer>'
python3 -m commerce_reasoning.cli rollback --manifest knowledge/releases/<release_id>/manifest.json
```

发布要求三次独立验证、安全回归通过、无安全违规、成功率不降低、关键失败类别不恶化、总 token 不超过基线 1.5 倍，且 usage 完整。报告还必须匹配模型、任务、环境与配置。候选接受/拒绝测试使用明确标注的合成数据，只证明验证机制，不证明模型优化收益。

初始人工图通过 `publish --initial` 绑定真实回归证据形成版本。发布保存不可变文件和哈希，原子切换 active 指针；服务启动读取该版本，现有服务实例和任务继续使用已加载版本。应用新发布版本需重启部署。回滚知识不会撤销库存变化。

## 验证命令

```bash
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest -q
python3 scripts/check.py
node scripts/check_retail_i18n.cjs
cd examples && npm run build
```

实现以当前项目的中英文改造提交为基线。原设计文档和参考目录保留，不会把 `TO_IMPLEMENT` 标记当成执行检查。已测结果、故障与限制记录在同目录的实施报告中。

## 本体语义依赖扩展

新增 `semantic_context_mode: legacy | closure`，默认仍为 legacy。Closure 根据当前局部 PG 的动作／状态和已确认目标类型补全定义，不替代现有事实或执行检查。新版受审查发布才可在正常 Runtime 开启 closure；旧 active 不会被工作区覆盖。

实现、离线检查、配对评测和发布操作见 [semantic-context.md](semantic-context.md)。本次没有运行付费模型对照或切换 active，不能据此声称成功率提升。
