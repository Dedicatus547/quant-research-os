# 文档目录

从任务选择入口。当前状态、操作方法、设计规则和历史证据分别维护，避免重复查找。

## 使用与开发

| 文档 | 内容 |
|---|---|
| [快速上手](guides/quickstart.md) | 安装、环境检查、最小离线示例 |
| [离线工作流](guides/offline-workflows.md) | 研究、回测、验证、Registry 与 Ledger |
| [数据与 Evidence 采集](guides/acquisition.md) | Tushare 与公告采集边界、发布方法 |
| [资格证据核验](guides/qualification.md) | 精确 checkout、保留证据、完整与 bundle 核验 |
| [开发指南](guides/development.md) | 仓库结构、CI、文档维护 |

## 系统设计

| 文档 | 内容 |
|---|---|
| [架构总览](architecture/overview.md) | 主流程、模块职责、复用边界 |
| [Contracts 与 provenance](architecture/contracts.md) | schema、状态、哈希域、不可变发布 |
| [数据与 PIT](architecture/data-and-pit.md) | endpoints、单位、membership、availability、Qlib view |
| [研究与回测](architecture/research-and-backtest.md) | safe DSL、Qlib ML、Signal、回测和 reconciliation |
| [验证与 Registry](architecture/validation-and-registry.md) | G0–G10、稳健性、OOS、策略历史 |
| [Agent 与 campaign](architecture/agent-and-campaign.md) | Evidence/admission、typed capabilities、Ledger、选择 |
| [冻结契约索引](contracts/README.md) | 精确路径与批准版本的 P14 契约 |
| [ADR 索引](adr/README.md) | Harness、公告采集与 SDK 决策 |

## 状态、路线与发布

| 文档 | 内容 |
|---|---|
| [当前状态](status/README.md) | 各阶段资格范围与未资格化能力 |
| [P14 状态](status/p14.md) | 当前报告、工程/研究结果、一致性范围 |
| [FR-03 状态](status/fr03.md) | `NO_GO`、薄维护、候选 runtime 重资格条件 |
| [实施路线图](../PLAN.md) | 依赖与下一项工作 |
| [第一阶段验收](roadmap/stage-one.md) | P0–P7 和独立 DQ 轨道 |
| [第二阶段验收](roadmap/stage-two.md) | P8–P14 与 FR 入口门 |
| [发布记录](releases/README.md) | 当前 RC 修正和历次冻结记录 |
| [审查记录](reviews/README.md) | 契约批准、资格接受与历史评审 |
| [历史文档](history/README.md) | 重组前的完整文档快照 |

## 参考

- [CLI 命令索引](reference/cli.md)
- [术语](reference/glossary.md)
- [风险登记](reference/risks.md)
- [设计资料](reference/design-sources.md)
- [Qlib 0.9.7 可行性与限制](feasibility/qlib-0.9.7.md)

## 目录职责

```text
docs/
├── guides/         操作方法
├── architecture/   设计规则与边界
├── status/         当前完成范围
├── roadmap/        阶段入口与验收
├── reference/      命令、术语、风险、资料
├── contracts/      冻结契约导航
├── adr/            决策原始记录
├── releases/       发布与冻结原始记录
├── reviews/        批准与评审原始记录
└── history/        原文归档
```

少量冻结契约保留在 `docs/` 原路径，因为资格脚本按精确路径和哈希读取它们。
旧 progress、FR-03 和 refactor 路径保留简短入口，正文集中在历史快照。

## 阅读与维护约定

- 日常查阅使用 `guides/`、`architecture/`、`status/`；完整哈希与历史结论查阅记录。
- 资格与完成状态集中维护在 `status/` 和路线图，其他页面链接引用。
  历史记录的“当前/下一步”属于原记录日期；技术说明按明确实现基线读取。
- 相同技术事实在一处维护，其他页面链接引用。
- 契约修订、批准、资格接受与冻结使用新记录；不把失败或旧报告改写为当前 PASS。
- `artifacts/` 是授权工作区中的证据目录，缺失本地数据不能由文档声明替代。
