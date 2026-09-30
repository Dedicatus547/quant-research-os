# HM Q01/Q07 原始来源诊断：attempt06

日期：2026-09-30。状态：`DIAGNOSTIC_ONLY / NOT_QUALIFIED`。
本记录属于 HM-07 实施验证，不是 HM-09 接受记录或 HM-10 发布说明。

服务安装绑定提交 `9ae5537dcb06cb2f9c6cd1caf85b8b65fa9f8022`；诊断 verifier
及管理端快照驱动来自此后未发布的工作区差异。不能据本记录给当前工作区或该提交授予完整资格。

| 工件 | 精确身份 |
|---|---|
| 冻结业务输入 B | `58d4d17fbd70efd23ff19c8022a88cd46383bc81eea2262329a26ff5e9a9c444` |
| 部署 D | `b9ff7d3c0986f9e7111cc739dcf5330907a5d3f6dd5b69f3e26835300311db9a` |
| 原始管理端根 | `/tmp/hm-stage-9ae5537-attempt06` |
| 最后一次诊断目录 | `/tmp/hm-q01-q07-9ae5537-attempt06-reverified-pending-summary` |
| 该诊断 manifest SHA-256 | `87e697043cfc5c49ecf244c079c32a0a5ecda01e87be684732b1a439ebef66ea` |
| Q07 窄边界独立审查 | [attempt06 review](../reviews/hm-q07-attempt06-review.md) |

Q01 用实际服务启动、终止和新进程启动执行。重启后 pending/status/resume 各查询两次。
管理端保存查询前后完整 authority 快照，verifier 校验两份 raw inventory 相同，并从协议
authority 核对完整请求、reservation、checkpoint、初始研究预算及查询返回值。一个 request
reservation、零 unique submissions、零 trial/execution；没有重新签发请求。

公共 `pending` CLI 返回身份摘要，完整请求仍来自保存的 canonical protocol bytes。
Q01 校验摘要的 request hash、campaign 和到期时刻以及重复摘要一致性，不把摘要当作完整 envelope。
协议预发布的固定 exhaustion receipts 不代表收到响应，也不产生 submission 消耗。

Q07 由实际受限宿主运行。文件写入、sealed/管理端/服务私有 FD 读取、ptrace、父进程内存、
pidfd-getfd 及 channel 替换尝试均拒绝；128 次 fork 并发替换均返回 EXDEV。
EXDEV 单独证明跨文件系统替换拒绝；只读 channel 另由 EROFS、只读挂载查询、入口拒绝及
服务身份观测共同核验。管理端通过 bubblewrap info FD 获取实际进程链，再读取真实
子进程的命令、执行文件 hash、namespace 和 credentials，与冻结安装及 bootstrap 对照。
服务网络隔离另有实际管理端连接正对照。

导出包含完整 authority inventory 及原始观测字节。独立提供的原始管理端目录与
`HostedManagerExport` 逐文件核对 bundle 路径、原路径、hash 和长度；copied transcript 或
`TRUSTED` 字符串不建立来源信任。原始管理端目录的可信选择是调用者的明确前提。

首两次 verifier 诊断的 Q01 FAIL 均保留，目录分别为
`/tmp/hm-q01-q07-9ae5537-attempt06` 和其 `-reverified` 副本。两份 manifest hash 相同：
`3d91f6c15a17edd0227857aa32119a5d36734bfefa44da55321560dd4e4cc49d`。
原因是新增 verifier 误要求没有预发布 exhaustion receipts，随后又误把 CLI 摘要解析为完整请求。
修正谓词后另建上述最后一次诊断目录，未覆盖初次失败结果或原始运行证据。

最后一次诊断 Q01/Q07 为 PASS；Q02–Q06、Q08–Q12 为 NOT_EVALUATED，整体 NOT_QUALIFIED。
本次没有读取模型 auth、没有调用模型，也没有执行研究候选。不能替代真实 Q11、Q09 receipt
reuse、Q10 两个 native 新根、覆盖率门槛、完整 Q 矩阵、HM-09 或发布工件核对。

实施遵循用户更新后的分配：普通实施由当前主代理执行；必要独立审查使用
`gpt-6.1-sol / high`。本轮包含一次实际部署 probe、一次实际重启诊断及三次 verifier
计算。模型 usage unavailable，不据耗时推算 tokens 或费用。
