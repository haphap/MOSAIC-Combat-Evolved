# KNOT 精简 Prompt 优化器重构计划

日期：2026-08-04

状态：实施校正中（2026-08-05，PR7/PR18 复审收口）

## 1. 决策与范围

KNOT 的唯一产品职责是：

> 根据目标 Agent 已成熟的历史分析、评估结果和失败案例，生成可解释、可追溯的 Prompt
> Candidate，交给 Autoresearch Runner 在冻结环境中自动试验和选择。

本计划替代旧 KNOT capability、pair authority、模型调用取证、effect runtime、coordinator ledger
和 terminal-prefix closure 实施目标；旧文件与 PR 仅保留为历史审计，不再继续执行。

`macro-agent-role-contracts-v2-plan.md` 中 Agent 角色、工具、输出、PIT、evaluation object、label、
maturity、Darwinian owner、私有 Prompt 和 RKE shadow-only 等合同继续有效。仅其中“私有 KNOT
在生产 Agent runtime 应用 effect/projection”的要求被本计划替代。

本计划所禁止的“数值 knob”是能直接改写数据门、接受/拒绝、限仓、执行、确定性组件合成或
Darwinian usage 的 runtime effect。只影响模型如何权衡证据、比较 facet、选择分析期限或形成判断
门槛的数值假设，可以作为私有 Prompt 参数参加 Candidate 变异，但只能渲染进私有
`cohort-behavior`，不得获得第二条 runtime 写路径。

本计划不重构通用 Agent outcome 生产、Darwinian usage weight、Model Adapter 的 structured
output、现有 Prompt Release canary/rollback 或 RKE。KNOT 只读取这些系统提供的稳定结果，不取得
它们的写权限。

## 2. 明确非目标

KNOT 不再负责或拥有：

- Agent 模型调用、工具 capability、provider invocation 审计或 HMAC 签发；
- provider schema、raw response、repair、normalization 或 accepted-output persistence；
- blind pair root、candidate capability、strict receipt、replay capsule 或 authority ledger；
- domain feature、确定性 confidence/execution policy、角色、工具、schema 或 runtime effect 变异；
- evaluation object、realized label、normalized score 或 Darwinian weight 生产；
- production release 激活、canary 流量、rollback 或 operator approval；
- 通过 CIO 总收益反向评价上游 Agent；
- 在 daily-cycle 中注入 KNOT runtime binding、hidden context 或 post-output rewrite。

如果将来需要分布式、不可信 worker，身份认证应在 RPC、任务队列、对象存储或部署平台边界解决，
不得再次进入 KNOT Candidate/Experiment 领域模型。

本计划的威胁模型是防止普通应用错误、实验条件漂移、数据泄漏、重复写入和不可比较实验；不声称
对抗已控制 runner 进程、Git 对象库和 Scorecard 数据库的特权攻击者。content hash 用于身份与漂移
检测，不是安全签名。当前单机/受信 worker 使用 OS ACL、Git、SQLite 事务、外键和唯一约束即可。

## 3. 目标架构与所有权

```text
Agent accepted analyses + mature Agent-specific outcomes
 + prior-round validation paired summaries promoted to training metadata
                         |
                         | training snapshot only
                         v
               KNOT Prompt Mutator
                         |
                         v
                 Prompt Candidate
                         |
                         v
            Autoresearch Experiment Runner
       frozen validation/holdout + model/tools/evaluator
                         |
                         v
            Metrics + tail failure cases
                         |
                         v
                 Promotion Decision
                         |
                         v
        existing Prompt Release Gate/Canary/Rollback
```

