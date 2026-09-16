# PG 本体语义依赖与上下文检索

本改动以 `adf23373c9fed7d0413fd996fe2e065322b00996` 为基线，落实《下一阶段实施计划》的核心增量：局部 PG 的动作／状态引用 → 显式依赖 → 有预算的定义上下文。它不是新增业务流程、完整 OWL 推理器或模型效果提升报告。

## 1. 当前行为与边界

- 默认 `semantic_context_mode: legacy`，现有 `configs/reasoning.yaml`、`knowledge/releases/active.json` 和历史 release 文件不变。
- `closure` 只用于开启的 T/P/E。关闭总开关后的有效模式是 C0/legacy。校验发生在 CLI、环境变量和 `model_copy(update=...)` 覆盖完成之后。
- 业务工具参数、PG 节点／边、审批、租户、幂等和执行检查不变。工作区本体升级为 1.1.0；工作区 PG 仅升级元数据版本到 1.0.1、配对本体到 1.1.0。
- 仍调用原来的指导模型。依赖解析自身不调用模型；本次未实现可选 render、向量检索、缓存或新一轮 PG 自动优化。
- `closure` 的完整定义仅进入指导模型。主 Agent 仍收到原有事实和生成的指导，不再重复注入整份定义。

## 2. 配置与源码

| 文件 | 用途 |
|---|---|
| `knowledge/ontology/retail.v1.yaml` | 11 对象、8 关系、9 动作、9 状态、14 属性、16 检查的定义与引用 |
| `knowledge/ontology/ontology.semantic.schema.json` | 与实际 Pydantic 校验器匹配的 Schema |
| `semantic_models.py` | 严格协议、稳定错误、公共投影与 legacy 六字段投影 |
| `semantic_registry.py` | 重复 YAML 键、类别错配、缺失引用、继承环等校验；不可变快照查询 |
| `semantic_context.py` | 无 I/O 的闭包、预算、去重与依赖来源 |
| `semantic_runtime.py` | 只使用保留的 PG 节点与已确认目标类型，隔离定义和事实 |
| `semantic_release.py` | working/published 来源、真实生效模板、代码身份及受证据约束的发布 |
| `semantic_evaluation.py` | 固定比较因素、语义构建计量和兼容性／回归门槛 |
| `semantic_cli.py` | 不加载 `.env`、不调用模型的检查和验证命令；显式人工发布命令 |
| `configs/experiments/p-{legacy,closure}.yaml` | 除语义模式外相同的离线比较配置 |

以上 Python 模块都在 `commerce-reasoning/commerce_reasoning/`。现有 `ontology.py`、`prepare_request()` 和 CLI 是薄接入点；没有把现有模块改成同名 package。

## 3. 显式依赖协议

```yaml
id: StageRestock
# 原工具、效果、来源及 checks 保持不变
semantic_refs:
  required:
    entities: [SellableItem, RestockPlan, StagedChange]
    relations: [plan_for, change_targets, realized_by]
    properties: [RestockPlan.quantity, RestockPlan.status, StagedChange.status]
  optional:
    entities: [Observation]
    relations: [supported_by]
    properties: [Observation.value_status]
```

九个状态也使用同一协议。例如 `waiting_for_host` 的 required 包含 StagedChange、ApprovalRecord、Operator、approved_by 和两项属性，但不包含可执行的批准动作。

引用按 `(kind, id)` 解析。类名／关系名相同不代表同一个定义。属性显式指定 `owner_ref`，`source_field` 只是字段标识，不执行 Python 表达式、SQL 或网络读取。

JSON Schema 校验不是全部校验：跨定义引用、重复 ID、required/optional 重叠、继承环仍由注册表验证。Schema 文件必须与正在运行的校验器一致，不允许从远程 `$ref` 加载代码。

## 4. Builder 的确定性规则

