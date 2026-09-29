# CLI 命令索引

本页按当前 `src/quantos/cli.py` 的实际 command surface 整理。
详细参数以 `uv run --frozen quantos <group> <command> --help` 为准。
Hash-addressed 输入必须使用显式完整路径，不能解析 mutable alias。

## 主入口：quantos

| 命令 | 用途 |
|---|---|
| `doctor` | 环境与本地能力检查 |
| `tushare probe` | 有界账号 capability probe；采集层联网 |
| `snapshot build-synthetic` | 从本地 fixture 发布 synthetic snapshot |
| `snapshot build-tushare` | 按显式 spec/execution/DQ policy 采集并发布 |
| `snapshot verify` | 核验不可变 snapshot |
| `qlib build-view` | 用锁定官方工具生成派生 view |
| `qlib verify-view` | 核验 view manifest、精确文件集合及文件 hash；保留所记录的 snapshot 身份 |
| `pit audit` | Snapshot-bound lineage/PIT audit |
| `backtest run` | 显式 SignalArtifact → Qlib reference backtest |
| `backtest verify` | 核验已发布 BacktestArtifact |
| `experiment run` | 已发布完整产物集合 → G0–G10 / ValidationReport |
| `experiment verify` | 核验已发布报告 artifact；完整性 PASS 与报告内研究 verdict 分别输出 |
| `release data-qualified` | 执行明确 snapshot 的 Data-qualified release pipeline |
| `registry register-experiment` | 重验来源并登记实验历史 |
| `registry register-strategy` | 登记显式策略版本 |
| `registry transition` | 按状态机追加版本事件 |
| `registry list / show` | 读取可重建索引 |
| `registry verify` | 核验 Registry chain 与产物 |
| `registry recover` | 清理遗留原子写临时文件 |
| `ledger verify` | 核验 Ledger event chain；需要 root 和 ledger ID |
| `ledger search` | 对冻结 snapshot、policy、scope、request 生成检索结果 |
| `ledger context-pack` | 从冻结 search result 与 context budget 发布上下文 |
| `campaign selection-report` | 消费完整 campaign/family/trials 生成选择报告 |
| `campaign selection-verify` | 核验明确选择报告及其输入 |

`experiment run` 是 validation 命令，不是隐式 signal/backtest builder。
`release data-qualified` 会执行并发布新证据，不是只读检查命令。

`qlib verify-view` 不重新读取源 snapshot，也不重跑 converter/health check；
实际外部输入绑定与 bottom-up 重建需使用相应[资格核验流程](../guides/qualification.md)。

## Evidence 独立入口

| 入口 | 用途 |
|---|---|
| `quantos-evidence-collector` | 按 collection/collector policy 联网冻结 staging |
| `quantos-evidence-publisher publish` | 离线核验并发布 Evidence Store |

网络、挂载和 authority 规则由运行 sandbox 强制，详见[采集指南](../guides/acquisition.md)。

## Scripts

| 类别 | 入口与文档 |
|---|---|
| Qlib 工具准备 | `scripts/bootstrap_qlib_tools.py` |
| 工程完整链 | `*_feasibility.py`；[离线工作流](../guides/offline-workflows.md) |
| P13 qualification | `scripts/p13_qualification.py`；[P13 冻结](../p13-v2-freeze.md) |
| P14a / c / d qualification | `scripts/p14a_qualification.py`、`p14c_qualification.py`、`p14d_qualification.py` |
| P14-DQ | `scripts/p14dq_qualification.py run / verify / verify-bundle` |
| FR-03 diagnostics | 历史固定 runner；入口受[薄维护政策](../status/fr03.md)限制 |

资格 verifier 是否重建、对 HEAD 的要求和环境范围见[核验指南](../guides/qualification.md)。
旧计划中的概念命令不作为已实现 CLI。

## 常用任务

- [最小 snapshot/view](../guides/quickstart.md)
- [PIT、回测、Validation、Registry](../guides/offline-workflows.md)
- [采集与 Evidence 发布](../guides/acquisition.md)
- [冻结报告核验](../guides/qualification.md)
