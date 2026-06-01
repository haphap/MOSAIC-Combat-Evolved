# Prompt Asset Protection Plan

日期：2026-06-01

## 目标

Agent prompt 是本项目最重要的私有资产。模型跑起来以后，autoresearch / PRISM / 人工调优产生的优化 prompt 不得暴露到公开项目 repo、公开 git remote、PR diff、CI artifact、日志、测试快照或 issue 文本中。

本计划采用**双 repo** 架构：

- 项目 repo：保存代码、协议、公开 baseline prompt、测试、文档和 metadata。
- 私有 prompt repo：保存优化 prompt 正文，并承载 autoresearch 的 branch / commit / diff / review / rollback。

autoresearch 仍然以 git 为核心；改变的是 git 操作边界：从项目 repo 移到 private prompt repo。

## 当前状态

当前 prompt 读取和优化路径：

- Prompt baseline 存在 `prompts/mosaic/<cohort>/<layer>/<agent>.<lang>.md`。
- TypeScript loader 默认从项目 repo 内 `prompts/mosaic` 读取。
  - `mosaic-ts/src/agents/prompts/cohorts.ts`
  - `mosaic-ts/src/agents/prompts/loader.ts`
- Python bridge 的 `prompts.write` 会把 mutation 写到项目 repo 路径，并可通过 git branch commit。
  - `mosaic/bridge/handlers/prompts.py`
  - `mosaic/autoresearch/git_ops.py`
- Autoresearch orchestrator 会调用 `prompts.write`，把 LLM 生成的 `zh_prompt` / `en_prompt` 写入分支。
  - `mosaic-ts/src/autoresearch/orchestrator.ts`
- 当前配置里 autoresearch git push 默认关闭，但 keep/merge 或人工 push 仍可能把优化 prompt 送到公开 remote。
  - `mosaic/default_config.py`
- DB 现状（已是 metadata-only）：`prompt_versions` 表**不存 prompt 正文**，只存 `branch_name` /
  `base_commit_hash` / `modification_commit_hash`（当前语义下指向项目 repo 分支提交）/
  `modification_summary` / pre/post/delta Sharpe。
  - `mosaic/scorecard/store.py`

核心风险：优化 prompt 正文的真实落点是 **项目 repo 的 git commit**。`modification_commit_hash` 指向的分支提交里就是 markdown 全文。DB 本身不是正文泄漏点，但它会把审计链指回含正文的公开分支。

## 原则

1. **Baseline 可公开，optimized 私有**：项目 repo 内 prompt 只作为可运行种子和 fallback；优化后的 prompt 不进入项目 repo。
2. **Git 仍是 autoresearch 的核心**：优化 prompt 必须有 branch、commit、diff、review、rollback，只是这些发生在 private prompt repo。
3. **运行时 overlay**：模型实际运行优先读取 private prompt repo，找不到才回退项目 repo baseline。
4. **写入默认私有**：autoresearch 默认写 private prompt repo，不写项目 repo 的 `prompts/mosaic/**`。
5. **项目 repo 只存引用和指标**：项目侧可以记录 prompt repo id、prompt commit hash、sha256、指标、脱敏摘要，但不存 prompt 正文。
6. **fail closed**：如果 autoresearch 配置为私有模式但 private prompt repo 不可用，直接失败，不回退写项目 repo。
7. **显式逃生门**：只有 per-invocation 授权才允许把 prompt 正文写进项目 repo，用于公开 baseline 更新；不得依赖长期 export 的 escape hatch。

## 目标架构

### Repo 边界

```text
MOSAIC-Agents/                         # 项目 repo
  mosaic/
  mosaic-ts/
  prompts/mosaic/...                   # 公开 baseline / seed prompt
  docs/

private-mosaic-prompts/                # 私有 prompt repo
  prompts/mosaic/cohort_default/...
  prompts/mosaic/<cohort>/...
```

项目 repo 保留：

- 公开 baseline prompt。
- prompt schema / loader / tests。
- autoresearch 协议和 scorecard 代码。
- prompt version metadata。

项目 repo 禁止：

- autoresearch 产生的优化 prompt 正文。
- private prompt repo 的完整 diff。
- 私有 prompt 的本地 checkout、submodule 或 vendored copy。

private prompt repo 保留：

- 优化后的 prompt markdown。
- autoresearch 自动分支。
- 人工 review / merge 的 prompt diff。
- prompt rollback 所需的 commit history。

### Autoresearch Branch

autoresearch 分支只在 private prompt repo 中创建：

```text
cohort/<cohort>/auto/<agent>/<YYYY-MM-DD>
```

分支 commit 内容：

```text
prompts/mosaic/<cohort>/<layer>/<agent>.zh.md
prompts/mosaic/<cohort>/<layer>/<agent>.en.md
```

commit message：

```text
autoresearch: <redacted modification summary>
```

