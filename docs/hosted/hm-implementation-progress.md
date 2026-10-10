# HM-MVP 交付进度

更新：2026-10-10（Asia/Singapore）。**有界 Codex-hosted MVP（component-v2）已完成**。
当前状态：`ACCEPTED_COMPONENT_V2_ENGINEERING / LOCAL_RELEASE_REGISTERED`。

## 交付结果

| 环节 | 结果与入口 |
|---|---|
| 实施与真实运行 | 固定 C15 完成实际模型提案交接、campaign 终态、离线 export 与 replay |
| 工程核验 | 候选五项原谓词 PASS；旧 C11 证明按限定组件范围复用；[来源采用说明](hm-component-adoption-v2.md) |
| HM09 | fresh `gpt-6.1-sol/high` 独立复审，`ACCEPT_COMPONENT_V2`，无阻塞项；[复审报告](../reviews/hm09-component-v2-final-review.md) |
| HM10 | `gpt-6-luna/medium` 完成[快速上手](hm-mvp-quickstart.md)、[故障恢复](hm-mvp-recovery.md)和[状态页](../status/hosted.md) |
| HM11 | 精确源码、接受及文档身份已登记；[发布标记](../releases/hm-mvp-component-v2-freeze-marker.md) |

工程接受限于版本化 component-v2 组合范围。旧 PASS 保持原 tuple，
当前候选 selected verifier 的七项 `NOT_EVALUATED` 保留；未声明 C15 v1 全12门重新通过。
两项科学执行均为 `SOFT_REJECT`，原 ValidationReport 均为 `SUCCEEDED / REJECT`。

## 当前运行状态

固定 CLI `0.162.1`、请求 `gpt-6.1-sol/high` 的路线已完成两份实际 proposal capture。
provider model identity 未暴露，HTTP 请求数为 `UNKNOWN`。
campaign 已 `COMPLETED`，服务及 namespace 已清理；正式额度8/8、诊断2次、
业务 CLI合计10/10，余额0。后续运行需要新的授权与额度，按操作文档办理。

## 已复用的工作

- 原 C15 源码冻结与 B/D/I、实际 live/export/replay 工件。
- 原 C11 CI1909、106项矩阵、原七门/native 和约4.79GB sealed bundle。
- verify02 保存的 Q01/Q07/Q09/Q10 canonical PASS；其 -15 空间失败原件保留。
  continuation01 仅续做 Q11 原谓词及原收尾，实际退出0并完成清理。

首次候选 view 未保存 gate 结论，无法复用未落盘的结果，因而必要的原谓词核对有明确来源记录。
HM10/HM11 未新增测试、开发门禁、重流程、业务模型调用或科学执行。
FR-03 SDK、P14d-C 及既有 P14 轨道沿用各自原状态。

## 历史追溯

完整[原文归档](hm-implementation-history-2026-10-10.md)保留整理前原字节：
446928B，SHA256 `b1ffa94768882e8fd6a344f7aec0cf8af0fea8ecb886a47925de0f40fc8a8da7`。
归档与原入口同目录，原相对链接保持适用。
完整记录中的“当前”“尚待”和 `NOT_QUALIFIED` 均按对应阶段解释。
科学原件、失败记录、接受 JSON、冻结契约和发布身份未因文档整理而修改。
