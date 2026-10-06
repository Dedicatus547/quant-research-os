# HM 存储恢复与后继执行边界

后继真实运行环境修复已执行，详见[当前实施进度](hm-implementation-progress.md)。
已绑定Ubuntu注册VHD、安装本地非setuid bubblewrap0.11.2并挂载真实硬容量scratch；
严格启动桥及六项真实保护控制通过。下面的ENOENT/不可互操作/未挂载等观测属于
初次恢复时点，保留其原始范围，不覆盖成后继事实。正式验收仍未启动，整体仍未接受。
Windows维护只提供[本机具体步骤](hm-windows-vhd-maintenance.md)，未自动执行。

核查时间：2026-10-06 04:52 UTC（Asia/Singapore 当日）。状态：恢复开发记录，
`NOT_QUALIFIED / NOT_APPROVED`。遵循 [恢复交接](hm-recovery-handoff.md)、
[实施进度](hm-implementation-progress.md)、[roadmap](../roadmap/host-mediated-mvp.md)
和仓库 `AGENTS.md`。本文没有执行完整 CI、正式门、模型调用、大规模复制或 Windows 维护。

## 当前可访问来源

本次只核对明确路径的 `lstat`、固定科学输入的非隐藏顶层目录项、1295B release 的
SHA256、指定 Git 对象和有限进程名称。没有扫描完整环境、递归科学目录、认证或密钥。
Git 使用 `--no-optional-locks`，Python 使用 `python3 -B`。

| 对象 | 精确路径或身份 | 当前观测 |
|---|---|---|
| 冻结实现 | `a2d9b82120f997a937954f1bf0573398c45ca1b7` | Git 对象类型为 commit；不因此证明原安装或工作树仍存在 |
| 原 canonical snapshot | `artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9` | 目录可见；顶层8项可见，没有重验底层文件 |
| 原 derived Qlib view | `artifacts/data/qlib-views/sha256-fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b` | 目录可见；顶层6项可见，没有重验底层文件 |
| 原 upstream release | `artifacts/releases/data-qualified-v0.1-f3fc768/report.json` | regular file，1295B；当前 SHA256 `6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca` |
| 第36轮原管理根 | `/tmp/hm-stage-a2d9b82-attempt36` | ENOENT |
| 第36轮原 W16 | `/tmp/hm-q12-installed-worktree16` | ENOENT |
| 第35轮原 wheel | `/tmp/hm-build-attempt35-01/quant_research_os-0.1.0.dev0-py3-none-any.whl` | ENOENT；历史绑定 SHA256 `e1351c038eb5962e105ecd05c0f89f64529f8c1ded57c01f911c4ee55142d0dc` 当前无法核验 |
| 原 observer helper | `/tmp/hm_stage36_readonly_observer_01.py` | ENOENT；历史绑定 SHA256 `5b1138771b9b7f31f290620d9bdab5e512a8e70450cc7cc352500372a59e6d4c` 当前无法核验 |
| W16 输入 preflight 原件 | `/tmp/hm-worktree16-scientific-input-preflight-01/result.json` | ENOENT |
| 原来源链 Root review | `/tmp/hm36-root-successor-chain-review-01/review.json` | ENOENT |
| 原并行回放及授权 Root review | `/tmp/hm36-root-parallel-replay-and-authorization-review-01/review.json` | ENOENT |
| 第36轮 CI hash observation | `/tmp/hm-ci-ready-review-launch-attempt36-01/independent-ci-hash-observation.json` | ENOENT |
| 第36轮 CI Root observation | `/tmp/hm36-root-actual-ci-observation-01/result.json` | ENOENT |

上述 `artifacts/` 路径均相对于 `/home/zjw/quant-research-os`。当前 `/tmp` 顶层
非隐藏 `hm*` 项的有限名称/metadata inventory 为0项；没有搜索其他宿主路径。
当前沙箱 `ps -eo comm` 未见旧 hm/quantos/python/systemd 名称匹配，不能证明宿主的
systemd 单元、其他 PID namespace 或旧后台任务已退出。ENOENT 只表示当前视图不可访问，
不能区分 `/tmp` 重建、namespace 差异和真正删除，更不能宣称原件永久丢失。

