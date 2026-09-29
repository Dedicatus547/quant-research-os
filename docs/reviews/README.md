# 审查与批准记录

审查记录绑定特定契约、实现或历史状态。标题中的 approved/accepted
不能脱离其 hash 和作用域使用。当前资格由[状态页](../status/README.md)指向。

## P14 RC 文档后继

[文档修订审阅](p14-rc-documentation-successor-review.md)记录对 `1e76aff` 的核对、
发现与修正，以及文档后继提交 `3a4a898` 的边界。
[独立 RC 复审](p14-rc-3a4a898-independent-review.md)绑定精确
`3a4a898f74ce2f60a14d2a69250024e92a4378c1`，由 `gpt-6-sol / high`
在全新上下文执行，结论 `APPROVE`，无阻塞项或 required fixes。
复审报告原文保持字节身份；当前登记提交不自动继承为独立审阅对象。

## P14-DQ 契约与复现

| 记录 | 作用 |
|---|---|
| [Entry review](p14-dq-entry-review.md) | v1 输入、轨道与初始 acceptance gate |
| [Contract reopening](p14-dq-contract-reopening.md) | 失败证据、v2 amendment 与批准 |
| [v3 contract approval](p14-dq-v3-contract-approval.md) | 批准 engineering admissible rejection；固定 v3 bytes |
| [Principal equality conformance](p14-dq-v3-principal-equality-conformance.md) | 权威 hash 域与 raw/projection 差异修正 |
| [Negative receipt selection](p14-dq-v3-negative-case-selection-fix.md) | historical qualification conformance fix |
| [Environment approval](p14-dq-reproducibility-amendment-approval.md) | 固定 runtime fingerprint/environment 和 hash seed |
| [v3 historical acceptance](p14-dq-v3-qualification-acceptance.md) | 早期 accepted report `f7545515…f2cb53`，实现 `6573112` |

历史 acceptance 不替代当前 `e318dc4` 的 `f912cb0b…64d38a`。
契约 amendment 的继承与 superseding 关系见[契约索引](../contracts/README.md)。

## 阶段评审与入口

| 记录 | 阅读用途 |
|---|---|
| [Stage-one architecture review](stage1-review.md) | 历史架构评估；旧建议的阶段编号不替代当前路线 |
| [P11 review](p11-review.md) | post-P11 边界、比较与后续建议 |
| [P13 benchmark v2](p13-benchmark-v2-review.md) | 人工审批对照；实际资格见 [P13 freeze](../p13-v2-freeze.md) |
| [P14 entry review](p14-entry-review.md) | FR-01/FR-02 hard entry evidence |
| [P14 entry review 2](p14-entry-review2.md) | 当时的实施缺口与顺序建议 |

## 批准 policy 原件

- [P14-DQ research policy](p14-dq-proposed-research-policy.yaml)
- [P14-DQ validation policy](p14-dq-proposed-validation-policy.yaml)

这些 YAML 和部分批准记录是 runner 读取的固定 authority input，不能为整理目录而移动或改写。
本次 RC 问题及修正文档见[修正记录](../releases/p14-rc-v1-equality-correction.md)；
独立结论由[精确提交复审报告](p14-rc-3a4a898-independent-review.md)单独记录。
