# 审查与批准记录

审查记录绑定特定契约、实现或历史状态。标题中的 approved/accepted
不能脱离其 hash 和作用域使用。当前资格由[状态页](../status/README.md)指向。

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
它没有自动成为新的独立 APPROVE。