| 组件 | 唯一职责 | 明确禁止 |
| --- | --- | --- |
| KNOT Prompt Mutator | 诊断训练结果、提出 Prompt 改写、记录假设与 lineage | 读取当前轮原始 validation/holdout 分区或 holdout 结果、执行 Agent、评分、晋升；只允许接收已完成旧轮次的 paired-delta 训练元数据 |
| Autoresearch Runner | 冻结实验环境、运行 champion/candidate、聚合指标与失败案例 | 修改 Candidate、Evaluator 或生产 release |
| Evaluator | 从既有 Agent-specific evaluation object/outcome 合同确定性评分 | 读取候选身份后改变规则、使用 CIO 总收益替代上游 outcome |
| Promotion Authority | 应用统计门、不退化门、canary、activation、rollback | 生成 Candidate、修改实验结果 |
| Model Adapter | provider schema、raw response、repair、normalization | 向 KNOT 暴露 provider-specific 中间协议 |
| Darwinian | 根据既有成熟 outcome 更新 usage weight | 直接修改 Prompt，或把 KNOT 结果当作生产 outcome |

KNOT 和 Darwinian 是同一成熟 outcome 系统的两个独立只读消费者。KNOT 结果只可能改变 Prompt
版本；Darwinian 结果只可能改变 usage weight。两者不得相互写入或把一方的权重当作另一方的标签。

## 4. 最小领域合同

### 4.1 Candidate

Prompt 正文和 mutation policy 继续保存在私有 Prompt 仓库。公开仓只保存 schema、稳定类型和
不可反推正文的引用/hash。

```ts
interface PromptCandidate {
  schemaVersion: "prompt_candidate_v1";
  candidateId: string;
  parentId: string;
  parentPromptCommit: string;
  parentPromptHashes: { zh: string; en: string };
  target: {
    agentId: string;
    stage: string;
    cohort: string;
  };
  promptRefs: { zh: string; en: string };
  promptHashes: { zh: string; en: string };
  trainingProjectionHash: string;
  excludedSampleIdsHash: string;
  mutatorConfigHash: string;
  mutatorCommit: string;
  mutationCategories: Array<
    | "EVIDENCE_PRIORITY"
    | "TEMPORAL_DISCIPLINE"
    | "CONFLICT_RESOLUTION"
    | "TRANSMISSION_CLARITY"
    | "UNCERTAINTY_CALIBRATION"
    | "TAIL_RISK_CONTROL"
  >;
  mutationSummary: string;
  hypothesis: string;
  behaviorContractHash: string;
  privateLineageHash: string;
  privateStateArtifactHash: string;
  createdAt: string;
}
```

私库内部可以在同一记录旁保存 `{ zh, en }` Prompt 正文；正文不得进入公开 DTO、TUI、CI artifact
或日志。一个 Candidate 原子绑定同一目标的中英文 Prompt pair；语言、语义对齐、角色、工具、输出
schema 和 immutable contract block 继续由现有 Prompt invariant validator 校验。

Candidate 生成前由 Runner 持有最小 split manifest。KNOT API 只接收其中的 training projection，
而不是完整 manifest：

```ts
interface PromptDatasetSampleRef {
  sampleId: string;
  inputRef: string;
  inputHash: string;
  outcomeRef: string;
  outcomeHash: string;
  eventWindow: { startAt: string; endAt: string };
  maturedAt: string;
}

interface DatasetPartition {
  snapshotHash: string;
  windowStartAt: string;
  windowEndAt: string;
  samples: PromptDatasetSampleRef[];
}

interface DatasetSplitManifest {
  schemaVersion: "prompt_dataset_split_v1";
  splitId: string;
  target: { agentId: string; stage: string; cohort: string };
  trainingProjectionHash: string;
  cutoffAt: string;
  training: DatasetPartition;
  validation: DatasetPartition;
  holdout: DatasetPartition;
  evaluatorVersion: string;
  createdAt: string;
}
```

### 4.2 冻结实验环境与结果