仓库中的 `src/quantos/infrastructure/hosted_manager.py`、
`hosted_management_runtime.py`、`hosted_regression_runtime.py`、
`scripts/hosted_live_qualification.py`、`verify_hosted_qualification.py` 和
`hosted_early_checks.py` 当前可见。它们是可继续开发的源码，不是第36轮外部管理 helper
或原执行结果的恢复副本。实施进度只给出部分 helper03/授权链02 的摘要或哈希；
未访问到原来源绑定时，不推测其完整路径、参数或字节，不用新脚本冒充原 helper。

## 原证据与输入的复用条件

1. 如果在真实宿主找到原管理根和原工作树，先停止新增调度并确认实际存活进程，
   在原件可读、权限和容量安全后保全原件。移动或备份另记路径映射、逐文件 inventory、
   hash 和前后核对；不补写原 wait、prelaunch、出口、结果或 producer 字段。
2. 尚可访问的科学输入只是复用候选。后继运行须由既有 offline input gate 核验原 manifest、
   snapshot/view 逐文件绑定、release、家族/policy/provenance 和权限；顶层存在性不授予 PASS。
   snapshot 是 canonical immutable Parquet；Qlib view/.bin 是 derived cache，不取代 snapshot。
3. wheel 原件不可访问时，可从精确冻结源码与依赖锁离线重建并记录新构建。即使新字节得到
   同一 hash，也不把新 build、安装、部署或 CI 记成原35/36轮执行；新部署需要新 identity。
4. 当前无法访问第36轮原 CI XML/run/tracked/source/principal/退出绑定，故不能以历史
   “1825通过、85.40%”摘要授予后继 Q12。第36轮56/106或其他采集数量也须来自原件；
   本文不改写当时观察、不把缺失出口判成业务失败、不继承旧通过。
5. 缺失的原 helper、CI、场景、来源门、native、公开副本或 authority 绑定，登记为
   `UNAVAILABLE_IN_CURRENT_VIEW`。原件真正不可恢复时，用独立新 attempt 重新执行受影响门；
   保留事故与不可用来源记录，失败/拒绝证据不删除，整体继续 `NOT_QUALIFIED`。
6. 存储保护、针对性测试和合法复用范围确认完成前，不启动完整验收或重复制环境。
   后继代码或部署变化须按影响范围重新冻结和核验；历史文档从来不是资格原件。

## 持久目录、硬配额与空间守卫契约

以下为部署约束；后继已新增下面所列实际接口，但真实 mount、VHD映射和资源容量仍未
核验，不能把源码接入或建议路径当作已部署保护。

| 内容 | 建议独立目录 | 留存与隔离 |
|---|---|---|
| 正式不可变证据、失败和拒绝原件 | `/home/zjw/quant-research-os/artifacts/hosted-evidence/<explicit-attempt-id>/` | 每次独占，拒绝覆盖；已发布原件只读；不参与缓存清理 |
| 已核验不可变离线输入/安装 | 显式 hash 目录及冻结 installation inventory | 只读映射；允许共享的前提是隔离与完整性契约仍成立 |
| pytest basetemp、build cache、临时工作树和测试副本 | `/home/zjw/quant-research-os/var/hosted-test-cache/<explicit-attempt-id>/` | 与证据根无祖先/子孙关系；单独硬配额、生命周期和清理名单 |
| 运行中 spool、私有 tmp、待发布工件 | 独立有界 scratch 卷/目录 | 完整计入预计增量；发布后按 inventory 转入正式证据，保留发布失败事实 |

离开 `/tmp` 能减少临时目录生命周期风险，但同一 WSL VHD 内迁移目录不会释放宿主 C 盘。
上表路径只有在部署权限、mount 身份与 host volume 映射固定后才可采用。

