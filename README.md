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

## 当前工程范围

P0–P7 工程发布与批准范围内的 P8–P14 功能已完成。
P14d-B 和 P14-DQ 的当前资格报告均绑定生产提交
`e318dc450e5c02f1120da7644250767bf682b6f9`。

P14-DQ 工程结果为 `SUCCEEDED / PASS`；自然研究结果为
`FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`，零个合格候选，未执行选择。
FR-03 的 SDK/runtime `0.162.1 + gpt-6.1-sol / medium` 已在本工作线完成资格
`GO`；[接受范围与原件](docs/status/fr03.md)绑定明确后继，实现已合入本地 main，尚未部署。
默认 canonical dependency pin 仍为 `0.154.0`；P14d-C 为 `BLOCKED_UNIMPLEMENTED`。

有界 Codex-hosted MVP（component-v2）已完成工程实施、真实交接与离线回放、
独立接受、操作文档及本地发布登记。精确 C15 源码和组件采用范围见
[HM-MVP 发布记录](docs/releases/hm-mvp-component-v2-freeze-marker.md)。
正式冻结标签为 `hm-mvp-component-v2`，目标提交 `59c25ac`；原接受源码 C15 的身份与历史保留。
两项科学执行均为 `SOFT_REJECT`，原 ValidationReport 均为 `SUCCEEDED / REJECT`。
已完成 campaign 的额度已用完、服务已清理；后续新运行按
[快速上手](docs/hosted/hm-mvp-quickstart.md)和[恢复手册](docs/hosted/hm-mvp-recovery.md)办理。

RC 的逐字节一致性表述已在[修正记录](docs/releases/p14-rc-v1-equality-correction.md)中澄清。
P14 v1 已冻结；本地 annotated tag `p14-rc-v1` 指向独立复审批准的提交 `3a4a898`。
审查报告和冻结边界见[独立复审](docs/reviews/p14-rc-3a4a898-independent-review.md)
及[freeze marker](docs/releases/p14-rc-v1-freeze-marker.md)。

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
