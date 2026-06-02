# 贡献指南

## 分支命名

- 人工:`phase-x-<feature>` / `fix-<scope>` / `chore-<scope>`。
- Autoresearch 自动分支:`cohort/{name}/auto/{agent}/{YYYY-MM-DD}`。

不要直接推 `main`;开 PR。

## 验证矩阵(提 PR 前全绿)

```bash
# TypeScript(在 mosaic-ts/ 下)
pnpm typecheck && pnpm lint && pnpm test
# Python(仓库根)
ruff check mosaic tests && python -m pytest -q
```

CI 在 `.github/workflows/ci.yml` 跑同样内容(一个 Python lane + 一个 TS lane)。TS lane 会建一个仓库根 `.venv` 装 bridge 依赖,使 live-sidecar 测试能 spawn 桥。

注意:
- `ruff` 排除 vendored 采集器(`mosaic/dataflows/collectors`)—— 第三方,逐字保留。
- 部分测试由 `_HAS_QLIB` / 依赖存在性 guard,当某可选 extra(如 `pyqlib`、`bcrypt`、`numpy`)缺失时干净跳过,使套件可 hermetic 运行。
- CI 也会运行 prompt leak guard。它会阻止 autoresearch/private prompt 产物进入项目 repo,但它是 provenance-based 检查,不对普通 prompt 正文做内容分类。
- 当 PR 修改 `prompts/mosaic/**` 且你运行 private prompt repo 时,在 `mosaic-ts/` 下设置 `MOSAIC_PRIVATE_PROMPT_REPO` 后运行 `pnpm prompt:drift -- --base-ref origin/main`。检查是 staleness-aware 的:只报告尚未与变更后 baseline **内容**对齐的 override(对齐状态按路径记录在 private repo 的 `prompts/mosaic/.baseline-sync.json`)。把 baseline 的工具/schema/contract 变更并入某个被标记的 override 后,用 `-- --mark-synced` 重新运行以记录其已对齐 —— 之后直到该 baseline 内容再次变化前都不再告警。
- scheduled operator check 先用已知安全的 `baseline_ref` 初始化 `data/prompt-drift-state.json`,再在 `mosaic-ts/` 下设置 `MOSAIC_PRIVATE_PROMPT_REPO` 并运行 `pnpm prompt:drift:scheduled`。检查通过时 state 会前进;优先用 `-- --mark-synced` 精确确认具体 override,或用 `-- --accept` 一次性把 state 推进到当前所有 findings 之后。

## 约定

- 每个 PR 聚焦单一关注点;描述含改了什么 / 怎么测的 / 已知限制。
- 新能力应**可选开关(opt-in,默认关)**且保持默认行为向后兼容 —— 参考 MiroFish 开关与 autoresearch git-push 标志的模式。
- 写最小化、直接满足需求的代码;匹配既有风格与已用库。
- 工具边界仅字符串/JSON(无跨语言 DataFrame 传输)。

## 各部分位置

仓库地图见[架构](Architecture.md)。权威设计 + 阶段日志是仓库根的 [`mosaic-tsplan.md`](../../../mosaic-tsplan.md)。