硬配额必须由已核验的文件系统/卷机制强制：例如专用、容量固定且已配足宿主物理容量的
scratch 文件系统，或启用且已生效的项目/user block 与 inode quota。既有限定测试要证明
worker 越额写入被内核拒绝，不能写出配额范围，也不能把正式证据放在自动清理的 scratch。
扫描目录字节数、`du`、软件预算、轮询和单文件 `RLIMIT_FSIZE` 都不能单独证明目录硬配额。
未配置、不能核验或权限不支持硬配额时，重复制/完整 CI/矩阵/导出入口 fail closed。
当前没有创建或设置这些卷、mount 或 quota。

每次部署、CI、矩阵、export 和新 worker 启动前，守卫至少绑定：Linux目标文件系统、
VHD 所在真实 Windows卷、scratch quota 身份、明确新增字节/inode上界、并发预留、
安全收尾/失败留证余量、监测间隔、独占输出路径及 policy hash。空间采样失败、host映射
未知、输入是无边界复制或预留不足，都不允许新增调度；不得默认把 `/mnt/c` 当成实际 VHD 卷。

同一物理卷的消费者统一预留，两个并行 root 不能各自把同一空闲字节算成独占额度。
预估计入原输入实际物理副本、完整 Python 环境、Qlib/MLflow结果、临时中间文件、导出副本和
失败留证，而不只计算最终 bundle。只读复用必须固定 hash、before/after inventory 与权限；
reflink 只有实际支持并验证隔离时才能计入节省，后续写时复制仍预留增长。可写 hardlink
副本会共享 inode，不能用作独立环境或独立可写 authority。

运行中同时监测 Linux、真实 host卷、quota 和预留。触线或监测不可用时停止新增任务，
请求既有管理流程安全收尾、观察真实 wait/不确定退出并保存有界失败记录；继续保持
`FAILED / NOT_EVALUATED` 或实际不确定状态，不造 success，也不删除唯一正式证据。
守卫不代替文件系统硬配额，也无法单独避免两次采样之间被其他宿主进程耗尽空间。

