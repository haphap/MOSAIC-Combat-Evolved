# Prompt Leak Audit

日期：2026-06-01

## 结论

本次审计覆盖当前本地 refs 和 `origin` fetch/prune 后可见的远端 refs。结论：

- 未发现 `cohort/*/auto/*` 或 `autoresearch/*` 运行时自动分支。
- 未发现 commit message 为 `autoresearch: ...` 的 prompt mutation commit。
- 未发现 `prompts/mosaic/**` 中包含 `autoresearch`、`fake mutation`、`modification_summary`、`rationale` 等自动 mutation marker。
- 当前可见的 prompt 历史主要是公开 baseline prompt 初始化、工具 wiring、schema/工具变更等人工维护提交。
- 仍存在结构性泄漏风险：当前 autoresearch 写入路径会把优化 prompt markdown 提交到项目 repo 分支；必须按双 repo 计划迁移。

## 当前可见分支

自动运行分支：

```text
无
```

本地 autoresearch 相关开发分支：

```text
feat-autoresearch-git-push
phase-4c-5-autoresearch-prism
```

fetch/prune 后，远端对应开发分支已删除；当前未见 `origin/cohort/*`、`origin/autoresearch/*` 或 `origin/*autoresearch*` 运行分支。

## Prompt 历史

`git log --all -- prompts/mosaic` 当前可见 prompt 相关提交：

```text
f99f409  2026-06-01  feat(moneyflow): server-side industry filter + per-sector THS names; review nits
fbf57c8  2026-06-01  chore: drop get_north_capital_flow (北向资金停更) + redesign 3 schemas
6c06b72  2026-06-01  feat(data): stock + industry money-flow tools (doc 170/342) + plan §18
f13e831  2026-06-01  docs(prompts): fix EM step numbering + financials ETF (review)
fdad43b  2026-06-01  docs(prompts): wire ETF tools into emerging_markets + sector prompts
73ccde5  2026-06-01  docs(prompts): wire research-report tools into the 7 sector prompts
d3f5d7f  2026-05-29  feat: add PRISM 7-cohort training orchestration (Phase 5)
b4bdf47  2026-05-29  Phase 2D.3: 4 decision agents (Layer 4 complete)
1343f57  2026-05-29  Phase 2D.2: 4 superinvestor agents (Layer 3 complete)
7097058  2026-05-29  Phase 2D.1: 7 sector agents (Layer 2 complete)
546a0ea  2026-05-29  Phase 2C.2: 8 macro agents (Layer-1 complete)
2aaa70a  2026-05-29  Phase 2C.1: extract Layer-1 factory + add china
30de5a1  2026-05-29  Phase 2B: central_bank vertical slice
4a41c61  2026-05-29  Phase 2A.1: state schema + prompt loader + cohort path
```

这些提交应视为项目 repo 的公开 baseline prompt 历史，不是已识别的优化 prompt 泄漏。

## 现有泄漏面

### 1. `prompts.write` 写项目 repo

当前 `prompts.write` 仍硬编码使用项目 repo：

- `_git()` 返回 `GitOps(_repo_root())`。
- 有 `branch` 时调用 `write_and_commit()`。
- 写入路径是 `prompts/mosaic/<cohort>/<layer>/<agent>.<lang>.md`。

风险：

- autoresearch mutation 的完整 `zh` / `en` prompt 会进入项目 repo git commit。
- 即使不 dirty 主 checkout，prompt 正文仍在分支 commit 中。
- 分支被 push、PR、merge、CI artifact 捕获后，会暴露优化 prompt。

相关文件：

- `mosaic/bridge/handlers/prompts.py`
- `mosaic/autoresearch/git_ops.py`

### 2. TS orchestrator 发送完整 mutation body

当前 orchestrator 把 LLM 生成的完整 prompt 传给 `prompts.write`：

```text
contents: { zh: mutation.zh_prompt, en: mutation.en_prompt }
branch: triggerResult.branch_name
message: autoresearch: <modification_summary>
```

风险：

- bridge 调用失败日志需要避免 dump params。
- mutation summary 是 LLM 生成文本，可能泄漏策略细节，应限长和脱敏。

相关文件：

- `mosaic-ts/src/autoresearch/orchestrator.ts`
- `mosaic-ts/src/autoresearch/mutator.ts`

### 3. DB metadata 指向含正文 commit

当前 DB 不存 prompt 正文，但字段语义仍指向项目 repo commit：

- `branch_name`
- `base_commit_hash`
- `modification_commit_hash`
- `modification_summary`

风险：

- `modification_commit_hash` 指向的 commit 可能包含完整优化 prompt。
- `base_commit_hash` / `modification_commit_hash` 当前都是项目 repo 语义，后续必须迁移为 private prompt repo 语义或新增字段。

相关文件：

- `mosaic/scorecard/store.py`
- `mosaic/autoresearch/evaluator.py`
- `mosaic/bridge/handlers/autoresearch.py`

### 4. 本地开发分支含 prompt baseline diff

本地 `feat-autoresearch-git-push` 和 `phase-4c-5-autoresearch-prism` 相对 `main` 都包含 `prompts/mosaic/cohort_default/**` 的 prompt diff。

判断：

- 这些是开发分支，不是运行时 autoresearch mutation 分支。
- 未发现 autoresearch marker。
- 不作为已识别泄漏处理。

处置：

- 可保留本地开发分支。
- 后续 guard 需要区分人工 baseline prompt PR 和 autoresearch 产物，避免误伤正常 prompt 维护。

## 已执行检查

```bash
git fetch --all --prune
git branch --all --list 'cohort/*' 'autoresearch/*' '*auto*' '*autoresearch*'
git log --all --date=short --format='%h%x09%ad%x09%D%x09%s' -- prompts/mosaic
git log --all --date=short --format='%h%x09%ad%x09%D%x09%s' --grep='autoresearch:' --all
git grep -n -I -e 'autoresearch' -e 'fake mutation' -e 'modification_summary' -e 'rationale' <all_refs> -- prompts/mosaic
git diff --name-status main..feat-autoresearch-git-push -- prompts/mosaic
git diff --name-status main..phase-4c-5-autoresearch-prism -- prompts/mosaic
```

## Scrub 决定

当前可见 refs 下未发现需要立即 scrub 的运行时优化 prompt 泄漏。

不执行：

- 不删除本地开发分支。
- 不改写 git history。
- 不 force-push。

需要继续：

- 如果曾经存在已删除的远端自动分支，当前 fetch/prune 后不可直接审计其内容；如需要更强保证，应在 GitHub 侧审计 closed PR、deleted branch audit log、forks 和 caches。
- 进入 Phase 1 前，不应再运行会写项目 repo 的 autoresearch mutation。

## 下一步

1. 实施 Phase 1：新增 private prompt repo 初始化、配置和边界校验。
2. 实施 Phase 2：复用现有 `GitOps(repo_root)`，让 `prompts.write` 按 target 路由到 private prompt repo。
3. 在 Phase 4 完成前，把 autoresearch mutation 视为危险操作：除非明确 dry-run，否则不要在项目 repo 中运行会写 prompt branch 的流程。