项目 repo 不创建这类 prompt 正文分支。

### 配置

建议配置项：

```toml
[prompts]
baseline_root = "prompts/mosaic"
private_repo_root = "/secure/private-mosaic-prompts"
private_repo_id = "private"
write_target = "private_git"
```

环境变量覆盖：

```bash
MOSAIC_PRIVATE_PROMPT_REPO=/secure/private-mosaic-prompts
MOSAIC_PROMPT_WRITE_TARGET=private_git
```

启动时必须校验：

- `MOSAIC_PRIVATE_PROMPT_REPO` 存在。
- 它是 git repo。
- 它不在项目 repo 目录内。
- 它不是项目 repo 的 submodule。
- autoresearch 写入目标不是项目 repo。
- 如果校验失败，autoresearch mutation fail closed。

### 读取顺序

对任意 `(cohort, layer, agent, lang)`：

1. `$MOSAIC_PRIVATE_PROMPT_REPO/prompts/mosaic/<cohort>/<layer>/<agent>.<lang>.md`
2. `$MOSAIC_PRIVATE_PROMPT_REPO/prompts/mosaic/cohort_default/<layer>/<agent>.<lang>.md`
3. `<project_repo>/prompts/mosaic/<cohort>/<layer>/<agent>.<lang>.md`
4. `<project_repo>/prompts/mosaic/cohort_default/<layer>/<agent>.<lang>.md`

这样生产运行可以使用私有优化 prompt，同时保留公开 baseline fallback。

注意：private-first 会带来 baseline shadowing 风险。某个 agent 一旦存在 private override，后续项目 repo 中该 agent 的公开 baseline 修复（例如新增工具 wiring、修正 schema、修复 role contract）不会自动进入生产 prompt。因此必须同时建设 baseline drift 检测和传播机制，不能只做简单覆盖读取。

## 版本与审计

双 repo 后，任一 evaluation / scorecard / production run 必须能 pin 到一组明确版本：

- `code_repo_id`
- `code_commit_hash`
- `prompt_repo_id`
- `prompt_branch`
- `prompt_base_commit_hash`
- `prompt_commit_hash`
- `prompt_sha256`
- `baseline_prompt_sha256`
- `baseline_code_commit_hash`
- `cohort`
- `agent`
- `language`
- `created_at`
- `source`: `autoresearch | manual | import`
- `summary_redacted`
- `metrics_json`

项目 DB / git 允许保存：

- prompt repo id。
- prompt branch。
- private prompt repo commit hash。
- prompt sha256。
- mutation summary 的脱敏版本。
- evaluation metrics。
- code commit hash。

项目 DB / git 禁止保存：

- `zh_prompt`
- `en_prompt`
- 完整 prompt diff。
- 完整 LLM mutation response。
- private prompt repo 的绝对路径。

`baseline_code_commit_hash` 表示 private prompt 上次同步或生成时参考的项目 repo baseline code commit；`code_commit_hash` 表示当前 evaluation / production run 实际运行的项目 repo code commit。Drift gate 比较这两个值以及对应 baseline prompt hash，判断 private prompt 是否落后于当前代码期望。

缓存 key 必须从旧的单一项目 repo `prompt_commit_hash` 升级为：

```text
prompt_repo_id + prompt_commit_hash + prompt_sha256 + code_commit_hash
```

否则不同 repo 的 commit hash、不同 prompt 内容或不同代码版本可能混淆。

运行时 loader 当前读取 filesystem path，而不是直接读取 git object。要让 `prompt_commit_hash` 真正可复现，evaluation / production 必须先把 private prompt repo checkout 到 pinned commit 的独立 worktree，再把 loader 的 private root 指向该 worktree：

```text
private prompt repo
  main
  cohort/.../auto/...

private prompt pinned worktree
  checkout: <prompt_commit_hash>
  root: <worktree>/prompts/mosaic
```

只记录 commit hash 但继续读取浮动 working tree，不能提供可复现性。

## Baseline Drift 管理

目标：防止 private override 长期遮蔽项目 repo baseline 的关键修复。

触发条件：

- 项目 repo 的 `prompts/mosaic/**` 被修改。
- 修改影响的 `(cohort, layer, agent, lang)` 在 private prompt repo 中存在 override。
- 代码变更新增或删除 agent 可用工具、role contract、schema、required section 或 output format。

处理策略：

1. Drift alert。
   - 本地 / operator-run / scheduled job 列出受影响 private override。
   - 输出 baseline commit、agent、语言、private prompt commit、差异摘要。
2. Propagation branch。
   - 在 private prompt repo 创建 `baseline-sync/<code_commit>/<agent>/<date>` 分支。
   - 把新的 baseline 作为上游输入，要求人工或 LLM 把工具/schema/contract 修复合入 private prompt。
