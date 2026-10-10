# HM-06 部署设计与前置观察

日期：2026-09-29；实施更新：2026-09-30。状态：`IMPLEMENTED_COMPONENTS / Q07_Q11_NOT_EVALUATED`。
逻辑 profile：`hm-isolated-service/v1`。本文件不是冻结契约的修订，亦不授予资格。
依据：[冻结契约 C08/C10](hosted-contract-v1.md)、[验收矩阵](hosted-acceptance-v1.md)、
[ADR-0003](../adr/0003-host-mediated-mvp.md)。

实施任务模型为 `gpt-6-sol`，reasoning effort=`high`，attempt=1，observed usage=`unavailable`。
研究宿主模型另行绑定 `gpt-6-sol/high`；开发会话不充当 Q07 攻击身份或 Q11 研究宿主。

后续 CLI 来源边界细化见 [hm06-cli-source-boundary.md](hm06-cli-source-boundary.md)：
研究宿主改用空只读 `/proc` 与固定 seccomp，服务保留独立 procfs；此前 namespace canary
观察原 bytes 保留，不能拿旧 procfs 配置授予正式 source-capture 资格。
正式代码入口、无环 B→L→C→D→S→R→Ii→Pi 绑定及聚焦测试见
[HM-06 实施记录](hm06-implementation.md)。本页保留前置部署设计和原始观察。

## 实际部署边界

部署管理域先构建并核验独立 wheel、固定依赖安装、lock/config hashes 和输入清单，再发布
不可变 DeploymentProfile。实际 wheel/commit 绑定待 HM-07 最终代码完成；本次 canary 不代表
该安装。逻辑路径固定，管理机实际路径另以完整 observation inventory 保留，不能投影掉。
服务和研究宿主都使用 bwrap 的 user/mount/pid/ipc/uts namespace、独立 procfs、new-session、
cap-drop ALL、clearenv 和 close_fds。profile 不声明抵抗恶意内核或部署管理者。

| 路径 | 离线 QuantOS 服务 | 受限研究宿主 |
|---|---|---|
| `/install` | 独立冻结安装，只读 | 冻结客户端、公开 `hosted-client.json` 与 CLI 必需文件，只读 |
| `/config` | 冻结服务配置，只读 | 不挂载服务配置 |
| `/authority` | 仅服务可写，本地 POSIX/fsync/flock | 不挂载 |
| `/sealed` | 仅离线确定性服务的必要输入 | 不挂载 |
| `/projection` | 初始静态 I0，随后每次独立管理的 Ii | 只读，恰为本次 R、ContextPack 与 proposal schema 三个 hash 对象 |
| `/channel` | 服务创建的 Unix socket | socket 目录只读，不能替换 inode |
| `/tmp`、宿主会话目录 | 各自独立 tmpfs | 各自独立 tmpfs |
| 管理证据根、采集凭据、源码 checkout | 不挂载采集凭据和 checkout | 均不挂载 |

服务 `--unshare-all`，不能访问宿主网络或 Tushare/模型 endpoint；研究宿主使用
`--unshare-all --share-net`，模型网络只发生于外部宿主提案。网络身份记录与实际 socket
负例同时验证。仅凭 namespace inode 不判 PASS。

服务使用冻结 Python 3.11 安装的隔离入口 `python -I -m ...`，清除 PYTHONPATH、用户 site、
插件、启动钩子和继承 cwd。不能把当前 editable `.venv` 当正式冻结安装；其 Python symlink
指向 checkout 内 `.uv-python`，正式安装须独立构建并逐文件绑定。系统 `/usr/bin/python3`
为 3.10.12，只用于 stdlib canary，不用于 QuantOS 服务。

## 受限通道与统一应用接口

通道只支持冻结入口 `start(spec_hash)`、`pending(campaign_hash)`、`status(campaign_hash)`、
`submit(request_hash,response_bytes,authenticated_principal)`、`resume(campaign_hash)` 和
`cancel(request_hash,authenticated_principal)`，与 HM-04/CLI 共用应用校验，不自建 admission。
客户端不能提供服务路径、Python、命令、输出位置、故障 hook 或离线 import。

SO_PEERCRED 仅提供服务观察的 UID/GID/PID，不能单独授权同 UID namespace。
管理域创建高熵、不可猜测 capability，经内存 fd 提供给指定研究实例，并注册其
host instance 与 campaign allowlist。服务在查询 campaign 或解析业务对象之前认证；
使用常数时间比较且不记录 capability 原文或摘要。证据只保留非秘密 principal ID、
授权 campaign、服务观察的 peer 与部署实例绑定。根目录/socket 不能由研究宿主替换。

