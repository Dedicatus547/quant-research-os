# HM-06 Q07 实际探针与来源绑定独立窄审

日期：2026-09-30。模型 override：`gpt-6.1-sol/high`；attempt：1；usage：`unavailable`。
结论：`Q07_EVIDENCE_INCOMPLETE / NOT_QUALIFIED`。
范围：冻结 Q07/C10，commit `ce74335fc2fb4036bcfaa592d594ea27eff6988c`，以及实际保存根
`/tmp/hm-stage-ce74335-attempt04`。开发模型 override 不改变研究 `gpt-6-sol/high`。
本文只读实现与证据，未运行新的越权操作或真实模型；只新增本审查文件，不改实现或冻结文件。

attempt04 是实际受限进程的观察，不是手写 PASS。其已保存结果支持若干局部边界，
但不能作为完整 Q07 通过记录。审查期间 manager/probe/service 的工作树正在补充；
本文明确区分已运行的 ce74335 安装和后继草稿，不把草稿新增字段赋予旧 evidence。

## 已核验的实际证据

`evidence/deployment-probes.json` 为 canonical JSON，15411 bytes，SHA-256：
`907eb313e418395359a702e85110e0f63cec2e757b88bb1f88684cda2e7d3bef`。
记录 D.hash=`3eac901581d997d25d648de76acb52da8b9c29fccf4c9d48d572225d10bf0e79`，
S.hash=`ef6d4fbbe63143a62321e1f34d9d89346e98ca11a2fd7810595c8c895e791173`。
已读取对应 D 的原 bytes 并重算 hash，D.exact_commit 为 ce74335；其安装 inventory hash 与
probe wrapper 一致。安装清单内 probe 文件和实际安装文件的 hash 均为
`bb2b58b61ce2ffca715e614578ddc941e8d1796ec200d2e0e0657314bb14b120`。
这次人工独立读取确实匹配，不代表旧 manager 代码能拒绝所有安装替换。

实际 observation 的 UID/GID 均为 1000：authority/event/Ledger/config/provenance 入口和
sealed/vendor canary/parent proc 等 open 返回 ENOENT；安装模块、projection、channel 写
open 返回 EROFS；正在执行的 native launcher 写 open 返回 ETXTBSY。五项 syscall 返回
-1/EPERM。错误 capability 和错误 campaign 查询未返回，随后合法查询成功，/proc 为空。
wrapper 的 authority 前后清单均有 21 个文件且逐项相同；manager 侧两份非秘密
sealed/vendor canary 文件实际存在。

`channel/bootstrap-observation.json` 为 799 bytes，SHA-256：
`45ceef55405954ecf14daf47d58e1d3ff220637c682e3b1214458641859cba56`。
它记录同 D、真实 service module/executable 路径、isolated/ignore_environment/no_user_site/
safe_path/hash_randomization 五项有效值、seed 环境 `"0"`、只在 `/install/python` 下的
搜索路径，以及 service net namespace `net:[4026532409]`。network_devices=null 是
未挂载 sysfs 时的观察，不能解释成已经证明没有网络设备或离线。
该文件当时仍在受限 host 只读 channel 目录；完整 bundle 应由 manager 核验并保存其
immutable bytes/hash，不能只在停止时删除 socket 后失去原 attestation。

同 UID 本身不授予边界证明。冻结 C10 允许同 UID namespace 的具体组合通过实际门，
也明确普通同 UID shell/CLI 不合格；需要下面各项实际证据才能区分它们。

## 已部署代码的明确来源绑定缺陷

ce74335 的 `probe_managed_deployment` 将当前 `install_inventory` 记为 install_before，
只核验运行后等于它，未在启动前要求它等于 D.install_inventory_hash 和预期完整清单。
同时 `probe_program_hash` 从旧 deployment.install 对象取值。若安装在 stage/bootstrap
后被替换，新的 probe 可以产生输出而 wrapper 仍标原程序 hash；before=after 只证明
被替换后的安装稳定。这是 P1 来源绑定缺口，不能由 producer 报告的 errno/flags 关闭。

