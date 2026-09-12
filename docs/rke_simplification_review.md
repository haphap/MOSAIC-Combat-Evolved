# MOSAIC CE / RKE 简化实施与验收

日期：2026-09-12。代码基线：main `17a44489`；先前简化实现截至 `fd09e91d`；本次追加研究案例消费与迁移。
交付：[PR #31](https://github.com/haphap/MOSAIC-Combat-Evolved/pull/31)，依赖 #30，集成 #27/#28 的既有清理；没有合并任何 PR。
当前研究案例改动与验证见下文；远端 CI 以 PR 当前提交的检查结果为准。

## 实施结果

| 批次 | 最终行为 | 验证依据 |
|---|---|---|
| P0 / F1 | 核实实际 L4 工具矩阵；准备和调用复用唯一授权 context 的查找；缺失、重复、跨角色、篡改分别拒绝 | 四角色五阶段的冻结/延迟路径及准备阶段反例 |
| F2 | L3 明确预留现有三次模型工具预算中的一个名额给 RKE；Sector 保持原预算策略；记录请求、派发、结果和缓存 | TS 全套 1023 项；同批/跨轮、预算释放、失败、缺失工具、缓存和日志统计 |
| P5 | 研究上下文 v4 / 排序 v3，读取 footprint、forecast 与 metadata；优先完整案例和当前股票，并保留来源多样性 | 可选研究文件缺失不阻断；来源、PIT、隐私失效仍拒绝 |
| H1 | 去掉展示/版本派生/无消费者摘要，单次可信构建复用同一输入；新回执和快照合同同步迁移 | 读取次数、内容与时间篡改、签名、角色和 scope 反例 |
| P1 | 用 jsonschema 替换手写递归校验；禁止外部 ref，错误不泄露原始值 | 隔离 CI 依赖环境 25 项通用回归；完整 Schema 文件 118 通过 /118 跳过 |
| P2 | 普通 operator-readiness 的 builder/no-write 只读，不复制 registry 或生成临时模板 | 禁止写文件、mkdir、copytree，并比较全部内容与 mtime；真实导入和隔离模拟保留 |
| P3 | 置信度公式、等价监控算法和操作命令合同归属统一；配置与命令按结构验证；删除不可达私有报告校验 | 舍入、标题/空白、非法命令、陈旧及篡改反例；最后 131 项上层消费者通过 |
| P4 | tool gap 作为唯一审核事实源；两种提案只按需展示；显式迁移并归档历史私有输入 | 联动 528 通过 /118 跳过；状态约束修正后 422 通过 /118 跳过 |
| P6 | 默认 basic 只提取事实；显式 full 才运行离线研究扩展；未计算计数为 null，outputs 只列实际写入 | 基础刷新不调用研究 builder、不覆写旧汇总；重复提取不再调用 LLM |

## Hash 与重复校验的处理

| 对象 | 处理 | 保留的真实边界 |
|---|---|---|
| Agent 文本中的 context_hash | 删除，并迁移 TS 文本消费者 | 服务端实际输出 content hash |
| RKE 的 hash(parser_version, route_id) | 改为明确合同版本 | 真正的 Schema 内容摘要和其他工具回执不受影响 |
| 空结果的十份输入摘要 | 保留三份实际输入，同次构建/渲染/密封读取同一份字节 | 缺失输入不能伪装为正常空结果 |
| source/staged 构建中的重复序列化与验证 | 复用同一可信构建结果 | 持久化读取、签名和跨进程边界仍验证 |
| 五类 runtime snapshot 的 role_context_hash | 在 v2 中退役 | 整包 snapshot_hash 仍绑定角色上下文 |
| 提案 ID 摘要 | 提案持久化退役，展示直接引用 gap ID | 缺口与来源身份保留 |
| fingerprint writer 的返回 sha256 | 删除无人使用的返回字段及写后整文件读取 | 导出清单仍对实际文件计算摘要 |
| author_ids_hash 及其临时作者 ID | 无仓库读取者，删除字段与两个仅供它使用的函数 | 来源事实仍保留作者；去重继续用来源、PDF、机构/时间/标题 |
| archive_hash / parent_capture_hash | 保留，有来源及资格检查消费者 | 非空结果仍证明私有来源链；不能仅以输出文字相同替代来源身份 |
| scope / universe / constraint hash，HMAC | 保留，实际限定权限、候选范围和签名 | 不以降低拒绝数量替代正确授权 |

检索的三份事实文件不包括非空结果所需的独立私有来源证明；输入字节在同次调用中复用。
没有添加通用 hash 服务、全局 mtime 缓存、兼容旁路或新的门禁框架。
旧 fingerprint 文件按原清单校验字节，下一次显式重建才省略作者摘要；不修改历史 hash。

## 保留的治理报告为何不同

| 规则/报告 | 唯一职责及实际消费者 |
|---|---|
| completion auditor | C01–C12 的完成证据；由 promotion gate、master-plan coverage、dashboard 消费 |
| promotion gate | 实际提升边界：金标、许可、来源、paper trading、lockbox、回滚及 patch 证据；不能用“文件齐全”替代 |
| master-plan coverage | 将公开完成证据映射到 MVP 交付、退出和最终验收；workflow 生成，CLI/dashboard 展示 |
| Report Intelligence patch coverage | 显式 full 下的 A–H 阶段与 rollout 延后状态，消费研究审计结果；不进入基础查询 |
| operator readiness | 当前可执行操作、导入模板与必要材料的状态；读状态与执行导入分开 |
| Schema/来源/签名检查 | 验证外部或持久化输入；复用规则不等于信任旧 accepted 标志 |

master-plan coverage 先过滤私有路径，其后针对私有 RI patch 的专用校验不可达。
已删除该分支、无消费者包装函数以及只能服务该分支的布尔参数/字符串分类，共净减 81 行。
公共 JSON 损坏仍为 missing，真正的 completion/promotion 阻断仍为 blocked。
未把职责不同的报告按文件名相似强行合并，也未把所有独立证据检查删除。

真实 registry 升级还暴露了 RI15-A-D1 对“至少 15 个 Schema”的硬编码检查：
删除两份提案 Schema 后，这个对静态列表数量的自证会误报缺失。
已删除该检查与语义验证中的强制 ID；真实 Schema 校验继续保留，
既有完整刷新回归先复现误报，再验证退役提案不会制造新的阻断。

## 提案和刷新迁移

`tool_gaps.jsonl` 保存 `data_decision_status`、`shadow_implementation_status`、实际请求工具和独有人工字段。
默认输入/输出/PIT/许可/验证模板不再长期复制为两份事实。
`data_acquisition_proposals.jsonl`、`tool_design_proposals.jsonl` 的 writer、计数、Schema 和 active export 契约退役。
旧路径继续保持私有；归档不进入当前快照。冲突、未知孤儿、重复和坏 JSON 均拒绝且不写入。

最终复查补齐了原提案中许可、PIT、实现状态和工程工作量的值约束：
一个纯函数由迁移、可行性和外部语义验证共用；无须生成模板，也不增加摘要。
5 个反例在遗漏的实现上失败，修正后通过；非法审核值的迁移保持零写入。

四种受影响的研究汇总使用 `tool_gap_contract: tool_gap_facts_v1`；版本缺失的旧报告必须重建，不能补一个版本字段冒充验收。
默认 basic 不生成这些研究汇总，不把旧报告标为本次结果。
真实迁移、full 刷新和回退限制见[操作 runbook](runbooks/rke_report_intelligence_operations.md#tool-gap-review-migration)。
首次代码交付只修改代码与合成测试。后续经用户授权已迁移真实私有 registry；
升级保留原始审核归档，只重算派生产物，没有运行 MinerU/LLM 或开启生产交易。
真实语料的人工审核和覆盖门禁仍独立生效，不以迁移成功替代研究质量验收。

## 改动量与限制

以下是 Git 行数差，按路径统计；不是性能或交易收益指标。包含 #27/#28 的既有清理。

| 范围 | main 17a44489 → fd09e91d | #30 157557bb → fd09e91d |
|---|---:|---:|
| 业务源码 mosaic/ + mosaic-ts/src/ | +1837 /−5590，净减 3753 | +1833 /−5322，净减 3489 |
| 测试 | +1923 /−2164，净减 241 | +1543 /−1471，净增 72 |
| Schema | +34 /−56，净减 22 | +34 /−56，净减 22 |

其他可直接观察的变化：formatter 预检函数 358→116 行；手写通用校验器及辅助函数移除；
默认查询/空结果基础输入先从 10→2，本次为消费完整案例增加 footprints，现为 3 份；两个提案持久化契约与两个 Schema 删除；
普通 no-write 状态检查的目录复制和文件写入均为零。
依赖并非净减少：CI 证明 jsonschema 缺少 RFC3339 可选依赖会静默跳过时间格式检查，
因此明确加入 `rfc3339-validator`，未安装整套无关格式 extras，也没有重写日期校验算法。

55 份历史日志中，10 份重试日志出现 18 条授权异常，另有两条 RKE 预算拒绝。
缺少同次失败的 L4 snapshot/capability，不能分辨历史异常究竟来自缺失还是重复 context。
当前修复可区分这两类原因，并验证正式调用路径；这不等于证明历史 18 次故障已全部复现并修复。

新的调用统计区分 available、normal_empty、blocked、authorization_rejected、request_rejected、
execution_failed、budget_not_executed、missing_tool、returned_unclassified。零派发时比率为 null。
未知旧日志不倒推成成功；派发不等于授权通过，更不等于 Agent 实际采用研报内容。
本次未测量新的真实 Agent RKE 成功率或收益，保留的收益验证协议不被单元测试替代。

## 先前简化检查

最终代码 `fd09e91d` 的完整 Python：3323 通过、122 跳过、0 失败/错误，1236.343 秒；
其中 Report Intelligence 293 项全部通过。JUnit 为本地 `.mosaic/tmp/registry-upgrade-full.xml`。
TS：90 个文件、1023 项全部通过；typecheck、lint、Ruff 0.15.15、prompt leak 和 diff 检查通过。
公开 registry 无改动；私有路径保持 gitignored；历史检查仅匹配研报测试文件，未发现私有报告 blob。
原工作区用户修改保持原样。跳过项不计作真实私有语料验证。

先前 bff72961 的全量运行因补齐状态约束而主动中断，不计作通过。
远端 CI 在本地验收后触发，其最终状态请查看 PR 当前提交；不沿用旧提交的检查结果。

Schema 数量门槛回归先在原实现上失败，修复后通过，并包含在本次完整 Python 验收中。


## 研究案例与 regime

复用 `analytical_footprints.research_case`，在同一单元保存研究问题、历史 regime、
有序推理、关键证据、前提、失效条件与结论。缺失字段保持未知。指标留在其支持的论证中，
不再把 `analysis_patterns` 字符串提升为方法，也不把推理句子自动变成交易配方。
方法身份按问题、逻辑与适用条件区分，同名但条件不同的方法不合并。

Agent 使用现有查询及授权路径，优先返回完整案例；更换股票代码可以借鉴符合角色的其他案例，
输出保留历史对象并要求验证当前适用性。同源重复案例去重，优先保留不同来源的论证。
报告原文所述 regime 与按历史日期附加的背景分别呈现；当前 regime 必须由 Agent 用当前数据判断。
价格结果不能证明盈利预测或因果机制正确。

案例摘要属于获准内部研究使用的来源派生文本，`private_text_included` 据实标记，
不再将其称为公开安全元数据。许可、来源、PIT 与服务端输入绑定保留；
原始段落字段、来源 span、私有路径和审核文本仍不进入 Agent 输出。
公开提交只包含代码、Schema、合成测试和操作说明。

迁移通过 `--migrate-research-cases --dry-run` 预览，仅恢复既有单一结构化主线中的明确步骤。
原文件自动归档，旧方法保留 ID 并标为历史上下文；人工审核导入不重写。
案例变化会使旧审核目标失效，新的审核模板包含案例全文，不能沿用旧审核冒充已复核。
不能恢复的主线、regime 和结论需重新读取原文提取；迁移不会推断这些内容。
现有离线价格/覆盖门禁继续独立生效，其通过也不等于新案例的语义质量已获证明。
