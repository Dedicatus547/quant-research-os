# 发布与冻结记录

## 当前 P14 RC 文档入口

[独立 RC 复审](../reviews/p14-rc-3a4a898-independent-review.md)已对
`3a4a898f74ce2f60a14d2a69250024e92a4378c1` 给出 `APPROVE`，无阻塞项或 required fixes。
下一步记录 tag 或 release marker。

[一致性权威表述修正](p14-rc-v1-equality-correction.md)维护 principal、批准投影与原始文件 bytes 的精确范围。
该修正及[文档后继审阅](../reviews/p14-rc-documentation-successor-review.md)的原文保留；
其中待独立复审的历史状态由上述新报告更新。

当前 P14d-B/P14-DQ 资格均绑定生产实现 `e318dc4`。
修正文档不改变报告、模型、政策、runtime 或研究 outcome。

## RC 历史链

| 记录 | 提交 / 身份 | 使用方式 |
|---|---|---|
| [初始 RC core](p14-rc-v1.md) | `28876d1` | historical blocked record |
| [Append-only verification](p14-rc-v1-verification.md) | `490119c` 及后续补充 | 保留失败、formatter 中间基线与验证历程 |
| [原 final freeze](p14-rc-v1-final.md) | `9e2fc41`；实现 `e318dc4` | 原始证据；无范围限定的 byte-exact 措辞已由当前修正记录替代 |
| [文档重组与修正](p14-rc-v1-equality-correction.md) | `1e76aff`；继承 `9e2fc41` 的既有证据 | 当前一致性措辞入口 |
| [文档后继审阅](../reviews/p14-rc-documentation-successor-review.md) | 审阅 `1e76aff`，记录于 `3a4a898` | 文档修订与原文归档核对 |
| [独立 RC 复审](../reviews/p14-rc-3a4a898-independent-review.md) | 精确对象 `3a4a898`；`gpt-6-sol / high` | `APPROVE`；允许后续仅发布管理步骤 |

Blocked/failed attempts，以及已被后继报告替代的旧 P14d-B/P14-DQ 报告保持历史身份。
Retained P14c 和批准的上游 Data-qualified release 仍按各自精确绑定沿用。

## 其他阶段

- 第一阶段：[状态与 Data-qualified 汇总](../roadmap/stage-one.md)
- P13：[批准 v2 冻结](../p13-v2-freeze.md)
- P14：[当前状态](../status/p14.md)、[冻结契约](../contracts/README.md)
- [资格核验方法](../guides/qualification.md)

原始 release/review 文件保持字节身份；后继修正明确说明修正范围。
复审报告原始 SHA-256 为 `633c1a761c5d95f24186691fbe7814fa92c1b68a85963fe89bb09babf5c18ae9`。
本次登记提交记录该复审结果；独立审阅对象仍为精确 `3a4a898`。