3. Compatibility gate。
   - 未处理的 critical drift 阻止 production pin 或 autoresearch merge。
   - 低风险文本改动可以只告警，但必须记录 waiver。
4. Metadata。
   - private prompt commit 记录 `baseline_code_commit_hash` 和 `baseline_prompt_sha256`。
   - evaluator 可判断 private prompt 是否落后于当前代码期望的 baseline。

验收：

- baseline prompt PR 不会被 private override 静默吞掉。
- 修改某个 agent baseline 后，系统能列出所有遮蔽该 baseline 的 private prompt。
- production release 能发现 private prompt 与 code commit 不兼容或需要同步。

## 兼容性契约

双 repo 后，code 和 prompt 会独立演进。只 pin 两个 hash 能保证“可识别”，但不能保证“兼容”。需要最小兼容性契约：

默认采用 registry-scan，不引入 prompt front-matter 子项目：

- 扫描 prompt markdown 正文中的工具 token，例如 `get_*`。
- 从 live `tools.list` registry 读取当前代码支持的工具集合。
- 如果 private prompt 引用的工具不在 registry 中，必须 fail loudly。
- Autoresearch evaluation 在跑分前先执行 registry-scan validation，避免用错误组合产生看似有效的指标。
- registry-scan 只覆盖工具存在性，不覆盖 output schema / section drift、role contract 变化、同名工具签名变化，或未来非 `get_*` 命名工具；绿色结果不能被视为完整兼容证明。
- 声明式 prompt metadata（agent、layer、tools、schema version、contract version）作为未来增强，不是本阶段前置依赖。

涉及文件：

- `mosaic-ts/src/agents/prompts/loader.ts`
- `mosaic-ts/src/agents/prompts/cohorts.ts`
- `mosaic-ts/src/autoresearch/orchestrator.ts`
- `mosaic/bridge/handlers/autoresearch.py`
- `mosaic/scorecard/store.py`
- `mosaic-ts/test/prompt_compatibility.test.ts`（可新增）

## Phase 0：暴露面清点

目标：列出所有可能把优化 prompt 写出私有边界的位置。

任务：

1. 梳理 prompt 读取路径。
   - `mosaic-ts/src/agents/prompts/cohorts.ts`
   - `mosaic-ts/src/agents/prompts/loader.ts`
2. 梳理 prompt 写入路径。
   - `mosaic/bridge/handlers/prompts.py`
   - `mosaic/autoresearch/git_ops.py`
   - `mosaic-ts/src/autoresearch/orchestrator.ts`
3. 梳理日志和 DB 字段。
   - autoresearch mutation summary
   - prompt_versions table
   - scorecard/autoresearch logs
4. 梳理 git / push / PR 风险。
   - 项目 repo feature branch
   - autoresearch keep merge
   - optional push
   - CI artifacts
5. 审计**已泄漏**面。
   - 扫描本地 + 远端项目 repo 分支和 commit history 里已写入的优化 prompt 正文：
     `git log --all -p -- 'prompts/mosaic/**'`，并列出 `cohort/*/auto/*` 类自动分支。
   - 判定是否有自动分支已 merge 到 `main` 或 push 到公开 remote。
   - 给出处置：删除自动分支；若已进入公开 history/remote，评估 `git filter-repo` 改写 + force-push +
     失效已暴露版本；核对公开 remote 现存内容。

验收：

- 文档列出所有 prompt 正文可能出现的位置。
- 每个位置都有后续 phase 的处理策略。
- 明确列出当前已泄漏的优化 prompt（分支 / commit / remote），并给出 scrub 决定与执行项。

产出：

- `docs/prompt-leak-audit.md`，记录已泄漏清单 + 处置结论。

## Phase 1：Private Prompt Repo 初始化、配置与校验

目标：系统知道项目 repo 和 private prompt repo 是两个不同 git repo，能初始化 private prompt repo，并在写入前强校验边界。

任务：

1. 增加初始化命令。
   - `mosaic prompts init-private-repo <path>` 或等价 TS CLI。
   - `git init` private prompt repo。
   - 创建 `prompts/mosaic/` 目录。
   - 默认 sparse：不全量复制项目 repo baseline，只有 autoresearch 或人工优化过的 agent 才创建 private override。
   - 可选 `--seed-baseline` 只用于迁移或离线环境；必须告警说明全量 seed 会让所有 agent 进入 shadowing 状态，增加 drift 管理负担。
   - 可选设置 private remote，但必须显式传入，且文档要求 remote 为 private。
2. 增加配置解析。
   - `MOSAIC_PRIVATE_PROMPT_REPO`
   - `MOSAIC_PROMPT_WRITE_TARGET=private_git`
   - config 中的 `prompts.private_repo_root` / `prompts.private_repo_id`
3. 增加 repo 校验。
   - private prompt repo 必须存在。
   - 必须包含 `.git`。
   - 必须不在项目 repo 内。
   - 必须不是项目 repo 本身。
   - 必须不是项目 repo submodule。