最小修复是启动前实际核验完整 installation 与 D/expected inventory 一致，重算 probe 和
真实 executable 所属清单项，并核验本次 BPF bytes 与 D.seccomp_bpf_hash 相同；同时验证
所用 C、S、输入 projection 身份和 profile 的传递绑定。实际 launch argv、程序/manager
身份、输出 hash 与终态 exit code 由 manager 捕获，不由 probe 上传身份声明。
审查末段已在工作树看到 install/profile/config/projection 与 BPF prechecks；方向正确，
但尚不是 ce74335 或 attempt04 的保证，须新 commit/安装/actual probe 记录。

## Q07 的精确最低补充

| 缺口 | 最小实际补充与机械断言 |
|---|---|
| 已知存在的攻击目标 | context 使用真实 campaign，选择实际已有的 event、Ledger、配置/安装清单项；manager 记录对应原 hash/inode 或已绑定的 logical id。只 open/close，不 truncate、不读秘密值。当前 `/business/probe/...` 不存在，不能证明具体 event/Ledger 文件访问被阻断；parent-root 路径须使用真正外部根的路径，不能用 manager 系统上不存在的 `/authority/...`。 |
| 只读安装/配置/投影 | actual host 增加非运行的 `/install/codex`、base Python binary 与必要 service source/wheel 文件写 open；核验 statvfs/mount 的 RO 属性。ETXTBSY 不能证明只读。manager 对 install/config/projection 的完整前后 inventory 重算，并先匹配原绑定；每次真实 request 的 Ii/Pi 与 request hash 另绑定，不能只用 I0 代表全部模型投影。 |
| 可信来源不可达 | manager 在真正 evidence/source 根放已知非秘密 canary，actual host 按真实绝对路径、别名 symlink、parent proc/fd 路径尝试 read/write open；均不能获得句柄。记录 evidence/Pi/capture/projection 根的实际不可写边界和 source 前后 inventory；不读取真实 token、auth 内容或 sealed 数据。probe 阶段未产生的 Pi/capture 可以先证明相同已知存在根边界，但真实 live 工件仍须独立底向上绑定。 |
| import 注入有正控 | host private tmp 中放真实非秘密 CWD/PYTHONPATH/user-site/plugin canary；fresh isolated child 带实际污染环境，find_spec 为 false，并有同安装 unisolated child 为 true 的正控或逐位置明确可见性控制。不能把 clearenv 后指向不存在 `/untrusted-canary` 的 found=false 当有效注入测试；实际 service sys.path/module origins 也绑定安装。 |
| channel symlink/race 与绕入口 | actual host 对真实 `/channel/quantos.sock` 和同目录执行 bounded symlink/unlink/rename 替换尝试；跨进程或并发的 bounded replacement/query probe 保存每次结果。原 endpoint、authorized query、authority 清单保持一致，任意 command/path/management replay header 经真实 raw channel 被关闭/拒绝。`/tmp` 到 `/channel` 的跨 filesystem replace 可能只因 EXDEV 失败，不能单独证明安全；顺序交错的 query 也不能冒称已做 concurrent race。 |
| OS/namespace/proc/fd 身份 | trusted manager 取得真正 sandbox 子进程 PID/身份，记录实际 mnt/pid/user/net namespace、root/mountinfo、uid/gid、Seccomp/NoNewPrivs/CapEff 和 executable/argv/环境指纹，和 service attestation/D 交叉核验。host /proc 为空时由 manager 外侧采集，不为探针开放真实 proc。actual host 对继承 fd 做 fstat/有效性枚举，记录脱敏类型和明确 allowlist，不读取 credential/capability 内容；必须排除 authority、source、parent/root/namespace 可用 fd。 |
| escape syscall 有效性 | 维持 frozen BPF、actual seccomp mode 和实际返回证据；用非秘密已知目标或受控 baseline 区分真实限制与无效参数。现 process_vm 为零长度、pidfd_getfd/setns 的 fd=-1，其 EPERM 是有限 syscall-denial 观察，不能冒称成功定位并阻断了实际可用 parent fd/namespace。未滤波控制若也受外部限制须如实记录；不要强行读真实父进程秘密。 |
| 服务网络离线 | manager 在其实际 net namespace 开非秘密本地 canary listener，并先证明它可连接；service 在 socket 开放前对同 endpoint 实际 connect 失败，记录 errno、时间范围和实际 net namespace，与 manager/host 的 ns 关系交叉核验。记录有效 host proposal network 与服务离线模式；/sys 不可见/null 不构成离线证据。任何发现 service 能连通的 attempt 保留为失败。 |
| 独立判定与未覆盖项 | verifier 对固定 probe 名称/集合、参数控制、preconditions、uid/grant/campaign、所有原 hash、实际否定结果和合法查询正控逐项重算，不接收 producer PASS。失联/超时/不存在目标/未知字段/缺 attestation 按具体 failure 或 NOT_EVALUATED，不能都当 syscall denied。错误 cap/campaign 必须由实际 service 观察其认证/授权拒绝，未产生 trial 或 campaign 读取副作用；测试框架自己的状态位不代替这些证据。 |