```ts
interface PromptExperiment {
  schemaVersion: "prompt_experiment_v2";
  experimentId: string;
  familyId: string;
  candidateId: string;
  championId: string;
  target: { agentId: string; stage: string; cohort: string };
  championPromptCommit: string;
  championPromptRefs: { zh: string; en: string };
  championPromptHashes: { zh: string; en: string };
  candidatePromptRefs: { zh: string; en: string };
  candidatePromptHashes: { zh: string; en: string };
  datasetSplitId: string;
  datasetSplitManifestHash: string;
  promotionPolicyVersion: string;
  promotionPolicyConfigHash: string;
  modelConfigHash: string;
  toolConfigHash: string;
  componentCalibrationSnapshotHash: string;
  darwinianUsageSnapshotHash: string;
  executorAdapterHash: string;
  evaluatorAdapterHash: string;
  evaluationBinding: {
    evaluationObject: string;
    evaluationObjectSchemaVersion: string;
    primaryLabelId: string;
    scoringContractVersion: string;
    outcomeContractVersion: string;
  };
  evaluatorVersion: string;
  evaluatorConfigHash: string;
  codeCommit: string;
  repeatSeeds: number[];
  runIds: string[];
  metrics: Record<string, number>;
  tailFailureCaseRefs: string[];
  status:
    | "PENDING"
    | "VALIDATION_RUNNING"
    | "VALIDATION_COMPLETE"
    | "HOLDOUT_RUNNING"
    | "COMPLETE"
    | "FAILED";
  holdoutOpenedAt: string | null;
  createdAt: string;
  completedAt: string | null;
}
```

每个 run 只需要 `runId`、`experimentId`、`side`、`sampleId`、`seed`、状态、Agent 输出引用、指标、
非空 `effectiveInputHash` 和可选 `traceRef`。包括确定性计分失败在内，任何 `COMPLETE` run 都必须绑定
实际有效输入；数据库唯一约束负责幂等，不为每个中间对象创建 hash、receipt 或签名链。

provider schema/raw/normalized 数据只属于 Model Adapter 的可选私有诊断 trace。trace 关闭或过期
不影响已完成 Experiment 的身份；若某个 promotion policy 明确要求保留 trace，则由该 policy 将其
列为普通必需 artifact，而不是升级为 KNOT authority。

### 4.3 选择与晋升

```ts
interface PromotionDecision {
  schemaVersion: "prompt_promotion_decision_v1";
  decisionId: string;
  experimentId: string;
  candidateId: string;
  policyVersion: string;
  decision: "ELIGIBLE" | "REJECTED";
  reasons: string[];
  metricSummary: Record<string, number>;
  decidedAt: string;
}
```

`ELIGIBLE` 只表示 Autoresearch 自动选择完成。KNOT 和 Runner 都不能直接写 active pointer。
Promotion Authority 把合格 Candidate 作为普通 Prompt-only release 交给现有
`staged -> canary -> active|rolled_back` 流程；生产 activation 继续服从既有授权和 rollback。

## 5. 数据分区与防止自我打分

每轮 evolution 在 Candidate 生成前冻结一个 PIT、Agent-specific 的 split manifest：

- `training`：KNOT 唯一可见分区，只含 cutoff 前已成熟的分析、label、score、失败案例，以及已完成旧
  轮次、与当前 reserved IDs 不重叠的 validation paired-delta 摘要；
- `validation`：Runner 用于比较和自动选择当前 Candidate，当前轮原始样本、输出和分区对 KNOT 不可见；
- `holdout`：最终 Promotion Gate 使用，每轮只解封一次，Candidate 和选择器均不可见；
- 三个分区的 `sample_id`、原始事件窗口和 outcome maturity 不得重叠；金融时间序列优先使用前瞻
  时间切分，不使用会泄漏未来状态的随机切分；
- Candidate 必须绑定排序后的 validation + holdout reserved sample IDs hash；Runner 在第一次
  validation 调用前与冻结 split 重算比对，不一致则整轮拒绝；
- Candidate 在 validation 或 holdout 结果产生后不可修改。holdout 失败即关闭该 evolution round；
  不允许继续针对同一 holdout 调参；
- Prompt 与 Evaluator 不得在同一 experiment 中同时变化。Evaluator 版本变化必须形成新的基线轮次；
- champion/candidate 使用相同 sample IDs、模型、工具、schema、decoding、Evaluator、代码和 seeds；
- 逻辑上保留 paired comparison，但只通过同一 Experiment manifest 和数据库唯一约束表达，不再创建
  pair authority 系统。

