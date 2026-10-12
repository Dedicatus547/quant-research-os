# FR-03 P10 v4 后继实施交付

后续状态：兼容性修复后的授权续跑已完成；内层四项 socket 均返回 EPERM，但 PATH 与
对照组不一致，v4正式结果仍为7/9。见[续跑结果](fr03-p10-v4-resume-result.md)；
[首次执行记录](fr03-p10-v4-live-result.md)保留模型启动前的失败与修复。
以下保留授权前的实施与预算说明，不代表当前尚未获得过授权。

2026-10-12，分支 `work/fr03-unblock-20261011`，基线 HEAD
`ddfe674b3404c12134dbaa765be956527af2c439`。变更尚未提交。
承接[测试设计审查](fr03-p10-network-probe-design-review.md)及用户“按照后继方案继续”的实施授权。

**工程实现及局部离线验证已完成，真实执行未获新额度、未启动。**
FR-03 保持 `NO_GO / THIN_MAINTENANCE`；旧 0.162.1 P10 保持 7/9；
P13 `NOT_EVALUATED`，P14d-C `BLOCKED_UNIMPLEMENTED`。
新代码和合成测试不授资格，也不证明 SDK 曾存在或已经修复网络隔离 bug。

## 已实施

- [独立 v4 fixture](../../tests/fixtures/p10_codex_workspace_v4/task.md)：要求按顺序执行、保留
  实际结果，不再要求模型必须得到某句错误文字。SDK/runtime 保持 0.162.1；canonical 仍为
  0.154.0，没有下载或采用 alpha5。
- [socket 探针](../../tests/fixtures/p10_codex_workspace_v4/network_probe.py)：仅创建并关闭
  IPv4/IPv6 × STREAM/DGRAM 四种 socket；不做 DNS、connect、bind、listen、send。
  记录数字 errno、实际 UID/cwd/解释器 hash 和三项受控环境值。四项创建成功退出0，
  四项 EPERM 退出1，混合或其他错误退出2；导入、关闭和输出异常保留为程序故障。
- [新契约](../../src/quantos/contracts/p10_v4.py)和
  [v4 判分](../../src/quantos/application/p10_v4.py)：严格检查四项集合、字段类型、规范 JSON、
  退出码、前后对照和相同执行上下文。两次对照必须成功；内层四项必须 EPERM。
  完成顺序为 `secret.end < write.start < write.end < network.start < network.end < recovery.start`。
  九项全过的分母不变；同一函数生成观察记录和判分依据。
- [管理入口与复验](../../src/quantos/application/p10_v4_runner.py)：管理侧在同一外层环境，
  于 SDK 尝试前后运行对照，单条至多5秒、stdout+stderr合计4096 bytes。
  前对照失败则不启动 SDK；模型尝试完成后先保存事件和真实结果，再做后对照。
  失败 checkpoint 不覆盖，同一输出根不能再次尝试。保留管理 receipt、原始输出、
  provider 的 SDK 投影、规范化事件、manifest/spec/report/observation；离线从原件重建全部结果。
  复验必须显式提供从管理侧取得的 receipt hash，不能让 Agent bundle 自己指定信任根。
- [有限候选 wrapper](../../scripts/fr03_p10_v4.py)：复用 SDK adapter、现有 preflight、guard、
  lease、只读 bwrap 及内容寻址发布。新单次额度与旧记录分开，预检成功才允许一次模型尝试。
  SDK 官方 wheel、runtime wheel、已安装 SDK、runtime 主二进制及 Code Mode 配套文件已静态核对。
  导入旧纯函数处显式保留局部 private-use 注释，避免为复用而改写冻结 runner。

该探针验证固定 Linux 组合中的四次 socket 创建拒绝。socket 创建成功不等于能联网；
非 EPERM、上下文不一致、对照失败或输出不完整均不能算安全通过，也不能直接定性为 SDK bug。
文件写入拒绝仍只归因于外层与内层组合。继承的连接、Unix 代理、其他工具和内核因果证明
均不在本次范围。

## 验证与留证

本 worktree 的 `artifacts/workstreams/fr03-v4-implementation-20261011/` 保留：