1. 收集**已保留局部图**的 `action_ref`、`state_ref`，以及观察适配器确认的目标类型。不按节点名称猜类型，不重新搜索全图。
2. 先合并所有 required：动作／状态声明的依赖、动作 checks、实体父类型、关系全部 domain/range、属性 owner。
3. 父类型仅向上补全，不扩散到兄弟类型或全量子类；宽 domain/range 的所有端点必须保留。
4. Required 全部满足后再处理 optional；每个 optional 根及其依赖作为一个原子组加入或舍弃。Required 身份优先，不因 optional 裁剪而移除。
5. 限制定义数量、依赖深度和**实际公共投影的 UTF-8 字节数**。Required 装不下即显式失败，不输出截断的假完整定义。
6. 输出按类型化 ID 排序，集合语义字段排序；公共内容 hash 不含时间、路径诊断或请求 ID。输入顺序改变不改变输出。
7. 依赖轨迹记录种子和补全路径；检查项只投影 ID 与说明，不投影内部 implementation 路径。

接口：

```python
bundle = SemanticContextBuilder().build(
    registry=registry,
    subgraph=retained_subgraph,
    observed_type_ids=("Variant",),
    limits=SemanticDefinitionLimits(
        max_definitions=64,
        max_dependency_depth=12,
        semantic_budget_bytes=16000,
    ),
)
# bundle.public / bundle.diagnostics / bundle.content_hash
```

这不是本体上的第二次 2-hop：PG 两跳决定过程范围，定义侧按显式依赖做有限闭包。

## 5. legacy 与 closure

Legacy 动作契约只投影原来的六个字段：`id`、`tool_binding`、`effect`、`side_effect`、`allowed_origins`、`checks`。新增描述或 semantic_refs 不会自动混进旧模式输入。

测试中的完整请求 golden 来自**未修改的基线 Runtime**和 FakeClient，以 `PYTHONHASHSEED=0` 固定原代码 set 迭代顺序；不删除库存、任务阶段、动作或审批信息，也不在测试中自动重生成 expected。基线捕获没有模型 API 调用。

Closure 中：

- `semantic_context` 继续表示实际事实，不从定义补出库存、销量或批准状态。
- `semantic_definitions` 表示定义，不充当授权。
- T 与 P 使用相同定义。T 仅保留原有步骤文本；诊断路径不进入 T 请求，以免偷偷补回图拓扑。
- `WAIT_APPROVAL` 在 hops=0 时仍能取到状态语义，`enabled_actions` 不会因此新增 ApplyApprovedChange。
- 构建失败沿用事实及原 Skill／执行保护，记录 `semantic_context_failed`；尚未发送模型请求就不增加指导调用或未计量 usage。
- 实际指导调用失败仍记录 `guidance_failed`，未知 usage 不伪造成零。角色调用数表示应用层请求尝试，不保证等于供应商底层 HTTP 重试次数。

## 6. 预算与调试

`context_budget_tokens` 仅在 legacy 兼容路径使用原来的字节倍率，不能把它当精确 tokenizer 数。Closure 使用 `pg_budget_bytes`、`semantic_budget_bytes`、`guidance_input_budget_bytes`；最后一项按实际发送的规范 JSON 编码计数。

配对实验把 legacy 的倍率预算和 closure 的显式预算对齐：PG 20,000 bytes、指导数据 30,000 bytes，semantic 子预算 16,000 bytes。它们是通过无模型预检的候选上限，不是推荐的生产最优参数，也不是已证实划算的配置。

只读调试面板显示配置／生效模式、知识来源、定义数量、字节数、内容 hash、动作和状态种子、依赖路径及 optional 裁剪。它不提供编辑或授权按钮。中文／英文界面标签均提供；知识定义正文按原始语言显示，不声称已经翻译所有定义。

## 7. 离线命令

在项目已按原 requirements 安装之后执行：

```bash
python -m commerce_reasoning.cli validate-knowledge \
  --config configs/reasoning.yaml --knowledge-source published

python -m commerce_reasoning.cli inspect-semantics \
  --config configs/experiments/p-closure.yaml --knowledge-source working \
  --node WAIT_APPROVAL --hops 0 \
  --fixture commerce-reasoning/tests/fixtures/semantic_context/waiting.json \
  --out runtime/semantic-inspection/waiting.json

python -m commerce_reasoning.cli preflight-semantics \
  --config configs/experiments/p-closure.yaml --knowledge-source working \
  --out runtime/semantic-inspection/preflight.json

python -m commerce_reasoning.cli verify-semantics \
  --config configs/experiments/p-closure.yaml --knowledge-source working \
  --out runtime/semantic-verification/report.json
```