KNOT 的训练输入应优先提供确定性摘要：分数分布、常见失败类别、关键尾部案例引用、证据使用缺口
和可靠度问题。原始 provider trace 默认不进入 KNOT 输入。

## 6. 评价与 Promotion Policy

每个 Agent 继续使用 `agent_outcome_contract_manifest_v2` 指定的 evaluation object、label、maturity
和 rank scope。Promotion Policy 至少检查：

1. 最低成熟样本量与重复运行次数；
2. champion/candidate 的 paired Agent-specific normalized score delta；
3. 时间序列适用的置信区间或 block bootstrap 下界；
4. 多 Candidate 同轮选择时的 multiple-comparison 修正；
5. schema/contract/tool failure rate 不上升；
6. 关键尾部案例和具名高优先级 failure suite 不退化；
7. 平均指标改善不能掩盖关键分位数、关键 regime 或拒绝/无行动行为退化；
8. validation 选择通过后，独立 holdout 仍满足同一最小门槛。

具体阈值、lookback 和统计参数属于版本化 Promotion Policy；私库保存值，公开记录只暴露
`policyVersion/configHash` 与通过/拒绝原因。这些参数不得进入 Agent Prompt。

## 7. 存储与隐私边界

新路径只保留两类不可变预注册 manifest 和三类实验结果记录：

1. 内容寻址的 Dataset Split manifest；
2. 内容寻址的 Candidate Family manifest，用于冻结同轮候选集合、multiple-comparison policy
   和一次性 holdout 归属；
3. Prompt Candidate；
4. Prompt Experiment；
5. Prompt Experiment Run。

Split 与 Family 不是第二套评估结果或晋升状态：写入后不可修改，不保存 metrics、Decision 或
Prompt 正文。把两者重复内嵌到每个 Experiment 会扩大重复面，也无法用数据库约束唯一的
`split -> family` 与一次性 holdout 消费，因此保留各一份 canonical manifest。

Promotion Authority 必须从上述冻结记录重算选择结论，并把通过的结论作为 Prompt Release evidence
交给既有 release 流程；不再建立一张可与 Experiment 漂移的重复 decision 表。TUI 的 decision
展示同样来自可重算的当前 Experiment/Release 状态。

可在现有 Scorecard SQLite 中实现，使用事务、外键和唯一约束；不引入新的 ledger 数据库。Prompt
正文、训练案例正文、失败案例详情和 raw trace 位于私库或本地私有缓存。公开提交物只包含 schema、
迁移、hash/ref、脱敏 fixture 和审计结果。

旧 KNOT 表和本地 runner artifact 第一阶段只读保留，不做破坏性迁移。切换完成后不再写入：

- `knot_*capabilit*`、`knot_*pair*`、`knot_*authority*`、`knot_*receipt*`；
- replay capsule/consumption；
- 32-effect/512-scope runtime capability 状态；
- KNOT coordinator command/event/workset 状态。

旧表最终是否物理删除是独立的数据保留决策，不是本重构的完成条件。

## 8. 当前实现的处理方式

### 保留并复用

- 私库 `runtime/typescript/src/autoresearch/prompt_mutator.ts` 中的单 facet 参数变异、确定性双语渲染
  和 invariant 检查；
- 普通 Agent runner、Model Adapter structured-output 与 accepted-output/outcome 系统；
- Agent-specific evaluation object、maturity、label 与 normalized score；
- `prompt_release_manager.ts`、`release_registry.ts` 的通用 canary/activation/rollback；
- 私有 Prompt Git 仓库、commit/hash lineage 和 prompt leak boundary；
- TUI 从 Candidate summary、hypothesis、metrics 和 failure cases 渲染的人可读说明。

### 提取后移除 KNOT 耦合

- `knot_research_capture.ts`：Model Adapter 需要的 schema/normalization 保留在 adapter；删除 Agent
  accepted path 对 KNOT capability、provider projection 和 replay capsule 的依赖；
