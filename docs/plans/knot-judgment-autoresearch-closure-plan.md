# KNOT 判断影响与 Autoresearch 闭环计划（公开版）

日期：2026-07-21

状态：已完成（2026-07-21）

## 1. 目的、范围与继承关系

本计划单独解决三个问题，避免继续扩大 `macro-agent-role-contracts-v2-plan.md`：

1. 证明私有 KNOT 通过受控、可评分路径影响 Agent 的经济判断或 accepted reliability；
2. 闭合 candidate、同根 pair、outcome maturity、评价、既有 release gate、生效和回滚；
3. 区分“hook 被调用”“判断受影响”“候选可演化”“生产版本已生效”四种能力。

大型计划及其生成合同继续唯一负责 28 个逻辑 Agent/29 个阶段、职责、数据、工具、output、PIT、
evaluation object、label、maturity、normalized score、统计门、Darwinian、隐私和 RKE 隔离。本文件
只补充作用路径、候选授权、生产编排和黑盒验收；未明确变更的合同全部保持原状。

在该窄范围内，本计划明确替换旧的 prompt-only candidate 限制；角色、工具、公开 schema 和数据
合同变化仍必须走正常合同迁移，不能伪装成 KNOT mutation。

私有规范位于 `MOSAIC-Prompts` 同名文件，公开仓固定其 opaque 审计 hash：

`sha256:bf1a2e5b36d19e359a4c15da70161c626101f89ef4d97c785f0bf825851b2bb7`

该 hash 只用于跨仓一致性审计。生产 source of truth 仍是 commit-pinned、内容寻址的 private
runtime/assets release；缺失或漂移时失败关闭。

## 2. 不变量与 V1 声明边界

- 保持 28 个逻辑 Agent、29 个执行阶段、24 条上游 usage-weight 轨和 4 条 Decision
  `EVOLUTION_ONLY` 轨；
- Darwinian updater 仍是 usage weight 唯一 owner；KNOT 不写权重、组件权重、label 或硬风险约束；
- prompt registry/promotion gate 仍是 behavior version 唯一 owner；KNOT coordinator 不激活版本；
- 私有 prompt 不出现 research-knob、阈值、lookback、评分、候选身份或晋级规则；
- CIO 总收益和下游 propagation 不反向评价上游 Agent；
- RKE 保持 shadow-only；不运行 100 日 daily-cycle。

V1 rollout 冻结为：

- 28 个逻辑 Agent 的 private prompt-behavior 路径都必须具有真实 consumer、Agent 专属 fitness
  binding 和 formal pair capability；
- derived economic feature 和 confidence-policy 只激活 `china`、`central_bank` pilot；
- 其余数值 domain target 继续 `READ_ONLY`，不得进入 proposer/pair/promotion/runtime apply。

因此 V1 只能声明“全部 28 个 Agent 的 prompt behavior 可 formal 演化，两个具名 Macro pilot 的
derived/reliability 路径可 formal 演化”，不能声明所有数值 KNOT 已激活。扩大范围必须发布新的
effect/consumer/fitness registry revision。

## 3. 公开边界、作用与评分合同

公库只提供不可反推出私有实现的稳定接口：

- opaque effect/consumer/fitness binding 和 rollout disposition；
- frozen source、pair-side capability、candidate receipt、lineage 和 effective-input hash；
- accepted output、Agent 专属 evaluation object/outcome、PIT maturity 和 normalized score；
- full runtime release ref、activation/rollback receipt 和 private artifact 版本/hash 校验。

每个 active effect 必须解析到唯一真实非测试 consumer，并具备确定性 fitness-sensitivity fixture：
在固定 realized observation 下，至少一组合同允许的 accepted field delta 必须改变登记 raw metric 和
Agent 自身 loss/normalized score。只改变 UI、日志或 score 未读取字段的 target 不得 active；Decision
直接使用自身 outcome，不得借用 CIO PnL 或伪造 usage weight。

### 3.1 模型可见经济 envelope 与隐私边界

公开 adapter 增加受限 pre-model context 方法。调用位置固定为：capability-bound required initial
tool result 已完成并冻结之后、第一次 LLM generation 之前。它只接收 runtime 生成的 source
receipt/snapshot/payload，不接收 caller summary；返回公开 allowlist/schema 验证的有限经济 observation
envelope 及 opaque audit hash。

同一 envelope 只计算一次，以相同 hash 进入自由分析、structured extractor、runtime evidence、
PIT/semantic validation 和 effective-model-input hash；不得只在 extractor 前补入，也不得在输出后
重写 direction、strength、selection 或 action。snapshot 的 model-context 与 post-validation policy
capability 分开单次消费；重复、乱序、跨 invocation 或异常后复用均拒绝。

隐私规则明确区分：

