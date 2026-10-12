# quant-research-os

面向 A 股日频研究的可审计工程系统：冻结 Tushare 数据为不可变 Parquet 快照，
复用 Qlib 计算、训练和回测，通过确定性程序生成验证报告与历史记录。

Agent 负责提出和解释研究建议。数据处理、PIT、执行及验证门保持确定性。

## 开始使用

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv sync --frozen
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run --frozen quantos doctor
```

接下来阅读[快速上手](docs/guides/quickstart.md)，或按任务进入[文档目录](docs/README.md)。

| 你要做什么 | 阅读入口 |
|---|---|
| 安装并跑通离线示例 | [快速上手](docs/guides/quickstart.md) |
| 执行研究、验证与 Registry 流程 | [离线工作流](docs/guides/offline-workflows.md) |
| 使用有界 Codex-hosted 工作流 | [HM-MVP 快速上手](docs/hosted/hm-mvp-quickstart.md) |
| 采集市场数据或公告 | [数据与 Evidence 采集](docs/guides/acquisition.md) |
| 核对资格报告、实现和运行环境 | [资格证据核验](docs/guides/qualification.md) |
| 理解系统设计和权威边界 | [架构总览](docs/architecture/overview.md) |
| 查看完成范围与阻塞项 | [当前状态](docs/status/README.md) |
| 查看后续工作和验收条件 | [路线图](PLAN.md) |

## 当前完成范围

| 工作 | 状态与入口 |
|---|---|
| P0–P14 确定性研究链 | 已完成各自批准范围；[当前资格与科学结果](docs/status/README.md) |
| HM-MVP component-v2 | 已冻结，campaign 已结束、额度耗尽；[使用与运行限制](docs/status/hosted.md) |
| FR-03 SDK/runtime | `0.162.1 + gpt-6.1-sol / medium` 确切组合 GO，实现已合入本地 main、尚未部署；[接受范围](docs/status/fr03.md) |
| Discovery 探索性研究 | 两轮有界比较已完成；第二轮未观察到相对最佳基线的质量增量，暂停扩大当前空间同类生成；[结果与后续](docs/status/discovery.md) |

默认 SDK 依赖仍为 `0.154.0`；使用已接受的后继需显式命名 profile。
P14d-C 仍为 `BLOCKED_UNIMPLEMENTED`。合并后的定向检查与资格边界见
[合并审核](docs/reviews/two-worktrees-merge-20261012.md)，历史发布身份见[发布记录](docs/releases/README.md)。

## 使用边界

- 市场数据事实源是不可变 Parquet 快照；Qlib `.bin` 是派生缓存。
- Tushare 只由快照采集层调用；后续研究、回测、验证和 Registry 离线运行。
- Qlib/MLflow 本地目录用于运行记录；导出的不可变产物和哈希承担证据权威。
- 工程 PASS 不授予 alpha、盈利、投资适用性、sealed confirmation 或无限制自主研究权威。
- P14-DQ 复现范围包含精确输入、实现、运行指纹、批准的环境记录及 `PYTHONHASHSEED=0`。
- 数据保持 `SINGLE_SOURCE_NON_VINTAGE` 限制；不具备历史供应商 vintage PIT 资格。

`artifacts/` 中的链接指向授权工作区中的证据，通常不随 Git 分发。
新克隆缺少这些数据时，可阅读文档中的绑定信息并运行 synthetic 示例。

开发约束见 [AGENTS.md](AGENTS.md)，质量门与文档维护方式见
[开发指南](docs/guides/development.md)。