预检使用真正的 SubgraphRetriever，覆盖 15 节点 × 3 个 hops × 3 种已知类型情形，共 135 个组合。它检查结构和预算，不模拟真实模型成功率。Fixture 不足会报错，不调用模型填充；这不是生产输入接口。

`verify-semantics` 分别运行新增语义测试与执行安全／运行集成测试，将命令、输出 hash 和当前知识／代码／配置／模板身份绑定。测试只用模拟业务和 FakeClient。该结果**不能单独授权新版本发布**。

## 8. 真实模型比较：需要另外授权运行

以下命令会调用配置的模型服务，本次开发没有执行：

```bash
python -m commerce_reasoning.cli evaluate \
  --config configs/experiments/p-legacy.yaml --variant P \
  --manifest evals/commerce_reasoning/manifests/validation.json \
  --out runtime/semantic-experiments/legacy
python -m commerce_reasoning.cli evaluate \
  --config configs/experiments/p-closure.yaml --variant P \
  --manifest evals/commerce_reasoning/manifests/validation.json \
  --out runtime/semantic-experiments/closure
```

两组使用同一新代码、本体、PG、工具、检查、模型、提示模板、任务和实际预算。只有上下文构造方式不同。报告增加 schema／builder／源码／真实模板／有效配置／比较清单 hash，并分别保留有效请求和全部提交的分母及区间；构造失败与模型失败分开统计。

`compare-semantics` 明确检查 P_legacy/P_closure 的固定因素、提交数量、完整 usage、安全、关键失败和 token 门槛。不把单次无回归当统计显著提升，也不覆盖之前 96 次试评或历史失败报告。

```bash
python -m commerce_reasoning.cli compare-semantics \
  --config configs/experiments/p-closure.yaml \
  --baseline runtime/semantic-experiments/legacy/BASELINE_RUN/report.json \
  --candidate runtime/semantic-experiments/closure/CANDIDATE_RUN/report.json \
  --verification runtime/semantic-verification/report.json \
  --out runtime/semantic-comparison.json
```

## 9. 发布与兼容

本次没有修改 active 指针，也没有发布新的语义版本。直接用 closure 配置启动现有生产式零售 Runtime 会拒绝旧 release，这是预期保护，不会回退工作区来猜依赖。

新的 `semantic_extension` 发布要求：身份匹配的语义与执行安全证据、可比的独立 validation（每项至少三次）、完整成本计量、无任务及关键类别退化、token 不超过基线 1.5 倍，以及明确审查人。`publish --initial` 不能启用 closure。

有相应真实证据并经审核后，才使用：

```bash
python -m commerce_reasoning.cli publish-semantic \
  --config configs/experiments/p-closure.yaml --knowledge-source working \
  --validation runtime/semantic-comparison.json --approved-by REVIEWER \
  --out runtime/semantic-published.json
```

这个命令会创建新发布目录并切换 active，不能在未审核时执行。它不改变库存。

发布包含本体、PG、谓词、图 Schema、新语义 Schema，以及**实际生效的** guidance/solver 字符串。新版 loader 从快照读取这些模板，FakeClient 测试验证真正发出的 system 内容；旧发布在 legacy 下保留原常量路径。

源码身份递归覆盖 reasoning、merchant core、commerce common，并覆盖 Runtime、宿主、Backend 和依赖锁定文件。Hash 是内容一致性检查，不替代部署权限、身份认证或文件访问控制。

回滚必须配套兼容代码、配置和旧 manifest。旧本体＋closure 预期失败；旧本体＋legacy 继续可用。知识回滚不撤销已经发生的业务写入。

## 10. 验收与未完成项

新增测试覆盖：严格引用、重复键、继承环、必需依赖完整性、宽关系端点、属性归属、状态单节点、可选组原子裁剪、确定性、无 I/O、无输入突变、legacy 完整请求、T/P 定义一致、tool_result 配对、调用计数、作用域、版本与模板绑定、回滚、比较因素和预算预检。

执行记录见 `semantic-context-progress.md`。发布单元测试使用明确标注的合成证据和临时目录；它们证明机制，不证明模型收益，也没有把合成记录写进现有发布历史。

本次不包括：付费模型对照、实际语义版本发布、render、向量索引、多图路由、新业务 PG、跨进程库存事务或生产认证。没有这些证据时只声称机制与离线回归已实现。