固定帧协议须有独立 header cap、request/response cap、连接读取/写入/idle timeout、
最大并发连接数及全局连接上限。按 C04 超限读取至 cap+1 后关闭，留 observed-prefix digest、
observed_bytes、complete=false；不能无限 drain。协议 reject receipt 和 submission 预算
由 HM-03 应用/store 唯一产生；未认证连接只保留有界部署统计，不读取 authority campaign。
未知字段、路径及错误 capability/allowlist 直接拒绝；timeout 和 worker 上限不由 host 改写。

## 可信外部 CLI launcher

launcher 属于部署管理域，直接启动独立研究 namespace 中冻结的外部 Codex CLI。
这不是 QuantOS LLM runtime backend；旧 SDK pin 和历史 CLI backend 均不改变。
预注册 launcher extraction rule `codex-jsonl-single-final/v1`：直接捕获 launcher pipe 的
安全原始 JSONL，要求合法事件序列、成功 exit、单个完成 turn、恰有一个完成的
agent_message，其原始 UTF-8 text 就是 proposal bytes，禁止 strip、人工补写或选择性重跑。
最终细节须针对绑定的 CLI 0.158.0 实际输出验证；失败输出保留安全 digest/reason，不能捏造提案。

CLI 使用明确 model/effort、`--json --ephemeral --ignore-user-config --ignore-rules`、
固定只读工作目录和冻结输出 schema。CLI stdout/stderr 通过管理域 pipe 捕获；不接受
host 上传 transcript 冒充 launcher source。凭据 scanner 在任何原始输出落盘之前执行，
复用 `quantos.security.artifact_secrets.validate_secret_free`，污染输出只发布安全 rejection facts。
capture 和 proposal bytes 都有冻结上限，超限/timeout 终止进程组；失败尝试不可覆盖。
CLI 会话临时目录使用 tmpfs，模型认证只允许已有管理输入的内存/tmpfs 引导，不能复制
auth 到仓库或 evidence；本轮没有读取 auth/token 内容。采集凭据从不进入服务或宿主。

可信 observation 绑定实际 executable bytes/hash/version、requested argv/config hash、
request/projection hash、namespace identity、启动/终止、可得实际 model identity、raw output
digest、提案 bytes/hash、exit 和 source kind。service 从预注册不可 host 写证据根解析 source，
不允许 response 自封 TRUSTED。固定 rule hash、binary/version/config 必须在 live 前发布。
argv/进程身份不能证明 provider effective permission、不可变模型 snapshot 或 hidden retries；
缺失 usage/transcript 记 null+reason，自报与 CLI 实际 identity 冲突则拒绝。

官方输出接口依据：[OpenAI 非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)。
该页已实际读取；本机 `codex exec --help` 同时确认上述 flags 存在。完整 transcript 的
可得性与 model identity 字段仍须以真实调用输出观察，不能用 help 代替 Q11。

## 前置观察与正式验收

完整前置观察为 [hm06-environment-probe.json](hm06-environment-probe.json)。可重跑诊断为
[hm06_namespace_probe.py](../../scripts/hm06_namespace_probe.py)，只创建临时
非秘密 canary，不调用模型或读取真实凭据。首次管理域实际运行成功：bwrap 0.6.1、
Linux 6.18.33.2-microsoft-standard-WSL2、UID/GID=1000、glibc 2.35。
两种 namespace 均实际拒绝 authority/sealed/acquisition canary/证据根访问、父进程 proc/fd
与 proc-init-root 逃逸；安装/投影写返回 EROFS，`python -I` 排除宿主 PYTHONPATH。
离线服务无法连接管理域监听 TCP，联网研究宿主可以连接同一地址，符合角色区分。

本机 CLI 候选为 0.158.0，binary SHA-256=
`167c0148a849d2444f1b5a7fb5f8bb2de1de5ae13a2a504b833fc765980f5cd9`，
实际文件为 `/home/zjw/.codex/packages/standalone/releases/0.158.0-x86_64-unknown-linux-musl/bin/codex`。
该位置仅为安装观察，正式 profile 使用复制并冻结的独立安装与逻辑 `/install` 路径。

最终 Q07 从实际受限研究宿主执行 syscall/API probes，并由 verifier 重算期望：authority
写、sealed/凭据 canary 读、服务代码改、父 proc/fd、插件/PYTHONPATH、非法 campaign、
伪 capability、symlink/路径和直接绕入口均拒绝；保存 syscall errno、exit 与 before/after hashes。
可达的当前环境只说明具备实施条件；`Q07=NOT_EVALUATED`、`Q11=NOT_EVALUATED`、
整体 `NOT_QUALIFIED`，直到冻结安装、通道与真实 CLI 交接都完成并通过独立 verifier。