普通同 UID 基线只使用非秘密管理 canary/测试目录，可以证明同 UID 普通 shell 仍可访问，
并明确该控制环境 NOT_QUALIFIED；正式探针在真正受限主体中阻断同一对象。该对照不扩大
host 挂载、不放宽认证，不把开发管理者当攻击主体。所有测试辅助参数仅由管理部署工具
提供；研究 channel 不新增任意路径、command、源码或 probe hook。

## 审查期间的后继草稿观察

工作树已开始增加可信 source canary、三种真实 import canary、non-running binary 写 probe、
read-only mount/PR_GET_SECCOMP、channel mutation/raw-management header 和 source/config/
projection 前后 inventory。service 草稿增加 namespace/mount/status 与真实 network connect
观察，manager 增加非秘密 listener 正控。这些是对应缺口的实施方向，不是已执行通过。

读到的 import child 草稿先用默认 json.dumps+print 输出带空格和换行，再把 child.stdout
直接交给 strict_json_object；后者要求完整 canonical bytes，因此该 probe 会在控制子进程
输出解析处失败。最小修复是子进程产生 canonical JSON，确认唯一 frame 尾 newline 后
传 stdout[:-1]，不 strip 任意空白、不改 strict parser。已向实施者指出，最终新版本需实际跑。

后继草稿的 `/tmp`→`/channel` replacement 和八次交错查询还须按上表限定证据含义。
实际 inherited fd/host namespace、真实 existing event/Ledger target、service-observed auth
拒绝与 independent Q07 predicate 仍须完整保存。新增网络探针入口由管理域固定端点类型，
不能演变为研究 channel 的任意网络或命令接口。

## 原三项 P1 的代码复核与资格边界

2418146 后继中：恢复存量 INTENT 已在 publication 前调用保存源 callback；Q11 只有
零 PASS 才进全 NONPASS 的 G5 例外，mixed/all PASS 要求原 P14c 成功；protocol verifier
补 observation hash/object 绑定。run_offline 在目标 bootstrap 前核显式 original source
inventory、原 protocol 完整一致，并逐 accepted response 调现来源 verifier复核 D/I0/Pi/Ii/
capture；source 在 `/saved-evidence` 只读挂载，host 不能选该参数。代码方向关闭原窄审
缺陷；这不表示真实 Q09/Q10/Q11 已完成或 whole bundle 合格。

当前独立 qualification verifier 的场景谓词仍不能据 probe wrapper 自动授予 Q07 PASS。
完整 CI coverage 门、正式 live 和两根重执行等资格条件未由本审查执行。attempt01–04 与
任何后继失败证据保留；不能用最新 probe 成功覆盖先前失败或为旧 D 追加新保证。
整体以及本次 Q07 均保持 `NOT_QUALIFIED`，冻结 contract/acceptance/freeze 保持原 bytes。

## exact commit 输入摘要

下列 hash 来自 `git show ce74335:<path>`；工作树草稿不计入该接受身份。

| src/quantos/infrastructure/ 下文件 | SHA-256 |
|---|---|
| hosted_probe.py | bb2b58b61ce2ffca715e614578ddc941e8d1796ec200d2e0e0657314bb14b120 |
| hosted_manager.py | e4d6ee74006c71fabcd2b07796b3dc381fc284b937ff64bd3ce69f13d6d13763 |
| hosted_deployment.py | 7e94d50f84e7d9b4469c4ae7830867fa966c6e988ef7b6f4ba317acaa6f8d0a6 |
| hosted_service.py | 413ba74abca26b992b000d418a1951683853014496522cbd02386d32d87bf8af |
| hosted_offline.py | f23a696c3bac1c8508a12aed251e58ccd7e1aff1a6e595c986936fb17f7e7e18 |
