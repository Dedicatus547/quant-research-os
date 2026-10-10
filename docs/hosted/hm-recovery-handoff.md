# HM-MVP 新会话交接

更新：2026-10-10（Asia/Singapore）。**MVP 实施与 HM09→HM10→HM11 交接已完成**，
当前范围为 `ACCEPTED_COMPONENT_V2_ENGINEERING / FROZEN`。
正式 tag `hm-mvp-component-v2` → `59c25ac`；原接受 C15 保留在 Git 历史中。

## 先读这些入口

1. [发布标记](../releases/hm-mvp-component-v2-freeze-marker.md)：接受对象、精确身份及资格边界。
2. [快速上手](hm-mvp-quickstart.md)和[故障恢复](hm-mvp-recovery.md)：使用与恢复约束。
3. [交付进度](hm-implementation-progress.md)和[组件采用说明](hm-component-adoption-v2.md)：结果与复用范围。
4. [仓库规则](../../AGENTS.md)。
5. [后续实施与恢复约定](../guides/implementation-discipline.md)及[本次实施复盘](hm-mvp-implementation-retrospective.md)。

## 必要上下文

- 接受源码是既有 C15 capsule，commit `a47e5a95db15f51e748c1343d96e124fc5b04d8c`。
  主工作区的未提交改动不能被宣称为已接受源码。
- HM09 独立接受无阻塞项；三份 HM10 文档与 HM11 本地发布登记已完成。
  接受、发布及文档哈希集中记录在发布标记，无待完成的同轮验收。
- CLI `0.162.1`、请求 `gpt-6.1-sol/high` 已完成两次实际提案采集。
  provider model identity 未暴露、HTTP 请求数为 `UNKNOWN`。
- campaign 已 `COMPLETED`，服务与 namespace 已清理。正式额度8/8、诊断2次、
  业务 CLI合计10/10余额0；后续运行需要新的授权和额度。
- 两项科学执行均 `SOFT_REJECT`，原 ValidationReport 均 `SUCCEEDED / REJECT`。
  工程接受不赋予 alpha、盈利、投资适用性、sealed 或历史 vendor-vintage PIT 资格。
- FR-03 SDK 仍 `NO_GO / THIN_MAINTENANCE`，P14d-C 仍 `BLOCKED_UNIMPLEMENTED`；
  其他 P14/ScriptedReplay 轨道保持原身份。

## 后续工作原则

已完成且身份可核对的冻结、CI、矩阵、native、sealed bundle、live/export/replay
和 checkpoint 必须复用。无法复用时说明缺失的身份、字节或绑定，保留原失败。
不得续发耗尽 campaign、自动重试、reissue 或重置 TTL。

恢复沿用原空间监管：Linux16GiB、宿主卷32GiB余量及512MiB private tmp；
按完整作业增量预估，不删除证据腾空间。维护方法见[存储恢复记录](hm-storage-recovery.md)
和[Windows VHD 维护](hm-windows-vhd-maintenance.md)。

后续扩展由具体需求启动。历史方案中的模型分工、旧 pending 和准备命令，
不构成新任务或运行授权；避免增加非必要开发门禁、测试和重流程。

## 历史追溯

完整[原文归档](hm-recovery-history-2026-10-10.md)保留整理前原字节：
188862B，SHA256 `5c07287014599044d893614d2aee0658766c07666f0ba6b6a50251570852b0ef`。
归档与原入口同目录，原相对链接保持适用。
该历史保留原失败、过期、待定和每阶段授权表述。其 HM09–HM11 待完成状态已由当前发布登记更新。
不可取得的01–36轮历史原件仍不可用，不依据文档摘要重建。