- `formal_knot_runner.ts`：用小型 `prompt_experiment_runner.ts` 替换；不迁移 capability、pair root、
  strict receipt、checkpoint 或 provider 取证状态机；
- `formal_knot_bridge_authority.ts`、`private_knot_runtime.ts` 和相应 RPC：保留通用 Prompt/Release
  所需部分，删除 KNOT execution-time authority；
- 私库 `knot_v2.py`、`coordinator_ledger.py`、effect/consumer/fitness registries：先标为
  `legacy_read_only`，提取仍被通用 outcome/evaluator 使用的纯函数后退出 active runtime manifest；
- `StageFormalKnotPromotionReleaseOptions` 等专用入口改为消费普通 `PromotionDecision` 的通用
  Prompt-only staging，不把 KNOT ledger 传入 Release Manager。

### 明确禁止继续继承

- 不从 PR17/PR6 的旧 authority branches 整体 cherry-pick；
- 不把 40-pair terminal prefix、rotation golden、32-effect matrix 或 4 failure probes 改名后继续；
- 不为了兼容旧审计而让 daily-cycle 双写新旧 KNOT 协议；
- 不把 historical legacy output 计入新 Candidate 的成绩或 promotion evidence；
- 不将旧 `emerging_markets`、`news_sentiment` 或其他 legacy-unverified Agent 记录迁入新训练集。

## 9. 实施工作包

### WP0：冻结旧设计并保存审计

- 停止旧 real runner；
- 本地保留隔离目录、SQLite、console log、summary 和 artifact hashes；
- 把旧计划标记为 superseded，旧表/代码进入 read-only inventory；
- 禁止继续 terminal-prefix、rotation、matrix 及后续旧发布门。

验收：无旧 runner 进程；本地审计目录与文件权限收紧；记录停止点和账本计数。

### WP1：建立唯一合同源

- 新增 Candidate、split manifest、Candidate Family manifest、Experiment、run 和派生
  PromotionDecision 的 Zod/JSON schema；PromotionDecision 不建立独立持久化表；
- TypeScript 为运行时唯一 DTO 合同源，生成 bridge/Python 验证合同，禁止手写重复字段表；
- 明确 public/private 字段和 trace retention；
- 给所有 28 Agent/29 stage 绑定既有 outcome contract，不新增 KNOT effect registry。

验收：schema round-trip、额外字段拒绝、私有正文泄漏测试、28-Agent 参数化合同测试通过。

### WP2：把 KNOT 收缩为私有 Prompt Mutator

- KNOT 只接收 training snapshot 的确定性摘要、具名失败案例引用和已完成旧轮次的 paired-delta
  训练元数据；
- 生成双语 Prompt Candidate、mutation summary 与 hypothesis；
- 只允许 cohort-behavior Prompt-only diff，角色、工具、schema 和 immutable block 不可变；
- Candidate 写入私有 Prompt Git，记录 parent/candidate/training/mutator lineage；
- 删除 numerical runtime effect、确定性 confidence/execution policy 和 production runtime
  projection 的生成入口；Prompt-only 数值参数只通过私有 renderer 改变 Candidate 正文。

验收：KNOT 无当前轮原始 validation/holdout API；Candidate 正文/hash、冻结训练输入与 lineage 可验证；不要求
重新调用随机 mutator 得到逐字相同输出；Prompt invariants 和 private leak gate 通过。

### WP3：实现通用 Autoresearch Runner

- 新建 `prompt_experiment_runner.ts`，按 Experiment manifest 调用普通 Agent/runtime；
- champion/candidate 使用同一 sample/seed/config，允许安全并发但不改变顺序与聚合结果；
- Model Adapter 内部处理 provider schema、repair 和 normalization；
- 持久化 run 状态、指标、失败案例引用和可选 trace；
- 失败/重试依靠普通 run idempotency，不创建 capability、receipt 或 replay capsule。

验收：中断恢复不重复 run；环境漂移拒绝；同一 manifest 聚合 byte-stable；adapter 单测与 Runner
领域测试互不依赖。

