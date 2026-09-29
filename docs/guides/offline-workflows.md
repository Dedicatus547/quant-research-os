# 离线工作流

本页从已发布的 snapshot、view 和研究产物开始。
环境准备见[快速上手](quickstart.md)，采集见[采集指南](acquisition.md)。

Canonical 执行要求干净实现 checkout、锁定依赖、显式输入哈希与版本化 policy。
下列占位路径均需替换为实际不可变路径。生产服务会重新验证输入内容与 lineage。

## 1. 运行 PIT audit

```bash
uv run --frozen quantos pit audit \
  'artifacts/data/snapshots/sha256-<snapshot_hash>' canonical-pit-request.json
```

request 指定 selector、safe expression、schedule 和 operator delay。
源时间与 membership 由已验证 snapshot 解析，不接受调用者自报。
未知 availability、伪造 lineage 或不完整窗口均拒绝。

`canonical-pit-request.json` 是需自行准备的运行时文件，遵循
[CanonicalPITAuditRequest](../../src/quantos/contracts/pit.py)，不是仓库附带的 fixture。

## 2. 生成研究产物

Expression 服务发布 SignalArtifact；native Qlib `DatasetH / LGBModel / Workflow`
导出与其绑定的 ResearchResult。事件服务发布独立 EventSignalArtifact。
[研究与回测设计](../architecture/research-and-backtest.md)说明输入和产物。

既有工程 runner 可在干净实现 checkout 中运行：

| Runner | 证明范围 |
|---|---|
| `scripts/qlib_feasibility.py` | 锁定 Qlib 组件的离线可行性 |
| `scripts/signal_feasibility.py` | 显式 synthetic snapshot/view → SignalArtifact |
| `scripts/backtest_feasibility.py` | synthetic 完整回测链与 reconciliation |
| `scripts/validation_feasibility.py` | synthetic native-Qlib 双管线与 G0–G10 |
| `scripts/release_feasibility.py` | synthetic Validation → Registry 发布链 |
| `scripts/p13_event_signal_feasibility.py` | synthetic EventFeature → native-Qlib bridge |

这些 runner 会执行和发布证据；它们不是只读 verifier，也不自动获得 Data-qualified 资格。
完整冻结资格的读取与重建见[核验指南](qualification.md)。

## 3. 回测显式 SignalArtifact

```bash
uv run --frozen quantos backtest run \
  'artifacts/research/signals/sha256-<signal_hash>' \
  'artifacts/data/qlib-views/sha256-<view_hash>' \
  configs/backtest/cost_v1.yaml configs/backtest/policy_v1.yaml

uv run --frozen quantos backtest verify \
  'artifacts/research/backtests/sha256-<backtest_hash>'
```

resolved experiment 从 SignalArtifact 读取并重新核验。
Qlib Exchange、Simulator 和 Position 负责执行与会计；项目不实现替代引擎。

## 4. 验证完整产物集合

```bash
uv run --frozen quantos experiment run \
  configs/research/hs300_momentum_v1.yaml \
  configs/validation/research_candidate_v1.yaml \
  configs/research/policy_v1.yaml validation-run-locators.yaml

uv run --frozen quantos experiment verify \
  'artifacts/validation/sha256-<validation_report_hash>'
```

`experiment run` 消费已经发布的 signal/backtest 及完整稳健性网格。
它不会隐式构建缺失产物。运行时 locator 文件需列出：

- snapshot、view、baseline SignalArtifact 与 BacktestArtifact；
- 独立执行的 reproduction BacktestArtifact；
- policy 要求的 cost、parameter、subperiod 产物；
- 启用 `rank_ic / icir` 阈值时，额外提供已发布的 `research_result_path`。

`validation-run-locators.yaml` 是需自行准备的运行时文件；
完整 schema 与字段名见[ValidationRunLocators](../../src/quantos/validation/locators.py)。
Locator 是定位信息。G0–G10 重新打开、验 hash、核 lineage 后才使用其内容。
`--development` 标记 `canonical: false`，仍保留产物、PIT、稳健性和复现检查。

`experiment verify` 核验报告 artifact 完整性；输出 `status=PASS` 时，
报告自己的 `run_status / verdict` 仍可为 `SUCCEEDED / REJECT` 或 `FAILED / NOT_EVALUATED`。
它不会重新执行原研究或把该研究改为 PASS。

## 5. 登记并检查 Registry

```bash
uv run --frozen quantos registry register-experiment \
  'artifacts/validation/sha256-<validation_report_hash>' \
  --event-root artifacts/events \
  --snapshot-path 'artifacts/data/snapshots/sha256-<snapshot_hash>' \
  --qlib-view-path 'artifacts/data/qlib-views/sha256-<view_hash>' \
  --signal-path 'artifacts/research/signals/sha256-<signal_hash>'

uv run --frozen quantos registry verify artifacts/registry
uv run --frozen quantos registry list
uv run --frozen quantos registry show '<experiment-or-strategy-id>'
```

登记会重新验证报告、来源和所需 OOS event。失败和拒绝实验也保留。
`register-strategy` 与 `transition` 遵守策略版本和状态机；索引可重建。
`recover` 仅处理遗留原子写临时文件，不重写证据。

## Ledger 与 campaign

Ledger 的 `verify / search / context-pack` 分别核验事件链、生成检索结果和冻结上下文。
Campaign 的 `selection-report / selection-verify` 消费完整 trial set。
参数见 [CLI 索引](../reference/cli.md)和各命令 `--help`。

单实验 Validation PASS 不等于 campaign selection，也不等于 sealed confirmation 资格。
当前 P14-DQ 自然研究结果见 [P14 状态](../status/p14.md)。
