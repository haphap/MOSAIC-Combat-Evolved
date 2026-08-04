# 自我改进

MOSAIC 严格分离 Agent 评价和 prompt 演化：

- Darwinian 按各 Agent 自己的 PIT outcome contract 评价表现，并只在合同允许时提供
  Agent 级 usage weight。
- KNOT 是私有、仅使用 training 数据的 Prompt Mutator；它根据成熟的 Agent 专属结果与
  failure summary 生成双语 Prompt Candidate。
- 公开 Autoresearch Runner 在冻结的 validation/holdout 环境中比较 Champion 与
  Candidate；Prompt Release 独占 canary、激活与 rollback。
- 组件校准是面向七个组合型 Macro 合同的独立半年度、shadow-gated 发布路径。版本化权重
  release 只从未来生效，并采用 append-only/可回滚记录；Darwinian 与 KNOT 都不直接修改
  组件权重。

Macro 输出保持相互独立；公开 runtime 不构造会损失信息的六因子 bundle 或聚合
stance。Decision 角色消费显式 control object，也不会把 CIO 组合收益反向归因给上游
Agent。

公开仓库定义 Agent 职责、工具、输出 schema、证据 lineage、release 引用与 fail-closed
完整性校验，并拥有不含私有文本的 Candidate/Split/Family/Experiment/Run/Decision 合同、
通用 shadow Runner、Promotion Authority 和 Prompt Release。Prompt 正文、training/failure
原文、Mutator 策略与私有晋级阈值不进入公开仓或模型可见 prompt。

生产 prompt release 仍使用受限 `canary` 并支持 `rollback`，但这些发布操作不会暴露或
重新定义私有演化合同。

更多公开边界见[宏观 Agent 职责合同](../../macro_agent_role_contracts.md)和
[公开运维边界](../../runbooks/position_aware_prompt_evolution.md)。
