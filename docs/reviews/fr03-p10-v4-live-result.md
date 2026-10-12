# FR-03 P10 v4：授权执行结果及最小恢复

本页保留第一次执行及当时待批准的恢复方案。用户随后已授权，续跑完成；
当前情况见[第二次执行结果](fr03-p10-v4-resume-result.md)。

2026-10-12。**账户预检通过；P10 在模型启动前失败。真实模型调用为0，FR-03 保持 NO_GO。**
分支 `work/fr03-unblock-20261011`，HEAD `ddfe674b3404c12134dbaa765be956527af2c439`，
本 worktree 的实现与修复尚未提交。没有采用 alpha5，没有科学重执行或资格提升。

## 实际发生了什么

用户“授权”对应此前的两阶段串行方案：一次账户预检，通过后一次 P10；失败即停。
[授权及原方案](../../../../artifacts/hosted-evidence/post-hm-fr03-01621-v4-p10-01/authorization.json)
与实际退出均已留存；原准备记录字节不变。

| 阶段 | 实际结果 |
|---|---|
| 独立账户预检 | SDK 0.162.1 初始化与1次 account/read 通过；0 thread/turn；操作约2.96秒，含监督器约16.99秒 |
| P10 前对照 | 探针退出1，stdout为空，stderr为 `hashlib.file_digest` 不存在；约0.052秒 |
| 后续 SDK、模型、后对照 | 均未启动；P10 监督器约12.26秒后退出1；没有矩阵报告或有效 socket 样本 |
| 收尾 | 两阶段均观察到实际进程退出、namespace退出及清理完成；未触发存储保护，无重试 |

直接证据：[前对照原始结果](../../../../artifacts/hosted-evidence/post-hm-fr03-01621-v4-p10-01/manager-checkpoint/before.json)、
[账户预检](../../../../artifacts/hosted-evidence/post-hm-fr03-01621-v4-p10-01/preflight/account-read-report.json)、
[P10 实际退出](../../../../artifacts/hosted-evidence/post-hm-fr03-01621-v4-p10-01/p10-supervisor-exit.json)。
本 worktree 的 `artifacts/workstreams/fr03-v4-implementation-20261011/live-failure-audit-01.json`
记录证据哈希、来源和时间。

这是我新增探针的兼容性 bug：运行时固定 `/usr/bin/python3` 是3.10.12，原测试环境是3.11.15，
只有后者提供所用的 `hashlib.file_digest`。以前的模拟测试没有覆盖这个解释器差异。
错误发生在四次 socket 创建尝试之后、输出结果之前，所以不能恢复每项的成功或 errno，
也不能据此判断 SDK 网络隔离是否正常。模型额度预留文件虽已创建，SDK 调用入口尚未到达。

## 已完成的修复

先把本次10个输入的原始字节留存到失败证据根的 `retained-inputs/`，逐项核对原准备记录哈希，
再将当前探针改为兼容3.10的分块 SHA256；socket 操作、安全判据、原失败证据不变。
新增一个在实际 `/usr/bin/python3` 中运行、在调用前替换 socket 为模拟对象的回归检查。
46个局部测试通过，格式/lint通过；没有追加真实 socket 探测、SDK或模型调用。

当前工作区的探针已修复，不能再拿它当失败时的原输入；历史输入以留存原件为准。
新准备记录是 `prepared-02/preparation.json`，保留旧 `prepared-01/`；新 spec hash：
`ada567188fa227ce84bd451187a7dd81665950e25e9450047435d8dcc6780323`。
`python310-compatibility.patch`、`pytest-v4-04.log` 与 `prepared-02/adoption.json` 位于上述本地证据目录。

## 待批准的最小续跑

具体输入、argv、哈希及采用步骤已写入本地 `resume-plan-01.json`。
只需在新的 `post-hm-fr03-01621-v4-p10-02` 证据根执行一次 P10；复用本次独立账户预检的
原报告和监督器退出记录，并保留原来源，不把采用结果重标为新执行。候选制品、预检代码和
预检依赖未变；新 P10 自身仍会做1次账户读取。启动前复核当前容量、全局 lease 及输入身份。

预算：SDK尝试900秒，前后对照各5秒，1个模型turn、0重试，256MiB持久增长、既有64MiB
scratch硬配额、1.5GiB串行内存预算。输入250000/输出4096 tokens 是事后验收阈值，
不是服务端计费硬上限。内存没有硬上限；模型重复执行探针由事后唯一性校验拒绝。
验收仍要求对照、上下文、命令完成顺序、9/9及原件复验一致；失败即停，FR-03不自动转GO。

原批准方案明确约定失败即停，本次启动尝试已经结束，因此修复后的真实重试尚待授权。
这不表示已用掉一次模型调用，也不需要重新做已通过的独立预检。
P13仍为 `NOT_EVALUATED`；P14d-C仍为 `BLOCKED_UNIMPLEMENTED`。
