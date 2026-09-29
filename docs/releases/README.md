# 发布与冻结记录

## 当前 P14 RC 文档入口

[一致性权威表述修正](p14-rc-v1-equality-correction.md)是当前 RC 措辞入口：
区分 principal、批准投影与原始文件 bytes。
文档修正已在 `1e76aff` 提交，后继[文档审阅](../reviews/p14-rc-documentation-successor-review.md)已完成；
精确后继提交待独立 RC 复审，通过后才记录 tag 或 release marker。

当前 P14d-B/P14-DQ 资格均绑定生产实现 `e318dc4`。
修正文档不改变报告、模型、政策、runtime 或研究 outcome。

## RC 历史链

| 记录 | 提交 / 身份 | 使用方式 |
|---|---|---|
| [初始 RC core](p14-rc-v1.md) | `28876d1` | historical blocked record |
| [Append-only verification](p14-rc-v1-verification.md) | `490119c` 及后续补充 | 保留失败、formatter 中间基线与验证历程 |
| [原 final freeze](p14-rc-v1-final.md) | `9e2fc41`；实现 `e318dc4` | 原始证据；无范围限定的 byte-exact 措辞已由当前修正记录替代 |
| [文档重组与修正](p14-rc-v1-equality-correction.md) | `1e76aff`；继承 `9e2fc41` 的既有证据 | 当前一致性措辞入口 |
| [文档后继审阅](../reviews/p14-rc-documentation-successor-review.md) | 审阅 `1e76aff`，记录于仅文档后继提交 | 待精确后继提交独立 RC 复审 |

Blocked/failed attempts，以及已被后继报告替代的旧 P14d-B/P14-DQ 报告保持历史身份。
Retained P14c 和批准的上游 Data-qualified release 仍按各自精确绑定沿用。

## 其他阶段

- 第一阶段：[状态与 Data-qualified 汇总](../roadmap/stage-one.md)
- P13：[批准 v2 冻结](../p13-v2-freeze.md)
- P14：[当前状态](../status/p14.md)、[冻结契约](../contracts/README.md)
- [资格核验方法](../guides/qualification.md)

原始 release/review 文件保持字节身份；后继修正明确说明修正范围。