本次 `df -B1`：Linux `/dev/sdd` 可用 `743071727616B`（约692.04GiB），
`/mnt/c` 的 C卷可用 `21260972032B`（约19.80GiB）；这是瞬时可用容量，VHD确切宿主路径
尚未核实，不是新任务额度。WSL所见的虚拟最大容量可能大于 Windows实际剩余空间，
见 [微软 WSL 磁盘空间说明](https://learn.microsoft.com/en-us/windows/wsl/disk-space)。
目前大规模任务应保持拒绝，直到已绑定卷和具体工作量能够通过容量与配额守卫。

## 后继已实现的守卫入口与 policy

实现位于 [hosted_storage.py](../../src/quantos/infrastructure/hosted_storage.py)，
入口为 [hosted_storage_guard.py](../../scripts/hosted_storage_guard.py)，复制设施为
[hosted_storage_copy.py](../../src/quantos/infrastructure/hosted_storage_copy.py)。
这些是后继开发源码，没有恢复第36轮安装或为真实部署授予资格。

`StoragePolicy` 是 frozen dataclass，要求绝对路径；四个路径不能使用符号链接别名。
canonical 字节必须来自 `StoragePolicy.canonical_bytes()`，不能用 pretty JSON、追加
换行或普通 `json.dumps()` 代替。policy文件最大16KiB，读取时同时核对显式SHA256和
canonical字节一致性。

| 字段 | 当前实现要求 |
|---|---|
| `evidence_root` | 已存在的持久 Linux目录；拒绝 `/tmp`、`/var/tmp` 及 tmpfs/ramfs/9p/drvfs；所有受保护输出须位于此根 |
| `scratch_root` | 已存在的独立**确切 tmpfs mount根**，与 evidence_root互不包含；`statvfs` 总容量不超过 `scratch_quota_bytes` |
| `host_volume` | 已存在的确切9p/drvfs mount根 |
| `vhd_file` | 已存在的regular file，位于host_volume且同一设备；此检查本身不能证明它就是当前发行版的VHD，真实映射仍须宿主核验 |
| `linux_reserve_bytes`、`host_reserve_bytes` | 各至少1GiB；启动时分别要求可用量至少等于reserve加完整job的预计新增量 |
| `scratch_quota_bytes` | 正整数；当前只支持tmpfs总容量上限，不接受未经验证的project/user quota作为替代 |
| `poll_seconds` | 大于0且最多5秒 |
| `terminate_grace_seconds` | 大于0且最多30秒 |

tmpfs把容量转为内存资源约束，也可能消耗swap；其上限必须计入实际RAM、cgroup内存限制
和并发worker预算。tmpfs空间上限不证明具备等量可用内存，不能把完整Python环境或科学
数据集塞入scratch来规避磁盘检查。当前实现没有建立tmpfs mount、扩容RAM或核验cgroup
余量；这些条件未核实时，只进行规模受控的纯测试与局部验证。上文项目配额/固定卷是
未来可选方案，现守卫没有其验证器，因此不能据此通过当前入口。

policy生成示例仅供替换真实已核验路径和预算后使用。本次没有执行、写入policy或ready
文件。占位符检查会拒绝未替换的示例；数值是小测试示例，不是完整CI/环境复制的预算：

```bash
PYTHONPATH=src <固定Linux解释器> -B - <<'PY'
from pathlib import Path
from quantos.contracts.base import sha256_bytes
from quantos.infrastructure.hosted_storage import GIB, StoragePolicy

policy = StoragePolicy(
    evidence_root=Path('/<已核验持久Linux证据根>'),
    scratch_root=Path('/<已核验独立tmpfs挂载根>'),
    host_volume=Path('/<已核验VHD所在9p或drvfs挂载根>'),
    vhd_file=Path('/<已核验VHD所在9p或drvfs挂载根>/<实际VHD路径>.vhdx'),
    linux_reserve_bytes=16 * GIB,
    host_reserve_bytes=32 * GIB,
    scratch_quota_bytes=1 * GIB,
    poll_seconds=1.0,
    terminate_grace_seconds=10.0,
)
output = Path('/<持久policy目录>/storage-policy-<明确attempt>.json')
assert all('<' not in str(path) for path in (*policy.paths, output)), 'replace placeholders'
payload = policy.canonical_bytes()
with output.open('xb') as stream:
    stream.write(payload)
print(sha256_bytes(payload))
PY
```

首先执行只读布局/容量检查；实际CLI stage值是 `deployment`、`ci`、`matrix`、`export`、
`replay`（不是 `部署` 或 `stage`）。`--check-only`不会建立运行lease，也不授权直接启动
需要checkpoint的业务命令。真实执行须在同一守卫监督调用内给出明确固定命令：

```bash
PYTHONPATH=src <固定Linux解释器> -B scripts/hosted_storage_guard.py \
  --policy <绝对policy路径> --policy-sha256 <实际canonical-SHA256> \
  --stage deployment --expected-new-bytes <完整job预计新增字节> --check-only

PYTHONPATH=src <固定Linux解释器> -B scripts/hosted_storage_guard.py \
  --policy <绝对policy路径> --policy-sha256 <实际canonical-SHA256> \
  --stage deployment --expected-new-bytes <完整job预计新增字节> \
  -- <固定部署命令及明确参数>
```

监督器在 `evidence_root/storage-control/run-.../` 发布有界prelaunch/policy/exit记录，并
预留1MiB收尾记录空间；存储记录只保存argv hash，不输出原argv或child stdout/stderr。
同一 evidence_root 的exclusive lease拒绝第二个并发job，job内部worker由同一个总预算
覆盖。所有共享同一物理卷的正式作业应使用同一个evidence_root监督；不同evidence_root
各有锁，不能据此宣称跨根/跨进程全卷过订已被阻止。

运行中同时检查Linux与host容量，按两者可用量的下降观测增长，超过forecast即失败；
这个增长包含其他同卷写入，不等于精确job字节统计。wrapper实际wait和namespace退出
观察后再次核对容量与forecast，以覆盖最后一次轮询到退出之间的写入。保护触发时向
受监督进程组发TERM，等待grace后必要时KILL并观察实际 `Popen.wait()`；清理期间屏蔽
重复SIGTERM/SIGINT，避免中断原退出记录的保存。存储记录的validation始终
`NOT_EVALUATED`，资格始终 `NOT_QUALIFIED`。

正式作业由bwrap建立独立PID namespace；监督器从真实 `--info-fd` 读取init PID与
namespace身份，核对wrapper父子关系后绑定pidfd。在wrapper实际wait之后观察namespace
init退出，必要时通过pidfd请求清理。它记录wrapper与namespace退出事实，不把这些事实
写成每个native子任务的原wait；业务管理者仍负责其原始退出/来源记录。wrapper wait
不可观察时return_code=null、waitpid_observed=false；namespace退出未知或未完成时
单独保留namespace_exit_observed的null/false与失败，不授予cleanup完成。lease owner缺出口、绑定不明
或previous job未确认清理时，后继作业分别拒绝为
`STORAGE_PREVIOUS_JOB_UNRECONCILED` / `STORAGE_PREVIOUS_JOB_UNREAPED`，不能靠
失去flock或旧PID当前不可见就自动放行。

部署、CI、矩阵预算、管理导出、replay入口及source snapshot复制已接入
`storage_checkpoint`。缺少显式policy/hash、有效active supervisor lease或布局/容量
证明时默认拒绝。管理设置使用 `QUANTOS_STORAGE_POLICY`、
`QUANTOS_STORAGE_POLICY_SHA256`、`QUANTOS_STORAGE_LEASE`；不读取全量环境或认证来
推导策略。子进程环境已改为固定allowlist：固定PATH、禁止Git optional locks、禁止Python
bytecode，以及policy/hash/lease/TMPDIR；不复制任意父环境。局部单测覆盖认证环境变量
不被转送，这不证明正式认证流程或真实namespace已通过。不能用手工填环境值证明真实监督。

`copy_tree_verified`/文件复制默认要求成功reflink；不支持时仅在调用者提供明确的
`before_physical_copy`预算守卫回调且该回调通过后逐文件物理复制，不静默退回普通copy。
它拒绝source symlink、hardlink和special file，核对前后字节、identity、mode及独立
destination inode，并区分实际reflink与physical统计。已有Python环境常含symlink，
因此来源规范化是新的前置工作，不能让旧环境直接复制后声称安装绑定不变。
来源规范化、全环境复制、完整CI与真实双根回放均仍需新identity和实际资源/来源验证；
小文件fixture或纯测试通过不证明这些大工作量已安全执行。

## 当前真实运行阻断与新身份要求

后继 [hosted_deployment.py](../../src/quantos/infrastructure/hosted_deployment.py) 新增
`hosted-mount-policy/v3`，保留历史v1/v2字节与识别分支。v3为私有 `/tmp` 固定
`536870912B`（512MiB）上限，要求bwrap的 `--size` 位于对应 `--tmpfs` 前；
[CI namespace](../../src/quantos/infrastructure/hosted_regression_runtime.py) 同限。
这与外层scratch_root的独立tmpfs容量是两项约束，都要计入实际内存与并发预算。

`require_bounded_bwrap()` 核对 `/usr/bin/bwrap` metadata、执行有限 `--help` 并要求
实际支持 `--size`。本次有限help观察只有 `--tmpfs`/`--unshare-pid`，没有 `--size`；
因此正式作业当前硬拒绝为 `STORAGE_BWRAP_HARD_QUOTA_UNAVAILABLE`。已有namespace
能力不满足新的硬容量要求，不能移除 `--size`、改成无上限tmpfs或回退旧mount policy
绕过此门。先通过Linux/host布局与容量检查后，正式quota支持仍不满足时，监督器在
启动前保存failure exit，pid/return_code为null、waitpid_observed为false，没有启动job。

`local-validation` 是源码内部用于受控toy子进程的开发模式；CLI不提供这个stage选项，
它不能执行正式部署、CI、矩阵、导出或回放。新PID namespace监督链尚未在真实完整
资格环境执行；单测与静态检查只能证明其明确的局部范围。

当前工作树有未提交后继变更，不是冻结C35。v3 mount policy、存储守卫、安装规范化和
环境传递变化必须冻结新commit、离线wheel、安装/部署及管理helper绑定，并按影响范围
完成新输入、来源门、完整CI/场景、native与资格审查；不修改旧C35身份或补写旧失败。
本机bwrap硬容量支持缺失、宿主C卷仅约19.8GiB、真实VHD映射未知、正式scratch mount
尚未建立/核验，仍是未解除的运行前置。代码接入和局部通过不表示环境ready，不允许
完整验收或大环境复制；只进行规模受控的必要开发验证并保留真实失败/拒绝记录。

## Windows 侧维护方案（只提出，不执行）

由用户在可关闭 WSL 的维护窗口执行。先保全可恢复的原件和已核验备份，停止研究及开发
后台任务，避免关闭过程中写入；本文没有运行下列 Windows 命令。

先在 PowerShell 用 `wsl --list --verbose` 和 `wsl --version` 固定真实发行版名称与版本。
只查询该名称的 VHD 路径，不打印全量注册表或环境；微软给出的定位方式如下。
[官方定位说明](https://learn.microsoft.com/en-us/windows/wsl/disk-space)

```powershell
$hmDistro = '<实际发行版名>'
$hmVhd = (Get-ChildItem -Path HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss |
  Where-Object { $_.GetValue('DistributionName') -eq $hmDistro }).GetValue('BasePath') + '\ext4.vhdx'
Get-Item -LiteralPath $hmVhd | Select-Object FullName, Length
Get-Volume -DriveLetter C,D | Select-Object DriveLetter, SizeRemaining, Size
```

将盘符列表改成实际 VHD 所在卷及计划目标卷；同时核对目标卷可以容纳备份、导出、导入
和运行增长，不假设 D盘存在。备份若放在C盘会进一步挤占当前19.8GiB余量，须选择有足够
空间的其他卷。维护后重新采样并记录精确路径/卷映射，不能沿用迁移前的 guard配置。

压缩适用于动态扩展 VHD，可以减少物理文件大小，回收量不能事先保证。执行
`wsl --shutdown` 后关闭会自动重启 WSL 的终端、IDE和容器程序；管理员命令提示符进入
`diskpart`，对已经核对的**脱离状态**目标执行：

```text
select vdisk file="<已核对的 ext4.vhdx 完整路径>"
detail vdisk
compact vdisk
exit
```

若目标仍以可写方式附加，停止并查清占用。微软要求 compact 的动态盘处于 detached
或 read-only attached 状态。重启发行版后验证固定输入、证据库存和容量；不要为了促成
压缩使用写满空闲空间的零填充做法。
[官方 compact vdisk](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/compact-vdisk)

长期迁移优先使用微软支持的 export/import 流程，保持原发行版和备份，先导入为新名称。
完成停写与 `wsl --shutdown` 后，以下示例把 export 和新安装都放在另一个容量充足的卷：

```powershell
wsl --export <原发行版名> D:\WSL-Backups\hm-recovery-20261006.tar
Get-FileHash -Algorithm SHA256 D:\WSL-Backups\hm-recovery-20261006.tar
wsl --import <新的独占发行版名> D:\WSL\HM-Recovered D:\WSL-Backups\hm-recovery-20261006.tar --version 2
wsl --distribution <新的独占发行版名> --user zjw
```

盘符、路径、用户名和名称均须替换为实际值。先核验新发行版的用户、权限、源码精确
commit、固定 snapshot/view/release 与全部可恢复正式证据 inventory，再配置新 VHD卷
绑定和硬配额。导入不恢复已丢失的 `/tmp` 原件，也不授予旧安装/CI资格。不要在核验前
卸载或 unregister 原发行版；微软明确说明 unregister 会永久移除其数据、设置和软件。
原发行版删除属于后续单独维护决策，不包含在本方案执行范围。
[官方 export/import 和 unregister 语义](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)

示例保留Linux16GiB、宿主32GiB，加上完整预计新增量；这不是未来job增长估计。
本次已观测C卷约19.8GiB，不能满足该保守宿主余量，更不能凭Linux空闲启动验收。

后继执行顺序为：确认当前可恢复来源 → 生效并核验存储保护 → 有意义的局部测试 →
冻结新的实现/安装/管理绑定 → 依据实际来源决定复用或新 attempt → 完整门与正式审查。
真实认证模型调用及上下文外传仍须最终具体材料齐备后另获明确用户授权。
