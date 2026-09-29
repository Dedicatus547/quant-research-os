# 冻结契约索引

本目录提供导航，契约正文保留原路径。
Qualification runner 会读取其中部分文件的精确路径与 SHA-256；
不能通过改名、润色正文或迁移文件改变其 authority input。

## P14

| 契约 | 作用 |
|---|---|
| [P14c selection](../p14c-selection-contract.md) | preregistration、eligibility、统计方法、denominator、canonical outcomes |
| [P14d-A autonomous loop](../p14d-autonomous-loop-contract.md) | finite candidate、编排、预算、receipt、失败与 replay |
| [P14d-B qualification](../p14d-qualification-contract.md) | clean-commit 双根、canonical/negative/restart、principal 与 verifier |

契约中的 pending/blocked 状态属于写作时点；后续资格由独立报告证明。
当前绑定见[P14 状态](../status/p14.md)，不改写原 contract。

## P14-DQ amendment 链

| 顺序 | 原始文本 | 后续批准 / 使用关系 |
|---|---|---|
| v1 | [Data-qualified contract](../p14-dq-qualification-contract.md) | [entry review](../reviews/p14-dq-entry-review.md) |
| v2 | [可评价窗口 amendment](../p14-dq-qualification-contract-v2-draft.md) | [reopening 与 v2 批准](../reviews/p14-dq-contract-reopening.md) |
| v3 | [engineering acceptance amendment](../p14-dq-qualification-contract-v3-draft.md) | [v3 contract approval](../reviews/p14-dq-v3-contract-approval.md) |
| Environment | [reproducibility amendment](../p14-dq-qualification-contract-v3-reproducibility-amendment.md) | [environment approval](../reviews/p14-dq-reproducibility-amendment-approval.md) |

`draft` 文件名和原文状态保留原始身份；批准记录绑定其中的精确 bytes。
当前 runner 使用批准的 v3 与 environment amendment，不由标题自动判为尚未批准，
也不将历史 v1/v2 原规则误当作当前完整 acceptance 规则。

[RC 修正记录](../releases/p14-rc-v1-equality-correction.md)集中列出当前精确 hashes。
[历史 acceptance](../reviews/p14-dq-v3-qualification-acceptance.md)绑定早期 report，
不替代当前 `e318dc4` 报告。

## Schema 与边界记录

- [Contracts / hash / status 说明](../architecture/contracts.md)
- [P8 安全冻结](../p8-security.md)：2026-09-07 边界记录
- [P9 语义冻结](../p9-research-semantics.md)：2026-09-07 语义和 DSL admission
- [资格核验方法](../guides/qualification.md)

原始记录中指向当时“下一阶段”的段落作为历史读取。
新增修订需明确 superseding 范围与独立批准，不在旧证据上覆盖内容。
