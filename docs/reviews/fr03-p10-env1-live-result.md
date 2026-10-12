# FR-03 v4-env1 真实 P10 结果

2026-10-12（Asia/Singapore）。**一次真实 P10 完成，9/9 通过；FR-03 总体仍为 NO_GO。**
SDK 和 runtime 保持 0.162.1，没有使用 alpha5。原 v4 的 7/9 失败报告保留不变。
本次只执行用户授权的新测试，没有执行科学作业或变更整体资格。

## 实际观察

| 检查 | 结果 |
| --- | --- |
| 网络探针环境 | 沙箱内与管理侧前后对照的完整环境、目录、用户、解释器哈希一致 |
| 管理侧前后对照 | 两轮各四种 IP socket 均创建成功 |
| 沙箱内网络探针 | IPv4/IPv6 的 TCP/UDP 四项创建均明确返回 EPERM（不允许操作） |
| 写入、秘密与恢复 | 写入被拒绝；秘密标记未泄露；拒绝后恢复命令正常完成 |
| 生命周期 | 六条命令的开始、结束逐一匹配，完成顺序满足原严格要求 |
| 整体 P10 矩阵 | FAILURE_RECOVERY、MCP、PERMISSION_DENIAL、PROPOSAL_BOUNDARY、SANDBOX、SKILLS、THREAD、TRANSCRIPT、USAGE 全部通过 |

上次 v4 的 PATH 不一致在本次已消除。网络探针统一建立环境，判分仍要求实际上下文完全相同；
四项 EPERM、前后对照和 9/9 标准没有放宽。执行器、SDK adapter、normalizer 和判分源码不变。
这是修正测试环境后获得的直接证据，不是 SDK 修复证明，也不能倒推早先 DNS 失败的唯一原因。
证明范围为本次固定输入和运行组合下的四种 IP socket 创建；不扩展为所有网络通道均已验证。
SDK 事件投影无法确认的内层调度字段仍为 UNKNOWN。

## 执行与成本

- 一次模型 turn，零重试；SDK 段约 60.7 秒，整个启动器约 73.8 秒。
- 记录用量：输入 18,050 token（其中缓存输入 17,664），输出 109；未据此估算账单。
- 复用已验证的独立账户预检；未新增独立预检调用。P10 内部按固定执行路径调用一次 account/read。
- 守护进程实际退出码 0，waitpid、命名空间退出和清理均已确认；共享租约已释放。
- 沿用 256 MiB 持久增长预算、64 MiB scratch 硬限与 1.5 GiB 串行内存预算。
  新结果目录在追加审计前为 42 个普通文件、230,568 字节逻辑大小；这不包含共享守护记录。

## 可核对证据

- [真实结果摘要](/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-fr03-01621-v4-env1-p10-01/p10-v4-result.json)
- [不可变 P10 报告](/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-fr03-01621-v4-env1-p10-01/bundles/sha256-4296daed6f06a0b01374cd9fbabb99c6dbef98b051944a50af2dc9ea694380d3/harness-spike-report.json)
- [本次审计](../../artifacts/workstreams/fr03-environment-fix-20261012/live-audit-01.json)：原始四项观察、对照、事件行号、用量、资源及证据 SHA256。
- [后继交接状态](../../artifacts/workstreams/fr03-environment-fix-20261012/status-live.json)
- [上次真实失败](fr03-p10-v4-resume-result.md)与[环境修正及离线验证](fr03-p10-environment-fix.md)

报告内容哈希为 `4296daed6f06a0b01374cd9fbabb99c6dbef98b051944a50af2dc9ea694380d3`；
报告文件 SHA256 为 `eb21235e5853e0d3b419b2b6da089d82cc3b9c2e56b1765858be9854c9cf97dc`。
两者算法范围不同。管理回执哈希为 `3d24d591eb1e84c3903d7c3f04c3abef7c8b9c8714cda6573c7414129f5c3be7`。
输入已在启动前逐字节留存，导出和复验由本次执行器完成；收尾未重复运行模型或全套复验。

报告中的 GO 仅属于这份新输入的 P10 矩阵。FR-03 总体 NO_GO 不变；
P13、P14d-C 和总体资格审查未在本次执行，原交接中的对应状态未被本结果改写。
工作分支仍为 `work/fr03-unblock-20261011`，HEAD 为 `ddfe674b3404c12134dbaa765be956527af2c439`；
改动未提交，原 main 源码和其他 worktree 未修改。
