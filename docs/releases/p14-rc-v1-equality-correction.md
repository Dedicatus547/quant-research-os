# P14 RC v1：一致性权威表述修正

日期：2026-09-29。状态：**文档修正完成，后继提交待独立复审**。

本记录修正提交 `9e2fc41a41f2d2b253e04c67b10519e6926c79dd` 中的 RC 一致性措辞。
原冻结记录、资格报告和失败尝试保持原始证据身份。本次修订未创建提交或 tag。

## 修正内容

原文 [p14-rc-v1-final.md](p14-rc-v1-final.md) 将 P14d-B independent roots、
P14-DQ artifact trees 无范围限定地称为 byte-exact。正确表述如下：

| 范围 | 精确结论 |
|---|---|
| P14d-B 确定性 principal evidence | 在契约定义的权威哈希域内逐字节一致 |
| P14d-B 原始文件树 | 50 个 manifest 仅顶层 `created_at` 不同；完整原始树不逐字节一致 |
| P14-DQ 确定性 principal evidence | 在批准的权威哈希域内逐字节一致 |
| P14-DQ artifact-tree inventory | 按批准规则排除 JSON 顶层 `created_at` 后的投影一致；两根 inventory hash 相同 |
| P14-DQ 原始文件树 | 68 个 manifest 仅顶层 `created_at` 不同；完整原始树不逐字节一致 |
| 各根原始字节 | 分别由 qualification report 的精确文件集合、size 与 SHA-256 清单绑定 |

`root-evidence.json` 的 root identity 也按各根分别记录；上表的 50/68 数量只统计 manifest 差异。
此修正没有新增忽略字段、放宽浮点比较或改变 verifier。
现有投影规则见[principal-equality conformance 记录](../reviews/p14-dq-v3-principal-equality-conformance.md)。

本记录是当前一致性表述入口。原文中的无范围限定措辞作为历史记录读取。

## 沿用的精确资格绑定

| 对象 | 实现提交 | 报告内容哈希（`qualification_hash`） |
|---|---|---|
| P14c retained | `618498a64b8e46ab5c38f66ea08a03a2afdaea32` | `d0412a30d27c4d793fe527a28432292f1616a4ad726830d3cb1ce24a5836913a` |
| P14d-B | `e318dc450e5c02f1120da7644250767bf682b6f9` | `41a27c6fd2b5f0f522a1fcae13424b924b9cdc2fa4e8aa0df24ff12d79fadc71` |
| P14-DQ | `e318dc450e5c02f1120da7644250767bf682b6f9` | `f912cb0b376c981c94dae267cb0b16a4d2f1e0a52edcd36d08f938f92964d38a` |

表中的报告内容哈希排除自身 `qualification_hash` 字段；不是报告文件的原始字节 SHA-256。
下列绑定同时包含原始文件哈希与 contract 内容哈希，分别按 lock/contract 文件、
RuntimeFingerprint、snapshot/view manifest、release report 和 principal summary 的具体域核验。

```text
Lockfile             0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca
Runtime fingerprint  66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321
Snapshot             6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9
Qlib view            fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b
Upstream release     6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca
External bindings    cdc3f98383b422f3adbb018894749e4488d2058dcc11d6e1fe40cb46c3f281c3
Approved v3 contract 563b1c44ff8e3b87822902c1f70183de2ddd97b007550f2028990bb37f858e17
Runtime amendment    a63058df2df0a89c054965fb33046d99dc0851624bd231b45a2446709539dbce
P14d-B summary       db5c8a0dfe0672fb5c326971d44bd9e8d29c720bb998c281c42c1b0ada96ab64
P14-DQ root summary  affa9baefe5880b1bc54886e1c48688a4be5fcb92f41fd699a74326ef1abaf9b
P14-DQ report summary 4bfb5d37b380e9da08f205b8a23b213596b97d1f17b9185983922e97a1fbb64b
```

P14-DQ runtime-environment schema 为 `p14dq-runtime-environment/v1`：
`PYTHONHASHSEED=0`，hash randomization disabled，并绑定上述指纹与批准 amendment。

## 工程、研究和复现边界

P14d-B 的 synthetic SELECTED 用例不授予 real-market selection 或 sealed confirmation 资格。

P14-DQ 自然研究结果继续为 `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`：
`eligible_candidate_count=0`、`selection_performed=false`。两个候选均为
ValidationReport `SUCCEEDED / REJECT`、TrialOutcome `SOFT_REJECT`，
经批准的 `G5_OUT_OF_SAMPLE / SOFT_THRESHOLD_NOT_MET` 路径拒绝。

`e318dc4` 的 Qlib 修复仅负责 `model.fit → drain async queue → clear stopped queue →
SignalRecord.generate` 生命周期。`QLIB_EXECUTION_FAILED` 仍为执行失败。
它没有修复 Position set-order 末位浮点敏感性，也不声明任意 hash seed 下确定性。

## 沿用的权威矩阵

| 权威域 | 状态 |
|---|---|
| P14 deterministic autonomous Offline Engineering | `QUALIFIED` |
| P14 deterministic autonomous Data-qualified Engineering | `QUALIFIED`，仅精确冻结范围 |
| P14a / P14b / P14c | `QUALIFIED` / `COMPLETE`（有限家族）/ `QUALIFIED` |
| P14d-B | `QUALIFIED`，仅精确 `e318dc4` 实现 |
| P14-DQ 自然研究 | `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE` |
| P14-DQ 工程 | `SUCCEEDED / PASS` |
| Live Agent | `NOT QUALIFIED / BLOCKED` |
| FR-03 / P14d-C | `NO_GO / THIN_MAINTENANCE` / `BLOCKED_UNIMPLEMENTED` |
| Sealed confirmation | `NOT QUALIFIED` |
| Alpha / profitability / investment suitability | `NOT CLAIMED` |
| Vendor-vintage PIT / unrestricted autonomous research | `NOT QUALIFIED` |

工程 PASS 不转换为研究 PASS、已选择 alpha、盈利或投资适用性结果。

## 证据和发布步骤

之前独立审查的结论为 `APPROVE_WITH_REQUIRED_FIXES`。它核对了 Git 边界、绑定报告、
文件清单、原始差异、完整 verifier 的保留 PASS 日志，并运行 retained P14c、
bundle integrity、外部输入与静态检查。完整回归证据仍见[原冻结记录](p14-rc-v1-final.md)
及[append-only verification](p14-rc-v1-verification.md)，这些是既有实现的证据。

本次文档修订没有重跑完整 Qlib qualification，也不将 bundle-only 核验称为 bottom-up rebuild。

下一步：形成本次文档的后继提交，对精确提交独立复审；通过后才记录 RC tag / release marker。
历史 blocked 提交 `28876d1415681ee98817c84aa16b1e68e01af6b0`、
`490119cff1ebe8ffe2b698854fbe500f85c42c0a`、formatter 基线
`ea2573ffd1d72e3f1f28390550e174338d88dda9` 和 `9e2fc41` 均保留。