4. 错误和日志脱敏。
   - 日志只显示 repo id 或 redacted path。
   - 不打印 private repo 绝对路径。
5. 测试。
   - init 命令能创建合法 private prompt repo。
   - 默认 init 不复制 baseline prompt。
   - 带 `--seed-baseline` 时才从项目 repo baseline seed `prompts/mosaic/`，并产生 shadowing 告警。
   - 缺失 private repo 时 autoresearch mutation fail closed。
   - private repo 指向项目 repo 时失败。
   - private repo 在项目 repo 子目录下时失败。
   - 合法 private repo 通过校验。

涉及文件：

- `mosaic/default_config.py`
- `mosaic/bridge/handlers/prompts.py`
- `mosaic/autoresearch/git_ops.py`
- `mosaic-ts/src/cli/commands/prompts.ts`（可新增）
- `tests/test_bridge_prompts.py`
- `tests/test_git_ops.py`

验收：

- 未配置 private prompt repo 时，普通 baseline 运行不受影响。
- 用户可以通过 init 命令创建 sparse private prompt repo。
- full seed 只能显式启用，并提示 shadowing 风险。
- autoresearch mutation 在未配置 private prompt repo 时失败。
- private prompt repo 不能被误设到项目 repo 内。

## Phase 2：Private GitOps 实例与写入路由

目标：复用现有 multi-repo-capable `GitOps(repo_root)`，把隐式项目 repo caller 改成按 target 路由到 private prompt repo。

任务：

1. 确认现状。
   - `mosaic/autoresearch/git_ops.py` 已经接收显式 `repo_root`。
   - `write_and_commit` 已经通过 worktree 提交，不会 dirty 主 checkout。
   - 当前隐式项目 repo 假设主要在 caller，例如 `prompts.py:_git() -> GitOps(_repo_root())`。
2. 提供显式实例。
   - `project_git = GitOps(project_repo_root)`
   - `prompt_git = GitOps(private_prompt_repo_root)`
3. 改造 caller 路由。
   - `prompts.write(target=private_git)` 使用 `prompt_git`。
   - `prompts.write(target=project_git)` 使用 `project_git`，但默认拒绝，仅用于 baseline 更新。
   - 不再在 `prompts.write` 内硬编码 `_repo_root()`。
4. 补充返回 metadata。
   - 返回 `repo_id`、`branch_name`、`base_commit_hash`、`commit_hash`。
5. 测试。
   - project git 和 prompt git 操作互不影响。
   - prompt git commit 不 dirty 项目 repo。
   - branch name 仍保持 `cohort/<cohort>/auto/<agent>/<date>`。

涉及文件：

- `mosaic/autoresearch/git_ops.py`
- `mosaic/bridge/handlers/prompts.py`
- `tests/test_git_ops.py`

验收：

- 在 private prompt repo 创建 autoresearch branch 后，项目 repo `git status --short` 仍干净。
- `git -C "$MOSAIC_PRIVATE_PROMPT_REPO" branch --list 'cohort/*/auto/*'` 能看到分支。

## Phase 3：Overlay Loader 读取 Private Prompt Repo

目标：模型运行时优先加载 private prompt repo，但不破坏项目 repo baseline。

任务：

1. 修改 TS prompt resolver。
   - `findPromptsRoot()` 仍返回项目 repo baseline root。
   - 新增 `findPrivatePromptRepoRoot()`。
   - `resolvePromptPath()` 支持 private-first candidates。
2. 修改 `loadPrompt()`。
   - cache key 包含 private repo root fingerprint、prompt repo commit hash 或文件内容 fingerprint。
   - 支持 pinned worktree root：evaluation / production 可把 private repo checkout 到指定 commit 的 worktree，再让 loader 读取该 worktree。
   - error message 不泄露私有绝对路径。
3. 增加 baseline drift 检测。
   - 当项目 repo baseline 改动影响已有 private override，输出 drift alert。
   - 该检查依赖 private prompt repo 或 prompt_versions DB，不作为项目 repo PR CI 的硬门禁。
   - critical drift 可以阻止 release/evaluation，除非显式 waiver。
4. 增加 compatibility validation。
   - 扫描 prompt 正文中的 `get_*` 工具 token，并对照 live `tools.list` registry。
   - 未知工具直接失败。
   - 声明式 prompt metadata/schema 校验留作未来增强。
5. 增加测试。
   - private cohort 覆盖 repo cohort。
   - private cohort_default 覆盖 repo cohort_default。
   - private 缺失时 fallback repo。
   - 未设置 private repo 时 baseline 行为不变。
   - pinned worktree checkout 后 loader 读取指定 commit 内容。
   - baseline 改动能触发 private override drift alert。
   - prompt 正文引用未知 `get_*` 工具时 validation 失败。

