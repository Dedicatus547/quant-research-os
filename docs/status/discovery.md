# Discovery 当前状态

更新：2026-10-12。两轮有界探索性研究及后继实现已完成，源码已合入本地 main。
按第二轮冻结规则，当前建议是**暂停扩大当前受限空间的同类 LLM 生成**。

## 研究结果

| 口径 | 首轮 | 第二轮 |
|---|---|---|
| 生成机会 | 15，三方法各 5 | 15，三方法各 5 |
| 不同候选结构 | 10 | 12 |
| 预测可比较情况 | 5 项通过当轮准入；LLM 无可分析预测 | 后继统计接口准入 9 项，缺源 3 项，共同日期 708 天 |
| 原科学裁决 | 5 `SOFT_REJECT`、5 `EXECUTION_FAILED` | 6 `SOFT_REJECT`、6 `EXECUTION_FAILED`；其中 8 个历史来源只读采用、4 个新任务执行 |
| 策略 Validation PASS | 0 | 0 |
| LLM 相对最佳基线 | 无法估计预测增量 | 共同日最高 Rank IC 均值增量为 0，低于事前 0.002 门槛 |

两轮预测准入口径不同，不能直接据此比较方法优越性。
第二轮统计可比不改写原执行失败或策略裁决；两轮均为回顾性探索，没有独立确认或 Registry 晋级。
完整数值、成本、原件与限制分别见[首轮报告](../roadmap/post-hm-mvp-discovery-report.md)和
[第二轮科学报告](../roadmap/post-hm-next-scientific-report.md)。

## 实现与检查

D01–D07、D09、D10/A、D10/B 已完成；顺序生成历史、恢复与冻结、覆盖基线、完整机会计数、
独立科学预算和预测证据接口已交付。D08 / N4b 窄执行路径因成本依据不足而暂缓。
实现与阶段材料见[实施记录入口](../roadmap/post-hm-mvp-implementation.md)及[文档索引](../roadmap/README.md)。

[合并审核](../reviews/two-worktrees-merge-20261012.md)记录 245 项定向离线测试、Ruff、格式和 strict Pyright 通过。
未重跑合并后的全量 CI 或覆盖率；历史科学来源和工程接受继续按原提交解释。

## 后续边界

第二轮五次 LLM 调用额度已耗尽；已完成工作无需继续生成或重跑。
若提出下一轮，先明确新的研究理由、比较设计及预算，按[路线图](../../PLAN.md)决定范围。
金额费用、provider 内部调用及实际模型身份的未知项继续保留，不能据耗时宣称成本优势。

SDK discovery/campaign 生成入口仍未资格化；本研究采用的 Hosted 路线与
[FR-03 确切组合 GO](fr03.md)具有各自的接受范围。

2026-10-12 新切片：B0/B1 的 `bounded-price-composition/v1` 离线实现与准备已完成，
见[设计、示例和 B2 最小请求](../roadmap/bounded-price-composition-offline.md)。
它是新的回顾性研究空间；尚未生成真实模型响应或科学评价，不改变上述两轮结论。
A0 的有界 SDK campaign 接入仍不放开 SDK Discovery capture；P14d-C 和新组合资格未授予。

2026-10-13：B2本次授权的单LLM3补跑与报告收尾完成，科学结果为SOFT_REJECT；
预测报告6项可分析、720共同日，LLM相对最佳基线无正增量。A1 V4后继r10两步工程闭环完成，个体科学均SOFT_REJECT、科学汇总FAILED/NOT_EVALUATED；累计SDK11/11、科学5/90。原r9失败按原身份保留。B2不因A1重跑，见
[A1/B2 当前准备状态](a1-b2-authorized-preparation.md)。
