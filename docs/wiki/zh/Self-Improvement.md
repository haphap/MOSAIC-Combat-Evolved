# 自我改进

MOSAIC 将两种不能混淆的机制严格分开：

- Darwinian v2 评价全部 28 个逻辑 Agent，但只为 24 个非 Decision Agent 提供下游
  usage weight；CRO、Alpha、Execution、CIO 仅参与演化。
- KNOT 是生产 prompt 行为唯一的演化和晋级路径。

## Darwinian v2

每个 Agent 都有角色专属 evaluation object、确定性 PIT label、成熟期限和 rank scope。
分数只更新归属 Agent 的轨道；CIO 组合收益绝不反向分摊给上游 Agent。新增 Agent ID
从零成熟样本开始，24 条 usage-weight 轨道分别从 1.0 冷启动。

十个 Macro 输出保持独立。下游直接接收 accepted output、证据 lineage、operational
reliability 和该 Agent 自己的 usage weight；不存在六因子 bundle 或 Macro stance。
Decision Agent 之间只传递不含 usage weight 的显式 control DTO。

多组件 Agent 的组件权重属于独立、固定的 runtime contract。离线组件校准可以提出
shadow release，但 Darwinian 和 KNOT 都不能直接修改这些权重。

## KNOT 配对演化

KNOT 在预注册 scope 内选择一条成熟轨道，只能对私有 prompt 的 cohort-behavior 块提出
最小行为改动。职责、工具、schema、label、组件权重、immutable stage instruction、数据
catalog 和评分阈值都不可变。

Champion 与 candidate 使用同一冻结 snapshot bundle、tool payload、opportunity set 和
realized market observation，并以不同 capability 生成各自独立的输出、label 和分数。
Agent failure 固定记 `-2`；双方共同的外生排除不计分；输入不对称直接判 pairing contract
失败。

CIO 配对使用专门的 control-shadow 子图。Alpha 只运行一次并由两侧复用；之后两侧分别
执行 proposal → CRO → Execution → CIO final。Alpha/CRO/Execution 控制调用固定为
`KNOT_CONTROL_SHADOW`、不具备生产 reliability 资格，也不能生成自己的 outcome label、
Darwin maturity、usage weight 或 KNOT score。依赖失败会阻断并消费该 pair slot，但不会
给 CIO 记 `-2`；只有 CIO proposal/final 自身失败才归因给 CIO。

晋级至少需要 30 个可问责、非重叠配对样本，并通过已注册的统计、可靠度、holdout regime
和安全门。多 variant mutation 原子发布：任一目标失败，整批拒绝。晋级行为从未来
production roster revision 和空 evaluation track 冷启动；之后最先成熟的 20 个配对可触发
前瞻回滚。

Prompt release 的流量切换仍经过受限 `canary`，失败时使用 `rollback`；这两个运维动作不
改变 KNOT 的配对、归因或晋级合同。

## Prompt 与 release 边界

生产加载固定 commit 的私有 release：8 个 cohort × 28 个 Agent × 2 种语言，共 448 份
prompt。bundled prompt 只是最小 fake/offline fallback，不能成为 KNOT champion。runtime
合同、研究控制、KNOT metadata、provider binding 和 tool payload 都不得进入模型可见
prompt 文本。

旧 Delta-Sharpe Autoresearch 只供诊断和历史审计：评价结果为 `legacy_unverified`，直接
keep/merge 已禁用，人工 domain review 只能记录拒绝。历史回测演化位于隔离 sandbox
分支，不存在通往当前生产 release 的边。

合同与运维细节见[宏观 Agent 职责合同](../../macro_agent_role_contracts.md)和
[位置感知演化 runbook](../../runbooks/position_aware_prompt_evolution.md)。
