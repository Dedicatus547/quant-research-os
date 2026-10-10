# HM-MVP component-v2 快速上手

## 当前已接受范围

从不可变接受记录和独立复审报告开始只读查阅：

- [HM09 component-v2 接受记录](../../artifacts/hosted-evidence/recovery-continue01/hm09-component-v2-acceptance-01.json)，SHA-256 `e31361d38f324db11cb5dec759bd3ad7079745a824fff1998d8763c4886727ec`。
- [HM09 独立最终复审](../reviews/hm09-component-v2-final-review.md)，SHA-256 `ba4557868c2d1f98fc87a19564d666e85ca9673b3c0266327c66d881237f7a33`。
- [本次执行摘要](../../artifacts/hosted-evidence/recovery-continue01/hosted-canonical-live-completion-summary-01.json)，包含真实 live 终态的有限摘要。

接受范围为 C15 (`a47e5a95db15f51e748c1343d96e124fc5b04d8c`) 及其绑定的 B、D、I，接受结论是 `ACCEPT_COMPONENT_V2`。两份原 ValidationReport 均为 `SUCCEEDED / REJECT`，对应两次真实执行结果均为 `SOFT_REJECT`。这不是 C15 v1 全 Q01–Q12 PASS，也不构成盈利、alpha、策略选择、投资适用性或 vendor-vintage PIT 证明。Q08 只覆盖 47 项来源链及当前 inventory；C11 原 Q02/Q03/Q04/Q05/Q06/Q12 证明按原 tuple 复用。详情以接受记录为准。

## 当前 campaign 的操作状态

当前 campaign 已 `COMPLETED`，正式模型调用 8/8、独立诊断 2 次、全部业务 CLI 额度 10/10 已耗尽；provider model identity 未暴露，HTTP 请求数为 `UNKNOWN`。没有剩余额度，不自动重试、重新签发请求或重置 TTL。服务与 namespace 已完成清理，服务不保证仍在运行。

因此当前步骤是阅读上述记录和保留原件；不要用 `start`、`resume` 或其他命令重启这个已耗尽 campaign。能力只通过私有继承 FD 提供；操作时仅传 FD 整数，绝不读取、复制、打印或记录 capability bytes。

## 后续新请求的 CLI 模板

[HM05 CLI 操作说明](hm05-cli-operations.md)列出 `start`、`pending`、`request-export`、`submit`、`resume`、`status`、`cancel` 七个命令示例。那些示例只适用于受限服务已经运行、管理侧已注册不可变 spec 和冻结输入、并且存在新授权的 spec/campaign 与未耗尽预算时；它们是模板，不是当前执行命令或本次接受范围的重放授权。所有身份都应使用显式哈希，不使用 `latest`、`current` 或 `auto`。

## 阅读路径

- [故障恢复与空间边界](hm-mvp-recovery.md)
- [HM 存储恢复记录](hm-storage-recovery.md)
- [Windows WSL VHD 维护说明](hm-windows-vhd-maintenance.md)
- [HM-MVP 发布 marker](../releases/hm-mvp-component-v2-freeze-marker.md)（发布登记以独立 marker 为准；本文不授予或执行发布）