涉及文件：

- `mosaic-ts/src/agents/prompts/cohorts.ts`
- `mosaic-ts/src/agents/prompts/loader.ts`
- `mosaic-ts/test/prompt_loader.test.ts`
- `mosaic-ts/test/prompt_compatibility.test.ts`（可新增）
- `scripts/check_prompt_drift.py`（可新增）
- `docs/wiki/Configuration.md`
- `docs/wiki/zh/Configuration.md`

验收：

- 未设置 `MOSAIC_PRIVATE_PROMPT_REPO` 时，现有 prompt loading snapshot 不变。
- 设置 private prompt repo 后，daily-cycle 实际加载私有 prompt。
- loader cache 不会在 prompt repo branch/commit 切换后读到陈旧 prompt。
- evaluation / production 可以通过 pinned private prompt worktree 读取指定 commit。
- private override 遮蔽 baseline 修复时有 drift alert。

## Phase 4：`prompts.write` 写入 Private Git

目标：autoresearch 能写优化 prompt，但默认写到 private prompt repo 的 git branch，而不是项目 repo。

任务：

1. 扩展 bridge 协议。
   - `prompts.write` 新增 `target`。
   - 允许值：`private_git | project_git | working_tree`。
   - 默认：`private_git`。
2. 更新 TypeScript bridge 类型。
   - `mosaic-ts/src/bridge/types.ts`
   - `promptsWrite()` 参数和返回值都包含 repo metadata。
3. 实现 private git writer。
   - 校验 agent/cohort/lang。
   - 写入 `$MOSAIC_PRIVATE_PROMPT_REPO/prompts/mosaic/<cohort>/<layer>/<agent>.<lang>.md`。
   - 在 private prompt repo 中创建/更新 autoresearch branch。
   - commit prompt markdown。
   - 返回 `prompt_repo_id`、`prompt_branch`、`prompt_base_commit_hash`、`prompt_commit_hash`、`prompt_sha256`。
4. 保留项目 repo writer 但加硬限制。
   - `project_git` / `working_tree` 只用于公开 baseline 更新。
   - 需要 per-invocation flag，例如 `--allow-public-prompt-write`。
   - 不使用长期 `MOSAIC_ALLOW_PUBLIC_PROMPT_COMMIT=1` 作为推荐路径。
5. 扩展 tests。
   - private git write 不 dirty 项目 repo。
   - private git write 后 loader 能读到新 prompt。
   - project write 未授权时失败。
   - 授权 escape hatch 能用于 baseline 更新。

涉及文件：

- `mosaic/bridge/handlers/prompts.py`
- `mosaic/autoresearch/git_ops.py`
- `mosaic-ts/src/bridge/types.ts`
- `tests/test_bridge_prompts.py`
- `tests/test_git_ops.py`

验收：

- `prompts.write(target=private_git)` 在 private prompt repo 产生 branch + commit。
- 项目 repo 不出现 `prompts/mosaic/**` 修改。
- `prompts.write(target=project_git)` 默认被拒绝。

## Phase 5：Autoresearch 改为 Private Prompt Repo

目标：LLM 优化 prompt 后，正文进入 private prompt repo；项目 repo 只记录引用和指标。

任务：

1. 修改 TS orchestrator。
   - `promptsWrite` 调用默认传 `target: "private_git"`。
   - record mutation 时记录 private prompt repo 返回的 commit metadata。
2. 修改 mutation metadata。
   - `modification_summary` 是 LLM 撰写、可进入项目 DB 的字段，必须限长和脱敏。
   - `rationale` 不进公开日志；如需保存，只能进入 private prompt repo 或私有 artifact。
3. 修改 Python autoresearch store。
   - `prompt_versions` 增加 `prompt_repo_id`、`prompt_branch`、`prompt_base_commit_hash`、
     `prompt_commit_hash`、`prompt_sha256`、`baseline_code_commit_hash`、`code_commit_hash`。
   - 保留旧字段迁移路径，但明确旧 `base_commit_hash` / `modification_commit_hash` 的项目 repo 语义已废弃。
   - 新 `prompt_base_commit_hash` 指 private prompt repo base commit，不再指项目 repo main HEAD。
   - v1 评估仍以项目 baseline 作为 base run；`prompt_base_commit_hash` 先用于审计和后续“相对 live private prompt 再优化”的 A/B 切换。
4. 修改 evaluator / scorecard。
   - evaluation 使用 `prompt_repo_id + prompt_commit_hash + prompt_sha256 + code_commit_hash` 作为版本 key。
   - `mosaic/autoresearch/evaluator.py` 不再假设 prompt commit 属于项目 repo。
   - `mosaic/bridge/handlers/autoresearch.py` 的 pending/evaluate 逻辑按 private prompt repo commit 判断是否可评估。
   - `mosaic/scorecard/store.py` 的 backtest/run cache 不再只用单一 `prompt_commit_hash`。