### WP4：隔离 Evaluator 与统计选择

- 复用 Agent-specific evaluation object/outcome/maturity；
- 实现 validation 选择、holdout 单次终审、重复 seeds、统计显著性和关键尾部不退化；
- 禁止 Evaluator 与 Prompt 同轮变更；
- 生成 `PromotionDecision`，不写 release pointer。

验收：train/validation/holdout 泄漏、样本重叠、Evaluator 漂移、multiple-comparison、尾部退化和
CIO 反归因污染均有失败测试。

### WP5：接入现有 Promotion Authority 与 TUI

- 把 `ELIGIBLE` Candidate 作为普通 Prompt-only release staged；
- 复用 canary SLO、authorized activation、rollback 和 previous champion；
- KNOT/Runner 无 active pointer 写权限；
- TUI 展示 Candidate hypothesis、mutation summary、核心指标、置信区间、尾部失败案例和当前
  release 状态，不展示 Prompt 正文或 raw trace。

验收：shadow 自动选择、canary、active、rollback 各一条隔离测试；缺少授权时保持 staged。

### WP6：切换 active path 并封存旧协议

- daily-cycle、Agent factory 和 common loop 不再读取 `knot_research_runtime_binding`；
- 删除 active imports/RPC/CLI 到 formal KNOT capability/pair/coordinator；
- 旧表停止写入并标记 `legacy_read_only`；
- 私有 runtime manifest 移除旧 effect/coordinator 执行模块；
- 旧 PR6/PR17 标记 superseded，不合并其完整 authority 实现。

验收：静态 import/RPC 扫描、数据库 writer 探针和 fake daily-cycle 证明旧 KNOT 路径零调用；普通
Agent、Darwinian、outcome 和 release 功能不回归。

### WP7：最终验证与发布

- 公私 generator 各运行两次达到 fixed point；
- public TypeScript typecheck/lint/test，private TypeScript build/typecheck/test；
- Python Ruff、相关 pytest、prompt leak/private boundary、RKE shadow-only、`git diff --check`；
- 29-stage fake daily-cycle；
- 一个 Agent/一个 cohort 的小型本地结构化 shadow smoke，只证明 Candidate -> Experiment ->
  Decision，不激活生产；
- 不运行 100 日测试，也不再运行 40-pair terminal-prefix/rotation golden。

真实模型 smoke 继续使用 128000 runtime context、GPU utilization `0.85` 和 256 MiB 空闲显存门槛；
提交的逻辑 context contract 保持 131072。

## 10. 分支与 PR

- 从执行时最新 `main` 分别创建：
  - public：`codex/knot-prompt-optimizer-simplification-public`；
  - private：`codex/knot-prompt-optimizer-simplification-private`；
- 旧 PR17/PR6 保留历史和交叉链接，但标记 superseded，不继续叠加修复；
- 只选择性移植与新边界独立一致的 Prompt invariant、通用 release 或 adapter 修复，每个 cherry-pick
  必须有新计划中的直接测试理由；
- 私有 PR 先提交 Candidate/Mutator 与私有 fixture；公共 PR 后提交 schema、Runner、Evaluator、
  Promotion adapter、migration、测试和文档；两个 draft PR 交叉链接；
- 不提交 private Prompt、训练/失败案例正文、raw trace、Tushare 原文或 `.mosaic/` 审计目录。

## 11. 完成交付条件

只有同时满足以下条件才完成：

1. KNOT 只能从 training snapshot 生成 Prompt Candidate，无法读取当前轮原始 validation/holdout
   分区或任何 holdout 结果；旧轮次 paired-delta 只有在转为 PIT 训练元数据后才可见；