- 禁止模型、公开 DTO/TUI/log/CI artifact 出现 private target path、knob 参数值、阈值、lookback、
  projection rule、candidate/champion 身份或评分目标；
- 允许模型看到通过公开 schema/ID allowlist 的经济观测值/状态；它们是 Agent evidence，不是 knob 值；
- public feature ID 不得嵌入或还原 private target，经济值不得直接复制 private knob/阈值/lookback；
- TUI 只从 accepted output 确定性生成人可读说明，不读取 hidden application audit。

active-unconsumed、重复 consumer、test-only caller、score-insensitive、越权字段、release 漂移或
read-only target 被使用时，generation、preflight、research 和 production invocation 全部失败关闭。

## 4. Candidate、盲化与真实 pair

candidate 必须物化为内容寻址、base-release-bound 的私有 research bundle。只有 formal scheduler 可为
某个 scheduled pair/side 签发一次性 capability；production/canary loader、普通 CLI 和 caller-
supplied output 均不能读取或运行 research bundle。promotion 后必须重新构建正常 production bundle，
不能把 research capability 直接升级。

proposer 只能读取 cutoff 之前目标 Agent 自身成熟 outcome 和 operational diagnosis。live evaluation
使用 candidate commit 之后的未来 slots；historical replay 使用独立 evaluator 预先提交、带私有 nonce
的 blind commitment，candidate commit 后才揭示。proposal/development/holdout sample 不得重叠；看到
evaluation 结果后重写 candidate 或替换样本使 track 失败。

固定 30-slot synthetic replay 只在 `TEST_CONTRACT_REPLAY` namespace 验证状态机，始终
`production_eligible=false`，不得成为 formal promotion、canary 或 activation 证据。

正式 pair 必须走 production 相同的 prompt loader、Agent node、tool bundle、structured extractor、
strict validator、accepted writer 和 operational audit。双方共享 byte-identical raw root、PIT、tool
payload、机会集、provider/model/language/decoding、schema/parser 和 realized observation，独立生成
output、evaluation object、label、utility 和 score。caller 不得直接注入 output、label 或 score。

`APPLIED/NOT_TRIGGERED/REJECTED` 三态必须可审计；未触发样本仍作为零差 pair，不能只选择有利日期。
所有 side difference 必须由唯一 candidate receipt 解释，且公开审计不含 raw knob 或隐藏推理。

## 5. Coordinator 与唯一 release authority

私库提供可恢复 `tick/resume/status` coordinator，串接 nomination、proposal cutoff、candidate、blind
schedule、real pair、maturity、label/score、统计门、release preparation 和 post-promotion shadow。
状态 append-only，command 使用 idempotency key 和 compare-and-swap revision；restart/replay/concurrency
不得重复 pair、label、promotion 或 release。

coordinator 复用现有 bridge/KNOT ledger，并可自动推进到等待批准；它不能生成 label/score、写
Darwinian weight、伪造 SLO/operator approval 或调用 activation CAS。公开 legacy
`runAutoresearchCycle` 保持非生产诊断用途并固定 `production_eligible=false`。

### 5.1 Full runtime bundle

不新增平行 `PREPARED -> COMMITTED` 状态机。现有 `ActivePromptReleaseManifest` v2 的 immutable
closure 必须包含一个 full runtime bundle ref，同时绑定 prompt、execution release、完整 future
roster revision、promotion/migration origin、opaque private runtime/policy、effect/consumer/fitness
registry 和全部合同 hash。release identity 覆盖 full bundle，因此 prompt 不变、execution/private
policy 改变时也必须形成新 release。

v2 release evidence 按作用类型区分：prompt 变更必须证明 prompt-only diff；非 prompt pilot 必须证明
prompt 不变且只有登记 execution/private-policy diff。原有候选校验改为严格 union，不能整体移除。

现有 `staged -> canary -> active|rolled_back`、operator approval、canary SLO journal 和 CAS active
pointer 是唯一 release/activation authority。canary future roster 只能由同一 canary assignment 使用；
CAS 后才成为 production roster。

daily-cycle 只调用一次现有 runtime resolver，并从同一个 active/canary v2 manifest 解析所有 pins。
静态 execution manifest 只作 builder/archive input，不再是第二个 selector。任一 sub-pin/hash 不闭合
时本次运行失败；不存在 prompt、execution、roster 或 private policy 单边切换的合法状态。

earliest activation slot 只是 operator CAS 的下界。CAS 前继续使用当前完整 active bundle且不得声明
`PRODUCTION_EVOLVED`；CAS receipt 必须绑定 expected base、new full bundle、operator、SLO 和 slot，
下一 production run 再以 accepted-output pins 证明生效。v2 cutover 先用当前 pins 发布 baseline full
bundle并走完整 lifecycle；cutover 后拒绝 v1/mixed resolver 和静态 override。

### 5.2 Rollback

rollback 分两步且均必需：