| 证据 | 结果 |
|---|---|
| `pytest-v4-03.log` | 45 个新增局部用例通过；socket 创建和 SDK 调用全部模拟，pytest 禁网 |
| `pyright-04.log`、`ruff-final.log` | 受影响 src 严格类型检查通过；新脚本及探针的格式/lint通过 |
| `retained-v3-replay.json` | 原真实 bundle 离线复验通过，仍为 NO_GO，SANDBOX/FAILURE_RECOVERY 两项未过 |
| `historical-source-preservation.json` | 旧 runner/evaluator/normalizer/adapter/host/wrapper 与 v3 fixture 共15个文件和 HEAD 字节一致 |
| `prepared-01/preparation.json` | 新 spec、实现依赖、10个输入 hash、有限制品身份和预算；资格 NOT_EVALUATED |
| `capacity-observation.json` | 只读容量快照，未占用 lease 或做共享资源 reservation |

首轮发现新嵌套契约漏写 schema_version，已同步修正 helper 和 schema；保留开发问题记录。
没有重跑科学作业、启动 runtime、account/read、真实 socket 探针或模型；没有改 main/其他
worktree、旧报告、旧 handoff 或原资格状态。旧 v1/v2/v3 定义不变，仅在契约文件末尾新增 v4。

## 待授权的真实执行

本次选择最小的“独立预检 → 同原模型命令路径的 v4 P10”。设计审查中可选的零模型
`command/exec` 可行性分支未实施，不作为新增资格门。新探针在真实 SDK 中是否可取得
预期 errno，仍须以下执行验证；合成测试无法代替它。

输入：已核验的 `post-hm-fr03-01621-02` 制品、当前 v4 fixture/实现 hash、已有只读认证，
`gpt-5.6-sol / medium`。具体 argv、准备记录 hash 和 guard policy 见同目录 `execution-plan-v2.json`。
该版本澄清 token/调用次数限制的实际执行方式；首版计划保留作修订历史。

| 阶段 | 范围与预算 | 验收及停止条件 |
|---|---|---|
| 独立账户预检 | 1次 initialize/account-read；0 thread/turn；90秒；32MiB持久增长 | 身份一致、账户通过、guard真实退出/清理完成；否则停止，不调用模型 |
| 一次 v4 P10 | 1次模型尝试/turn，retry0；另1次内置account/read；token验收阈值为输入250000/输出4096；SDK尝试900秒；前后对照各5秒；256MiB持久增长预算 | 前对照成功才进SDK；四条命令完整、上下文/前后对照成立、9/9、导出与复验一致；失败保留即停，不进P13 |

两阶段串行；持久增长合计288MiB，scratch硬限64MiB，内存拟预留1.5GiB。
按指令完成时合计12次 socket 创建：管理侧固定8次，模型内层指令4次；一次至多一个打开FD。
若模型重复执行，完成后的唯一 lifecycle 校验会拒绝，现有接口没有事前执行次数拦截，
因此12不是整轮不可突破的调用上限。probe不产生外部流量，runtime可能有后台请求。
900秒是SDK尝试预算，对照另计最多10秒，清理沿用现有guard。

SDK host 未向模型设置 token 硬上限，adapter/判分器在尝试完成后核对 usage；250000/4096是
验收阈值，不是服务端计费硬封顶。一轮 turn 内也可能有多次模型推理。超额则失败且不重试；
账户货币计费未知，不代估金额。持久增长是 guard 使用的预算，scratch有硬配额；内存预留
尚未执行，不声称已有硬内存限额。真实调用授权应理解这些实际边界。

只读快照时主机卷可用约62.16GiB、64MiB tmpfs可用约60.72MiB、Linux可用内存约10.22GiB。
这些不是 reservation，也不代表无并发占用；执行前须复查真实宿主卷、全局并发和清理空间，
沿用 Linux 16GiB / 主机32GiB floor 及同一全局 lease。

现有 guard 的 `require_root` 限制输出在统一证据根，不能直接用本 worktree 的准备目录开跑。
待授权的共享写入明确限于：新目录
`/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-fr03-01621-v4-p10-01`、
现有 `artifacts/hosted-evidence/storage-control` 下的 guard/lease 记录，以及现有
`artifacts/hosted-scratch/recovery-runtime01`。不修改原 main 源码、分支或其他 worktree。
授权后原样发布已完成的准备记录到新根；不重复下载、不扩大旧额度、不覆盖旧失败证据。

这里仍需单独授权，是因为最初任务明确要求“真实调用、科学重执行或共享资源……等待授权”，
且原0.162.1单次模型额度已耗尽。本次实施同意不作为第二次真实调用额度或 FR-03 GO 批准。