5. 保留 evaluation worktree。
   - 代码仍从项目 repo worktree 运行。
   - prompt 通过 private prompt repo 的 pinned worktree 加载：先 checkout `prompt_commit_hash`
     到独立 worktree，再把 loader private root 指向该 worktree 的 `prompts/mosaic`。
   - evaluation 结束后清理临时 worktree；长期 production pinned worktree 由 release 管理并定期 GC。
6. 加入兼容性 gate。
   - evaluation 前扫描 prompt 正文中的 `get_*` 工具 token，并对照当前 code commit 暴露的 live `tools.list` registry。
   - 失败时不跑分，记录 incompatible 状态和原因。

涉及文件：

- `mosaic-ts/src/autoresearch/orchestrator.ts`
- `mosaic-ts/src/autoresearch/mutator.ts`
- `mosaic/bridge/handlers/autoresearch.py`
- `mosaic/autoresearch/evaluator.py`
- `mosaic/scorecard/store.py`
- `mosaic-ts/src/bridge/types.ts`
- `tests/test_autoresearch_store.py`
- `tests/test_bridge_autoresearch.py`
- `mosaic-ts/test/mutator.test.ts`

验收：

- `pnpm dev autoresearch trigger ...` 后项目 repo 仍干净。
- private prompt repo 中出现 `cohort/*/auto/*` 分支和 prompt markdown commit。
- DB 可查到 prompt repo id、prompt commit、prompt sha256、code commit 和指标。
- evaluation 使用 pinned private prompt worktree 的 prompt，而不是项目 repo baseline 或浮动 working tree。
- incompatible code/prompt 组合会失败并记录原因。

## Phase 6：Git 与 CI 防泄漏 Guard

目标：即使有人误操作，也不能轻易把优化 prompt 提交到项目 repo。

任务：

1. `.gitignore` 增加常见私有目录（次级护栏）。
   - `.mosaic/`
   - `private-prompts/`
   - `prompt-store/`
   - `data/private-prompts/`
2. 新增检查脚本。
   - 正常放行人工 baseline 编辑：`prompts/mosaic/**` 的常规 PR 改动不应仅因路径有改动就被拦。
   - 按 provenance 拦截 autoresearch 产物：自动分支命名、commit message/trailer 标记、private metadata、
     或优化正文出现在项目 PR diff 的判据，命中即失败。
   - 检测 private prompt repo 被放进项目 repo、submodule 或 artifact。
3. 接入 CI。
   - autoresearch 产物进入项目 PR 即失败。
   - private prompt repo path/submodule 进入项目 PR 即失败。
   - 正常 baseline 维护 PR 不被误伤。
   - 项目 repo CI 不运行 baseline drift check，因为它通常没有 private prompt repo 或 production DB。
4. 接入本地检查。
   - 提供 `pnpm prompt:check` 或 `uv run python scripts/check_prompt_leaks.py`。
5. 接入 operator-run / scheduled drift check。
   - 在有 private prompt repo 和 prompt_versions DB 的环境运行。
   - baseline 修改影响已有 private override 时，提示需要 private repo sync branch 或 waiver。

涉及文件：

- `.gitignore`
- `scripts/check_prompt_leaks.py`
- `scripts/check_prompt_drift.py`（operator-run / scheduled）
- `.github/workflows/ci.yml`
- `mosaic-ts/package.json`
- `docs/wiki/Contributing.md`
- `docs/wiki/zh/Contributing.md`

验收：

- 人工 baseline prompt PR 可以通过检查。
- autoresearch 产物进入项目 repo diff 时检查失败。
- private prompt repo 被误放进项目 repo 时检查失败。
- 项目 repo CI 不依赖 private prompt repo 或 production DB。
- operator-run / scheduled drift check 能发现 baseline 修改遮蔽已有 private override。

## Phase 7：日志、错误与 Artifact 脱敏

目标：prompt 正文不进入 stdout、stderr、JSON artifact、debug log、测试快照。

任务：

1. 日志策略。
   - 不打印 prompt body。
   - 不打印完整 private repo absolute path。
   - 只打印 agent/cohort/lang/repo id/hash。
2. 错误策略。
   - `PromptNotFoundError` redacts private paths。
   - LLM mutation failure 不 dump input prompt。
3. Artifact 策略。
   - autoresearch run artifact 只存 metadata。
   - dashboard 不展示 prompt body。
   - report export 不包含 prompt body。
4. 测试快照策略。
   - 只有优化 prompt 正文必须 synthetic；公开 baseline prompt 出现在测试里没问题。
   - 不把真实优化 prompt 复制到 tests。

涉及文件：

- `mosaic-ts/src/agents/prompts/loader.ts`
- `mosaic-ts/src/autoresearch/orchestrator.ts`
- `mosaic-ts/src/cli/commands/autoresearch.ts`
- `mosaic/bridge/handlers/prompts.py`
- `tests/`
- `mosaic-ts/test/`

