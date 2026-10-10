# 本机 WSL VHD 独立维护步骤

2026-10-06，用户已明确批准本次离线压缩；以下原手动步骤保留供审阅。
代理准备的实际一次性任务采用微软支持的**未挂载VHD直接compact**方式，
不创建挂载，避免失败清理时误detach其他进程的挂载。执行结果尚待Windows实际记录核验，
不得把准备、批准或任务启动记为压缩成功。本机注册发行版为 `Ubuntu`；经 Windows Lxss
注册元数据及同一仓库文件 device/inode 核对，其 VHD 为：

```text
C:\Users\zjw\AppData\Local\Packages\CanonicalGroupLimited.Ubuntu_79rhkp1fndgsc\LocalState\ext4.vhdx
```

原始观察在 `artifacts/hosted-evidence/recovery-runtime01/runtime-observation-01.json`。
VHD文件逻辑长度为604493578240B，不能把此长度当成实际已分配空间或承诺可回收量。
正式预检观察C卷可用20328837120B，当前选用的32GiB保守余量底线尚缺14030901248B
（约13.07GiB），且还需另加完整执行的预计新增量。32GiB是本次存储策略的保守配置，
不是研究资格门；科学、来源、106场景及85%完整CI门槛保持不变。

## 维护前准备

先保存会话交接与本轮持久证据，停止新增调度；关闭其他WSL工作负载。
`wsl --shutdown` 会停止所有WSL发行版，包括本会话及Docker，不在运行中的Linux会话执行
后续操作。本次用户明确批准后，代理通过Windows系统UAC提升注册一次性任务；
任务及日志位于Windows文件系统，WSL关闭后继续运行。未获UAC提升时不会关闭WSL或压缩。
若准备完整VHD备份，先选择另一块卷并核对至少能容纳该文件逻辑长度及余量，
不要在仅余约19GiB的C卷复制604GB文件。备份保持本地，不读取或展示其认证文件内容。

## 离线压缩路径

先用下列只读命令重新确认精确文件和C卷余量；与上述注册位置不一致即停止：

```powershell
$HmVhdPath = 'C:\Users\zjw\AppData\Local\Packages\CanonicalGroupLimited.Ubuntu_79rhkp1fndgsc\LocalState\ext4.vhdx'
Get-Item -LiteralPath $HmVhdPath | Select-Object FullName, Length
Get-Volume -DriveLetter C | Select-Object DriveLetter, Size, SizeRemaining
wsl --shutdown
wsl --list --running
diskpart
```

确认没有运行中的WSL后，在DiskPart内逐行执行：

```text
select vdisk file="C:\Users\zjw\AppData\Local\Packages\CanonicalGroupLimited.Ubuntu_79rhkp1fndgsc\LocalState\ext4.vhdx"
attach vdisk readonly
compact vdisk
detach vdisk
exit
```

选盘、挂载或压缩任一步失败就停止后续步骤，保留实际错误；如已挂载，完成detach。
不执行填零、不删除证据、不unregister发行版。压缩前后分别记录实际C卷可用空间。
步骤依据：[Microsoft compact vdisk](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/compact-vdisk)
与 [WSL commands](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)。

## 已批准任务及中断续接

本次任务名 `Quantos-HM-VHD-20261006-01`，无触发器、无自动重试，等待独立release
记录后才关闭WSL。原生压缩不设置强制杀进程的时限；运行中持续记录C卷余量，
余量警报阻止新增工作，现有原生操作安全完成。任务执行一个固定DiskPart脚本：
`select vdisk file="<上述精确VHD>"`、`compact vdisk`、`exit`。
任何已挂载状态、注册路径变更、启动错误均保留实际失败，不能记作通过。

Windows持久日志目录：

```text
C:\Users\zjw\AppData\Local\Quantos\hm-vhd-maintenance-20261006-01
```

源码脚本、hash绑定和续接清单在仓库
`artifacts/hosted-evidence/vhd-maintenance-20261006-01`。不复制完整VHD或认证目录。
重启WSL前先在Windows PowerShell读取：

```powershell
$HmLog = 'C:\Users\zjw\AppData\Local\Quantos\hm-vhd-maintenance-20261006-01'
Get-Content -Raw -LiteralPath "$HmLog\result.json"
Get-Content -LiteralPath "$HmLog\compact.stdout.log"
Get-Content -LiteralPath "$HmLog\compact.stderr.log"
```

`result.json`未出现时，先检查同名计划任务及原生DiskPart进程，不重启WSL、重跑或杀压缩进程。
`NATIVE_COMPLETED_PENDING_LOG_REVIEW`仅表示观察到原生命令结束；还需检查实际stdout、
退出码、未挂载观察、C卷实际余量及错误字段，才可结论本次维护成功。
任何维护成功都不等于正式验收通过，不授权研究模型认证或上下文外传。

UAC请求可能需要用户在Windows安全桌面确认。放行监督程序最多等待10分钟，
检查实际管理员就绪、两份脚本hash、精确任务XML与Running状态及新C卷余量后才写release。
`release-controller-result.json`记录实际放行或拒绝；超时后不自动重试，不补“已运行”。
若`release.json`未生成而监督器已超时，则本次没有获放行；任务最多等待自身5分钟，
记录失败后删除自身未变化的任务，源码与全部日志保留。无需再次授予代理同一维护权限，
但Windows管理员提升必须由系统实际完成。

## 重启后的保护与复验

启动Ubuntu后，旧/tmp、进程、挂载及lease一律重新观察，不继承存活、wait或quota假设。
本轮scratch是非持久tmpfs挂载；重启后必须重新建立独立硬容量挂载并核验noswap、
mount身份、byte/inode上限。挂载缺失时现有守卫会拒绝正式入口。
核对已安装bubblewrap的明确版本/hash、原持久证据hash及VHD注册映射；不改写旧失败exit。
按新的完整工作量预算生成显式hash策略并通过两卷预检后，再冻结新源码/wheel/安装，
启动新的离线attempt。空间增加本身不授予旧CI、场景、HM09或研究资格。

如压缩后仍不足，可另选空间充足的目标卷，使用WSL官方export/import建立**新名字**发行版，
对源码、输入、证据逐项hash核验后切换。目标卷/新发行版尚未选定，迁移不能直接执行；
保留原发行版，验证完成前不unregister。参见
[WSL disk space](https://learn.microsoft.com/en-us/windows/wsl/disk-space)。
