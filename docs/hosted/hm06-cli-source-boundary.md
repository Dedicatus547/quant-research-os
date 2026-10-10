# HM-06 CLI 输出来源边界前置探测

日期：2026-09-29。状态：`PREFLIGHT_OBSERVED / NOT_QUALIFIED`。
本记录延续 HM-06 开发 attempt=1，模型 `gpt-6-sol/high`，usage=`unavailable`。
不改变冻结 C10，不实现服务通道，不调用模型，不读取任何 auth/token 内容。

仅隐藏 authority 根不能证明 launcher pipe 中的 JSONL 来自冻结 CLI。与 CLI 同 UID 的
工具子进程可能重新打开 `/proc/<CLI-pid>/fd/1`，向事件流写伪造 JSONL，或用 ptrace/
process_vm_writev 改父进程内存。因此宿主采用以下有界 OS 边界，不能以模型提示代替：

- 研究 namespace 的 `/proc` 是空只读 tmpfs，完全不挂 procfs；服务可保留自己的 procfs。
- x86_64 固定 seccomp BPF 拒绝 ptrace、process_vm_readv/writev、pidfd_getfd、kcmp，
  拒绝 mount/unshare/setns 及 namespace clone flags，阻止子进程重新挂 procfs。
- clone3 返回 ENOSYS，使常规线程/进程创建可回退 clone；普通 fork/clone 不被禁止。
- 关闭非必要继承 fd、隔离新 session，工具 stdout/stderr 被 CLI 捕获；工具不能继承
  launcher 原始 stdout pipe 的别名或 capability fd。正式 Q07 必须验证这一 fd 条件。

seccomp scope 仅支持本机冻结 x86_64，其他架构直接拒绝部署；其 BPF、libseccomp 与
bwrap 版本/哈希进入 DeploymentProfile。过滤规则详见
[probe source](../../scripts/hm06_cli_source_probe.py)，BPF SHA-256 为
`a66ee36d025856553d5516ac52783c18c530b057d18bfadf637e7e3c5605defb`。

实际探测记录不可覆盖：[run01](hm06-cli-source-probe-run01.json)、
[run02](hm06-cli-source-probe-run02.json)。第一轮 bwrap 拒绝对非 mount-point 的
`/proc` remount-ro，CLI 未启动；第二轮使用空 tmpfs mount 后成功。
在空只读 `/proc` + 上述 BPF 下，真实 Codex 0.158.0 `--version` 与 `exec --help` 都 exit=0。
同 UID 子进程实际攻击父进程：父 stdout fd 读取 ENOENT；ptrace、process_vm_writev、
pidfd_getfd、unshare、mount proc 和 namespace clone 返回 EPERM；clone3 返回 ENOSYS。
父进程内存 canary 未变化，普通 fork 成功，攻击进程 exit=0。

此结果只证明非 live 启动与 canary 机制。正式 live 仍需证明 CLI 可读取冻结 schema、
模型/effort 配置、真实网络交接与固定输出抽取；help 成功不能当 Q11。
若实际 CLI 需要 procfs 或内建 sandbox 需要被禁止的 namespace syscall，必须先解决其
最小需求并重新冻结 profile，不能恢复可读父 `/proc` 后宣称来源风险已消失。

## 已知 capability/secret 输出拦截

高熵 capability 不一定匹配通用 credential scanner。可信 launcher/service 在内存注册
所有已知敏感值，任何 pipe/raw-output/response/rejection-text 持久化前，都先做已知值
精确比对，再复用 `validate_secret_free`。capability 不写 argv、日志、evidence、其摘要或
异常文本；仅非秘密 principal ID 被保留。不得把含 capability 的原始输出写文件后再扫描。

比对覆盖原始 UTF-8、JSON 解码后的字符串以及冻结实现明确支持的 base64/url-safe-base64、
hex、percent-encoded 与 JSON escaped 形式。保存的 record 只能报告 detection rule 和安全
原因，不能包含命中的字节或字节前缀。未知任意编码不被宣称可完整检测；权限边界仍以
不把 capability/采集凭据提供给模型输入或 CLI 可继承 fd 为基础。

frame/capture 都有硬 byte cap。输出先在有界内存缓冲区完成 scanner 与已知值检查，再发布
安全原始输出和 source record；超限、污染、timeout 或来源不确定时拒绝 Q08/Q11，保留安全
失败事实，不发布 proposal。任何输出摘录、console 日志和失败 stderr 都走相同前置检查。

内存随机 canary 实测见 [known-value run01](hm06-known-value-probe-run01.json) 与
[run02](hm06-known-value-probe-run02.json)：原文、base64/url-safe-base64、无 padding、
大小写 hex、完整大小写 percent encoding 和 JSON unicode escape 均在 publish 前拒绝，
rejected-case files-written=0，安全 control 允许。canary 值及其 digest 均未留存；
[诊断源码](../../scripts/hm06_known_value_probe.py) 只是前置机制测试，不是生产 scanner 资格。

正式 Q07 应保留 syscall errno/exit/before-after hashes，并由 verifier 重算期望。此方案是
冻结 C10 的 mount/pid/proc/fd 与零凭据留存要求的实现细化，无需修改合同；Q07/Q11 仍为
`NOT_EVALUATED`，整体 `NOT_QUALIFIED`。