验收：

- 失败日志中不出现 prompt 正文。
- `rg` 搜索测试快照不含真实优化 prompt 片段。
- CLI autoresearch 输出只含 repo id、hash、summary 和指标。

## Phase 8：Private Prompt Repo 备份、Review 与发布

目标：prompt 私有化后，仍然可 review、merge、rollback、备份、恢复、发布。

任务：

1. Review 流程。
   - autoresearch 创建 private prompt repo branch。
   - evaluator 跑分并记录指标。
   - 人在 private prompt repo review diff。
   - 通过后 merge 到 private prompt repo main。
2. 发布流程。
   - production pin `code_commit_hash + prompt_repo_id + prompt_commit_hash + prompt_sha256`。
   - 不默认使用 floating `private prompt repo main`，除非明确配置为实验环境。
   - 发布时创建 pinned prompt worktree，并让 runtime loader 读取该 worktree，而不是读取 private prompt repo 的浮动 checkout。
   - 发布前运行 compatibility validation 和 baseline drift check。
   - 维护 pinned worktree GC：删除未被 active release / recent eval 引用的 worktree。
3. 备份方案。
   - private prompt repo 配置 private remote。
   - remote 必须私有，权限只给必要用户和机器账号。
   - private prompt repo 必须有加密备份或加密静态存储策略；remote/account 泄露的 blast radius 是全部优化 prompt。
4. 恢复方案。
   - clone private prompt repo。
   - checkout pinned prompt commit。
   - 校验 sha256。
5. 审计方案。
   - 查询版本列表。
   - 查询 hash / metrics。
   - 默认不展示正文，除非用户在本地显式 `--show-content`。

涉及文件：

- `mosaic-ts/src/cli/commands/prompts.ts`（可新增）
- `mosaic/bridge/handlers/prompts.py`
- `mosaic/scorecard/store.py`
- `docs/wiki/CLI-Reference.md`
- `docs/wiki/zh/CLI-Reference.md`

验收：

- 可从 private prompt repo commit 恢复同一版 prompt。
- 恢复后 daily-cycle 能加载相同 hash 的 prompt。
- production 使用 pinned prompt worktree，切换 private repo branch 不影响已发布运行。
- code/prompt 不兼容或 critical baseline drift 未处理时，release 失败。
- 旧 evaluation / release worktree 可被安全清理，不会无限累积。
- 默认 CLI 不显示 prompt 正文。

## 配置建议

本地 autoresearch / 训练环境：

```bash
export MOSAIC_PRIVATE_PROMPT_REPO="$HOME/private-mosaic-prompts"
export MOSAIC_PROMPT_WRITE_TARGET=private_git
```

只读运行环境：

```bash
export MOSAIC_PRIVATE_PROMPT_REPO="/opt/mosaic/private-mosaic-prompts"
export MOSAIC_PROMPT_MODE=readonly
```

`MOSAIC_PROMPT_WRITE_TARGET` 是写入目标枚举，只允许 `private_git | project_git | working_tree`。只读运行是独立模式开关，不能作为 write target。

公开 baseline 更新：

```bash
pnpm dev prompts write-baseline --allow-public-prompt-write ...
```

不建议长期设置允许公开写入的环境变量。

## 任务清单

### P0 暴露面清点

- [x] 列出所有 prompt 读取路径。
- [x] 列出所有 prompt 写入路径。
- [x] 列出日志 / DB / artifact 泄漏点。
- [x] 列出 git / push / PR 泄漏点。
- [x] 审计已泄漏优化 prompt（分支 / history / remote）并产出 `docs/prompt-leak-audit.md` + scrub 决定。

### P1 Private Prompt Repo 初始化与配置

- [x] 增加 init-private-repo 命令。
- [x] 默认 sparse init，不复制 baseline。
- [x] 可选 `--seed-baseline`，并提示 shadowing 风险。
- [x] 增加 `MOSAIC_PRIVATE_PROMPT_REPO`。
- [ ] 增加 `MOSAIC_PROMPT_WRITE_TARGET`。
- [x] 校验 private repo 是独立 git repo。
- [x] 校验 private repo 不在项目 repo 内。
- [x] private path redaction。

### P2 Private GitOps 路由

- [x] 确认 `GitOps(repo_root)` 已显式化。
- [x] 提供 project git / prompt git 两个实例。
- [x] `prompts.write` caller 按 target 路由到 private prompt repo。
- [x] 返回 repo id、branch、base commit、commit hash。
- [x] git ops tests。

### P3 Overlay Loader

- [x] TS resolver 支持 private prompt repo first。
- [x] loader cache key 区分 private repo commit/content。
- [ ] loader 支持 pinned prompt worktree。
- [ ] operator-run / scheduled baseline drift alert。
- [ ] registry-scan compatibility validation。
- [ ] private path redaction。
- [x] loader tests。
- [ ] prompt compatibility tests。

