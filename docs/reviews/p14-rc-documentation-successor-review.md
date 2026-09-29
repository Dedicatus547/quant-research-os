# P14 RC 文档后继提交审阅

日期：2026-09-29。状态：**文档审阅与修订完成，精确后继提交待独立 RC 复审**。

本记录完成 PLAN 的“审阅本次文档修订，形成仅包含文档的后继提交”。
审阅基线为 `1e76aff09b03c4cda2d821c2f7b09257659151da`。
审阅者为执行该任务的 Codex；独立 RC 复审仍是下一项工作。
本记录及所列修订由其所在的仅文档 Git 提交绑定。

## 发现与修正

| 发现 | 后继修正 |
|---|---|
| 发布索引和一致性修正页仍称“未创建 commit”，与 `1e76aff` 已存在不符 | 明确文档重组提交身份，记录审阅完成和精确后继提交待独立 RC 复审 |
| DQ tree inventory 说明只提 `created_at`，未写明 `root-evidence.json` 排除项 | 与冻结 runner 对齐：排除各根 `root-evidence.json`，仅对带顶层 `created_at` 的 JSON 对象投影，其他文件保持原始字节 |
| PLAN 的下一项仍为本次正在完成的文档审阅 | 下一项推进为对精确后继提交独立 RC 复审，发布标记继续以通过为前提 |

同步修正发布入口、README、状态页、哈希域说明与资格指南。
原始契约、批准 policy、release/review 记录及历史归档沿用其原始字节。

## 文档与 Git 完整性核对

核对方法为本地只读文件检查、Git 对比，以及现有 contracts 的 JSON 解析与内容哈希校验。

| 范围 | 核对结果 |
|---|---|
| 原文归档 | Inventory 的 50 个文件逐一与 `9e2fc41a41f2d2b253e04c67b10519e6926c79dd` 原文比较，bytes、size、SHA-256 一致 |
| 保留原位的原始文档与批准记录 | 32 个文件与 `9e2fc41` 一致，包含冻结契约、批准 YAML 与旧 release/review 记录 |
| 非文档已跟踪文件 | 591 个文件逐一与生产实现 `e318dc450e5c02f1120da7644250767bf682b6f9` 比较，一致 |
| 活跃文档链接 | 重组与本次后继涉及的 Markdown 页面相对文件链接有效；归档原文按原提交解释 |
| 提交边界 | 后继差异仅为根 README、PLAN 与 `docs/` 下 Markdown；`git diff --check` 通过 |

归档依据见[历史清单](../history/2026-09-29/inventory.json)。
链接检查包含授权工作区内的两处上游 release report 链接；新克隆仍可能缺少 `artifacts/`。

## 资格报告与原始文件清单

使用现有 `P14dQualificationReport`、`P14dqQualificationReport` 解析保留报告，
核对 canonical bytes、内容身份、principal summary、实现、lock 与所列文件的原始 bytes。
清单包含下表全部文件，报告自身由单独的内容哈希和原始 SHA-256 绑定。

| 保留 bundle | 报告内容身份 | 清单文件数 | 每根文件数 | 双根原始差异 |
|---|---|---|---|---|
| P14d-B | `41a27c6f…fadc71` | 1848 | 922 | 50 个 manifest 仅顶层 `created_at` 不同，另有 1 个 root-evidence identity 差异 |
| P14-DQ | `f912cb0b…64d38a` | 1054 | 519 | 68 个 manifest 仅顶层 `created_at` 不同，另有 1 个 root-evidence identity 差异 |

```text
P14d-B report raw SHA-256
34ecdcbc3cdc92398bc6de85d586bdf08c643db5cfd6be59d9ea894bed7d5fa3
P14-DQ report raw SHA-256
7dceffb8d8563d82e94d3bb31b5aefea3bc8d55f36f2344280681dd8568b974d
P14-DQ projected tree inventory（两根相同）
d459a2d9d1e5d6995647521f9ac9ad698a078fa5fab01f40cf28de6c479d1be2
```

按冻结 runner 的 `_inventory_projection` 与 `_tree_inventory_hash` 规则复核 DQ 投影，
其结果与两根报告中的 `artifact_tree_hash` 相等。
Principal 比较沿用现有 contract 的字段域；完整原始树的逐字节一致性声明不成立。
规则入口见[一致性修正](../releases/p14-rc-v1-equality-correction.md)和
[principal-equality conformance](p14-dq-v3-principal-equality-conformance.md)。

同时核对批准 v3 contract 与 runtime amendment 的原始文件哈希，以及报告中的
runtime fingerprint/environment 和 external-bindings 身份。
DQ 的两根证据均记录自然研究 `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`、
零个合格候选、未执行选择、sealed authority 为 false。
每根两个候选均为 `SUCCEEDED / REJECT`、`SOFT_REJECT`，唯一拒绝 gate 为
`G5_OUT_OF_SAMPLE / SOFT_THRESHOLD_NOT_MET`，其余 G0–G10 为 PASS。

## 验证范围与下一项

本次核对保留报告、bundle 原始文件和文档声明；未执行 Qlib 双根重建、
重新核验实际外部 snapshot/view 数据或重跑软件回归，不产生新的工程资格。
既有 full verifier 与回归证据仍归属于[原冻结记录](../releases/p14-rc-v1-final.md)
和[追加验证记录](../releases/p14-rc-v1-verification.md)。

独立 RC 复审需绑定本记录所在后继提交的完整 Git SHA，并核对发布入口和权威矩阵。
复审通过后才记录 RC tag 或 release marker，冻结 P14 主线。
生产实现继续绑定 `e318dc4`；Live Agent、sealed、alpha/盈利、投资适用性、
vendor-vintage PIT 与 unrestricted autonomy 的边界沿用[当前修正记录](../releases/p14-rc-v1-equality-correction.md)。
