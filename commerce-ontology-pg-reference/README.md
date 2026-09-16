# commerce-agents Ontology / PG 参考配置包

这是技术设计文档的附属材料，不是已实现的插件或 Agent。基线提交：`fd4d59224ab96b43c6dc6888207c67b3bd5a24cf`。

## 文件

| 文件 | 用途 |
|---|---|
| ontology.retail.v1.yaml | 对象、关系、动作、检查引用、状态与公式 |
| inventory_restock.v1.json | 完整初始 PG：15 个节点、22 条边 |
| predicates.v1.yaml | 三值谓词的语义规格，函数尚未实现 |
| pg.schema.json | PG 结构 JSON Schema |
| reasoning.example.yaml | 新增 ReasoningConfig 的设计示例，不可直接塞入原配置 |
| task.T01.example.json | 正常补货案例及终态断言示例 |
| *.prompt.txt | 指导、Solver集成、Refiner提示模板 |
| validation-report.json | 本配置包实际完成的结构校验范围 |
| SHA256SUMS.json | 配置文件内容摘要 |

## 使用顺序

先按主文档 M0/M1 固定基线、统一执行路径及测试环境，再实现本体注册表、观察适配和补货工具。实现图加载器、谓词函数、Guidance及评测后，才启用这些配置。

`TO_IMPLEMENT_AND_TEST` 与 `TO_IMPLEMENT_OR_BIND_AND_TEST` 是未实现标记。包中没有可以直接用于执行的权限检查或并发保护，不能用“配置存在”代替实际检查。

`reasoning.enabled` 默认关闭；核心安全强化应独立存在，不受该开关影响。不要为运行样例关闭原项目的 `require_host_approval`。

## 校验范围

已完成JSON Schema、节点／边唯一性、动作／谓词／状态／关系引用及可达性检查。未运行 commerce-agents、谓词实现、真实业务事务或模型API；不宣称任何成功率提升。