### P4 Private Git Write

- [x] `prompts.write` 增加 `target=private_git`。
- [x] TS bridge 类型增加 target 和 repo metadata。
- [x] private git writer commit prompt markdown。
- [x] 默认禁止 project git prompt write。
- [x] bridge tests。

### P5 Autoresearch 双 Repo

- [x] orchestrator 默认写 private prompt repo。
- [x] mutation record 存 private prompt commit。
- [x] trigger 不再创建项目 repo prompt 分支。
- [x] keep/revert git 操作按 branch 所在 repo 选择 project/private GitOps。
- [ ] mutation record 存完整 prompt repo id / sha256 / code commit。
- [ ] evaluator 不再假设 prompt commit 属于项目 repo。
- [ ] evaluator 为 prompt commit 创建 pinned worktree。
- [ ] evaluator 清理临时 pinned worktree。
- [ ] scorecard cache key 升级为 prompt repo + prompt commit + prompt sha + code commit。
- [ ] registry-scan code/prompt compatibility gate。
- [x] autoresearch tests。

### P6 Git / CI Guard

- [ ] `.gitignore` 私有目录。
- [ ] 新增 prompt leak check script。
- [ ] CI 接入检查。
- [ ] CI 只做 leak/provenance guard，不依赖 private repo。
- [ ] baseline drift check 接入 operator-run / scheduled tool。
- [ ] 文档化 baseline 更新流程。

### P7 日志脱敏

- [ ] PromptNotFoundError redaction。
- [ ] autoresearch CLI 不输出 prompt body。
- [ ] mutation rationale 不进公开日志。
- [ ] 测试 fixture 去真实优化 prompt 化。

### P8 Review / Backup / Release

- [ ] private prompt repo review 流程。
- [ ] production pin code commit + prompt commit。
- [ ] production 使用 pinned prompt worktree。
- [ ] release 前运行 drift / compatibility checks。
- [ ] pinned worktree GC。
- [ ] private remote 权限说明。
- [ ] hash 校验恢复流程。
- [ ] 默认不显示正文的审计 CLI。

## 测试计划

Python：

```bash
uv run python -m pytest tests/test_bridge_prompts.py tests/test_git_ops.py -q
uv run python -m pytest tests/test_autoresearch_store.py tests/test_bridge_autoresearch.py -q
uv run python scripts/check_prompt_leaks.py
uv run python scripts/check_prompt_drift.py
git diff --check
```

TypeScript：

```bash
pnpm test -- prompt_loader
pnpm test -- mutator
pnpm test -- autoresearch
pnpm typecheck
pnpm lint
```

Manual smoke：

```bash
export MOSAIC_PRIVATE_PROMPT_REPO="$HOME/private-mosaic-prompts"
export MOSAIC_PROMPT_WRITE_TARGET=private_git
pnpm dev prompts init-private-repo "$MOSAIC_PRIVATE_PROMPT_REPO"
pnpm dev autoresearch trigger --cohort crisis_2008 --agent volatility --fake-llm
git status --short
git -C "$MOSAIC_PRIVATE_PROMPT_REPO" branch --list 'cohort/*/auto/*'
pnpm dev daily-cycle --cohort crisis_2008 --fake-llm
```

期望：

- 项目 repo `git status --short` 不出现 `prompts/mosaic/**` 修改。
- private prompt repo 下出现 autoresearch branch 和 prompt commit。
- DB 记录 prompt repo id、prompt commit hash、prompt sha256、code commit hash。
- daily-cycle 读取 private prompt。
- 未优化 agent 继续 fallback 项目 repo baseline。
- logs 只显示 repo id/hash，不显示 prompt 正文。

## 不做事项

- 不把 private prompt repo 放进项目 repo。
- 不把 private prompt repo 作为项目 repo submodule。
- 不把优化 prompt 正文写进 autoresearch DB 的公开字段。
- 不在项目 PR diff 中展示优化 prompt。
- 不在项目 CI artifact 中保存优化 prompt。
- 不默认 push private prompt repo 到任何未显式配置的 remote。

## 建议执行顺序

0. 先做 Phase 0 的已泄漏审计：若已有优化 prompt 进了公开 remote，scrub 是第一优先级。
1. 做 Phase 1 + Phase 2：建立 private prompt repo 配置和 multi-repo GitOps。
2. 做 Phase 3：runtime overlay loader，确保模型能读取 private prompt repo。
3. 做 Phase 4 + Phase 5：把 autoresearch 写入和评估链路切到 private prompt repo。
4. 做 Phase 6 + Phase 7：补上 git/CI/log 防泄漏护栏。
5. 做 Phase 8：review、backup、restore、release pinning。
