# 资格证据核验

核验结论必须记录实现提交、报告 hash、检查范围和运行环境。
先从[当前 P14 绑定](../releases/p14-rc-v1-equality-correction.md)确定证据身份；
不要根据目录名或历史文档中的“当前”选择报告。

## 核验层级

| 操作 | 检查范围 | 可报告的结论 |
|---|---|---|
| 阅读记录与报告 | 绑定、状态、限制、历史身份 | 文档与报告中的声明 |
| Bundle integrity | 报告 canonical bytes、hash、完整文件清单、冻结输入副本 | 保留 bundle 完整性 |
| 外部输入核验 | 实际 snapshot/view/upstream release 与绑定一致 | 这些外部输入确实被核验 |
| Full verifier | 上述检查及按冻结实现重新构建双根 | 对应契约范围内的 bottom-up 结果 |

Bundle 检查不执行 Qlib 双根重建，也不重新验证实际外部数据。
核验结果不能跨层级表述。

本文报告身份使用 `qualification_hash`，它是 contract 的内容哈希。
`sha256sum qualification-report.json` 得到的是原始文件哈希，不能与它直接比较；
定义见[Contracts](../architecture/contracts.md)。

## 完整核验的前提

P14d-B 和 P14-DQ full verifier 要求：

- checkout 的 `HEAD` 是报告绑定的精确实现 `e318dc450e5c02f1120da7644250767bf682b6f9`；
- Git 工作区干净，`uv.lock`、Qlib 和 runtime fingerprint 与相应报告匹配。

P14d-B 从实现 checkout 中的 `tests/fixtures/p14d_qualification/` 读取已冻结的
synthetic snapshot/view，不要求 Tushare snapshot 或额外下载官方转换器。
P14-DQ 还要求批准的 runtime-environment、`PYTHONHASHSEED=0`，
以及规定路径下的授权 snapshot/view/upstream release；不能用 symlink 替代。

使用独立的干净实现 checkout 核验。文档后继提交的 HEAD 不满足实现 HEAD 等式，
即使它只修改文档。不要将它的拒绝解释为原资格失效，也不要放宽 verifier。

本页提供操作示例，不授权重新采集数据或运行 live Agent。

## P14c retained verifier

保留资格按契约核验，不因后续生命周期修复而自动要求新资格：

```bash
env -u TUSHARE_TOKEN uv run --frozen python scripts/p14c_qualification.py --verify \
  artifacts/qualification/p14c/sha256-d0412a30d27c4d793fe527a28432292f1616a4ad726830d3cb1ce24a5836913a
```

## P14d-B full verifier

以下命令在满足上述前提的实现 checkout 内运行：

```bash
env -u TUSHARE_TOKEN uv run --frozen python scripts/p14d_qualification.py --verify \
  artifacts/qualification/p14d-qlib-drain-e318dc4/sha256-41a27c6fd2b5f0f522a1fcae13424b924b9cdc2fa4e8aa0df24ff12d79fadc71
```

它核验 bundle 并重建 root-A/root-B，覆盖 canonical cases。
两根合计 54 个负例、6 个 restart 用例，即每根 27 个负例、3 个 restart 用例。
Synthetic SELECTED 仅证明选择工程路径。

## P14-DQ bundle 与 full verifier

Bundle-only 示例：

```bash
env -u TUSHARE_TOKEN PYTHONHASHSEED=0 uv run --frozen python scripts/p14dq_qualification.py \
  verify-bundle --artifact \
  artifacts/qualification/p14-dq-qlib-drain-e318dc4/sha256-f912cb0b376c981c94dae267cb0b16a4d2f1e0a52edcd36d08f938f92964d38a
```

完整核验在精确实现 checkout 中显式提供冻结上游：

```bash
env -u TUSHARE_TOKEN PYTHONHASHSEED=0 uv run --frozen python scripts/p14dq_qualification.py verify \
  --workspace . \
  --artifact artifacts/qualification/p14-dq-qlib-drain-e318dc4/sha256-f912cb0b376c981c94dae267cb0b16a4d2f1e0a52edcd36d08f938f92964d38a \
  --snapshot-path artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9 \
  --qlib-view-path artifacts/data/qlib-views/sha256-fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b \
  --upstream-release-report artifacts/releases/data-qualified-v0.1-f3fc768/report.json
```

完整核验在两根合计覆盖 54 个 P14d 负例、24 个 DQ 负例、6 个 restart 用例；
每根分别为 27、12、3 个，并核验自然研究结果。
工程 `SUCCEEDED / PASS` 不改变研究 `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`。

## 比较范围与结果留证

- Principal evidence 按冻结契约的权威哈希域比较。
- DQ artifact-tree inventory 排除各根 `root-evidence.json`；仅对带顶层 `created_at`
  的 JSON 对象删除该字段并 canonicalize，其他文件保持原始字节。
- 原始文件清单分别绑定各根完整字节；不能称整个原始输出树 byte-exact。
- Qlib Position 的 set-order 敏感性仍存在；seed `0` 之外没有确定性资格。

记录实际执行的命令、HEAD、环境、报告身份、状态与失败原因。
Failed/blocked attempts 独立保存，不能覆盖或改写为 accepted report。
原始规则见[冻结契约索引](../contracts/README.md)。