1. authorized operator 使用现有 rollback CAS 恢复 previous active full bundle并生成紧急 receipt；
2. coordinator 用旧 champion 内容发布新的 forward recovery full bundle、execution release 和 roster
   revision，重新走 staged/canary/active；下一 run pins 通过后才标记 `ROLLBACK_VERIFIED`。

不得原地改 manifest、删除失败 track、直接替换静态文件、依赖人工重启或省略 forward recovery。

## 6. 实施与验收矩阵

| WP | 公开 touch points | 交付门 |
| --- | --- | --- |
| Release closure | prompt release contract/manager/registry/loader、execution archive、daily-cycle | v2 full bundle 通过既有 canary/CAS 唯一解析，mixed pins 全拒绝 |
| Effect ABI | private boundary、common agent loop/evidence、四层 factory、strict validator | 28 prompt-behavior + 两个 Macro pilot 均有 consumer、fitness fixture、顺序/隐私拒绝 |
| Formal research | KNOT scorecard wrapper、Darwinian bridge handler/types | candidate capability、blind holdout、同根 real pair 和 score lineage 闭合 |
| Coordinator | opaque private-runtime loader、autoresearch CLI status surface | 每个状态 restart/replay/concurrency 幂等，审批边界不可旁路 |
| Rollout | accepted-output pins、prompt leak/private-boundary tests | paper-mode activation、紧急 rollback、forward recovery 均有下一 run pins |

黑盒 capability 按 `(production variant, Agent, effect)` 单独记录：

| 状态 | 必须证明 |
| --- | --- |
| `EFFECT_PATH_VERIFIED` | 真实 consumer、fitness sensitivity、real-path counterfactual audit |
| `RESEARCH_EVOLVABLE` | blinded proposer、candidate capability、real pair、maturity/score、可恢复 coordinator |
| `PRODUCTION_EVOLVED` | Agent 自身 gate、既有 canary/SLO/operator/CAS receipt、下一 production pins |
| `ROLLBACK_VERIFIED` | emergency CAS、forward recovery release、下一 production pins |

pilot、另一 cohort/language、下游结果或 synthetic replay 均不能替代目标记录。“输出不同”也不能替代
Agent-specific outcome 正确性。

## 7. 验证与完成定义

交付前运行：

- public TypeScript typecheck/lint/test 和 private TypeScript build/typecheck/test；
- public bridge/scorecard 与 private KNOT/outcome Python focused pytest；
- 28-Agent effect/fitness 参数化 fixture、30-slot test-namespace contract replay；
- 29-stage fake smoke 和一次固定本地模型结构化单日 smoke；
- prompt leak/private boundary、RKE shadow-only、CIO 反归因污染和 `git diff --check`。

不运行 100 日测试，不提交 private prompt/runtime/projection、knob、Tushare 原文或本地缓存。私有计划
固定精确模块和命令；公开计划不复制私有实现。

最终完成必须同时满足：

1. V1 28-Agent/pilot rollout 与 read-only 边界全部闭合；
2. 每个 active effect 都有唯一 consumer、fitness binding、candidate authorization 和真实 pair 路径；
3. proposer/holdout 隔离，synthetic fixture 永不进入 production evidence；
4. coordinator 可恢复到 operator gate，但不能越过现有 release authority；
5. full bundle 经唯一 active pointer 生效且下一 run pins 可证明；
6. emergency rollback、forward recovery 和下一 run pins 全部通过；
7. capability 不跨 Agent/effect/variant 冒用或升级声明；
8. 公私边界和 prompt/TUI/log/CI artifact 无 private target、参数值、规则或候选目标泄漏。

## 8. 实施结果

- prompt release 已升级为内容寻址的 v2 full-runtime bundle；每次 daily-cycle 只从
  既有 active/canary CAS authority 解析一个 bundle，execution archive、roster、prompt、
  evaluation 和 opaque private pins 任一漂移都失败关闭。
- KNOT 派生上下文已在 tool result 冻结后、首次 model generation 前由 common loop 单次
  构造，同一 hash 进入四层 factory、structured extraction、runtime evidence、语义验证和
  accepted-output pins；未安装私有 runtime 时保持明确的公开基线路径。
- candidate-only 授权、同根 pair、blind holdout、maturity/score lineage、可恢复 coordinator、
  activation receipt、emergency rollback 和 forward recovery 均通过黑盒合同测试；
  Darwinian、outcome 和 release authority 未被取代。
- 公开 TypeScript typecheck/Biome 通过，87 个测试文件共 881 项通过；Python Ruff、
  全量 `tests/`、prompt-leak guard 和 `git diff --check` 通过。
- 29-stage fake smoke 和固定本地模型结构化单日 smoke 都产生 10/10/4 层输出与
  27 个 accepted refs，并明确标记 `production_eligible=false`。未运行 100 日测试，
  RKE 保持 shadow-only。
