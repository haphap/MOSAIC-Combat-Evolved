# MOSAIC CE / RKE 简化实施与验收

日期：2026-09-12。代码基线：main `17a44489`；实现截至 `878532bc`。
交付：[PR #31](https://github.com/haphap/MOSAIC-Combat-Evolved/pull/31)，依赖 #30，集成 #27/#28 的既有清理；没有合并任何 PR。
当前状态：计划内代码实施与本地最终验收完成；远端 CI 以 PR 当前提交的检查结果为准。

## 实施结果

| 批次 | 最终行为 | 验证依据 |
|---|---|---|
| P0 / F1 | 核实实际 L4 工具矩阵；准备和调用复用唯一授权 context 的查找；缺失、重复、跨角色、篡改分别拒绝 | 四角色五阶段的冻结/延迟路径及准备阶段反例 |
| F2 | L3 明确预留现有三次模型工具预算中的一个名额给 RKE；Sector 保持原预算策略；记录请求、派发、结果和缓存 | TS 全套 1023 项；同批/跨轮、预算释放、失败、缺失工具、缓存和日志统计 |
| P5 | 基础上下文 v3 / 排序 v2，仅依赖 forecast 与 metadata；按匹配范围、可得时间和稳定 ID 排序 | 可选研究文件缺失不阻断；来源、PIT、隐私失效仍拒绝 |
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
| 空结果的十份输入摘要 | 基础输入缩至两份，同次构建/渲染/密封读取同一份字节 | 缺失输入不能伪装为正常空结果 |
| source/staged 构建中的重复序列化与验证 | 复用同一可信构建结果 | 持久化读取、签名和跨进程边界仍验证 |
| 五类 runtime snapshot 的 role_context_hash | 在 v2 中退役 | 整包 snapshot_hash 仍绑定角色上下文 |
| 提案 ID 摘要 | 提案持久化退役，展示直接引用 gap ID | 缺口与来源身份保留 |
| fingerprint writer 的返回 sha256 | 删除无人使用的返回字段及写后整文件读取 | 导出清单仍对实际文件计算摘要 |
| author_ids_hash 及其临时作者 ID | 无仓库读取者，删除字段与两个仅供它使用的函数 | 来源事实仍保留作者；去重继续用来源、PDF、机构/时间/标题 |
| archive_hash / parent_capture_hash | 保留，有来源及资格检查消费者 | 非空结果仍证明私有来源链；不能仅以输出文字相同替代来源身份 |
| scope / universe / constraint hash，HMAC | 保留，实际限定权限、候选范围和签名 | 不以降低拒绝数量替代正确授权 |

基础检索的两份文件不包括非空结果所需的独立私有来源证明；没有宣称整个授权调用只有两次文件读取。
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
本次只修改代码与合成测试，没有迁移、发布真实私有数据，没有运行 MinerU/LLM 或开启生产交易。

## 改动量与限制

以下是 Git 行数差，按路径统计；不是性能或交易收益指标。包含 #27/#28 的既有清理。

| 范围 | main 17a44489 → 878532bc | #30 157557bb → 878532bc |
|---|---:|---:|
| 业务源码 mosaic/ + mosaic-ts/src/ | +1837 /−5566，净减 3729 | +1833 /−5298，净减 3465 |
| 测试 | +1919 /−2164，净减 245 | +1539 /−1471，净增 68 |
| Schema | +34 /−56，净减 22 | +34 /−56，净减 22 |

其他可直接观察的变化：formatter 预检函数 358→116 行；手写通用校验器及辅助函数移除；
默认查询/空结果基础输入 10→2；两个提案持久化契约与两个 Schema 删除；
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

## 最终检查

最终代码 `878532bc` 的完整 Python：3323 通过、122 跳过、0 失败/错误，1263.172 秒；
其中 Report Intelligence 293 项全部通过。JUnit 为本地 `.mosaic/tmp/rke-plan-final-v2.xml`。
TS：90 个文件、1023 项全部通过；typecheck、lint、Ruff 0.15.15、prompt leak 和 diff 检查通过。
公开 registry 无改动；私有路径保持 gitignored；历史检查仅匹配研报测试文件，未发现私有报告 blob。
原工作区用户修改保持原样。跳过项不计作真实私有语料验证。

先前 bff72961 的全量运行因补齐状态约束而主动中断，不计作通过。
远端 CI 在本地验收后触发，其最终状态请查看 PR 当前提交；不沿用旧提交的检查结果。