2. Candidate 只改变 Prompt cohort behavior，不改变角色、工具、schema、Evaluator 或 runtime policy；
3. Runner 能在冻结环境中重复执行 champion/candidate，并记录最小 Experiment/Run 对象；
4. 自动选择同时通过样本量、显著性、关键尾部不退化和独立 holdout；
5. KNOT 和 Runner 均不能写 active release，现有 Promotion Gate 能 canary 和 rollback；
6. Model Adapter 的 provider schema/repair/normalization 不再出现在 KNOT 领域合同；
7. daily-cycle、Agent runtime 和 bridge 不再消费 KNOT capability/pair/replay/coordinator；
8. Darwinian、Agent-specific outcome、RKE shadow-only、私有 Prompt 和 TUI 人可读说明边界保持不变；
9. 旧 KNOT 账本只读可审计，但不参与新 Candidate 评分、晋升或生产运行；
10. 公私门禁、fake smoke 和小型 shadow smoke 通过，且没有运行旧的重型 closure 流程。

## 12. Facet 评价闭环补充

生产链路不再使用无调用方的公开 `prompt_behavior_evaluation_v1` facet-score builder。公开仓只导出
严格、hash-bound 的 `prompt_training_projection_v1`：目标 Agent 自己的 accepted-output ref/hash、成熟 outcome、
七个可组合 Macro Agent 的 component signals、CIO 同 run proposal，以及已经完成旧轮次的 validation
paired deltas。当前 validation/holdout 的 sample IDs 必须作为 exclusions 传入；任何重叠实验整轮排除，
当前轮原始 validation 数据以及所有 holdout 字段和结果永不进入 KNOT 请求。accepted-output 与 CIO
proposal 的完整 payload 不跨 bridge；只保留可审计 ref/hash 和评分所需的确定性 metrics。

28-Agent、173-facet 的语义、评价模式和变异规则只存在私库。可独立识别的 component/action facet 使用
该 Agent 自己的确定性 outcome component；无法从一次整体输出可靠归因的 reasoning facet 只接受单
facet Candidate 的 validation paired delta，未实验前保持 `COLD_START`，不得复制 overall score 或使用
LLM judge。每个 Candidate 的目标 facet 写入私有 lineage sidecar，公开 DTO 只保存 sidecar hash；私仓
Candidate commit 原子包含中英文 Prompt、公开 Candidate record 和私有 lineage sidecar 共四个文件。

真实入口为：

```bash
pnpm --dir mosaic-ts dev autoresearch generate-candidate \
  --request <public-safe-request.json> \
  --private-cli <private-repo>/runtime/typescript/dist/cli.js \
  --private-repo <private-repo> \
  --mutation-adapter <private-adapter.js>
```

该入口依次完成 bridge 历史导出、私有 facet snapshot 构造、单 facet 双语变异、私有 Git 发布和公开
Candidate 持久化。少于 30 个角色匹配成熟样本、未来数据、reserved split 重叠、CIO proposal 缺失、
facet mode/lineage/hash 漂移均 fail closed。

## 13. 私有 Prompt 数值参数补充

复审确认旧数值并非同一种权限。最终私有合同按用途分为：234 个 Prompt-only 参数、7 个确定性
owner policy、0 个缺消费者的确定性参数和 4 个退役权重。公开仓只允许保存这组无语义计数及私有
release/contract hash，不保存参数 ID、值、范围、步长、经济解释或 Prompt 正文。

- Prompt-only 参数只改变一个 Agent、一个 cohort、一个 facet 的证据显著性、分析期限或判断门槛；
- 确定性 policy 由其公开 owner/validator 执行，KNOT 只读且不得变异；
- 退役的重复大类权重既不进入 Prompt，也不与 Darwinian usage 再次相乘；
- 每次 Candidate 只能改变一个 scalar 或一个声明过的 atomic normalized group，并由私库从 parent
  state 确定性重放；
- 28 Agent × 8 cohort 的 champion state、双语 Prompt pair 和私有 release manifest 必须原子更新，
  缺 state、越界、步长错误、跨 cohort 写入或 immutable block 变化一律拒绝。

这项补充不恢复旧 effect runtime。KNOT 仍只生成 Prompt Candidate；公开 Runner 仍独立冻结和评分，
Promotion Authority 仍独立负责 canary、activation 与 rollback，Darwinian 仍只调整下游 usage。
