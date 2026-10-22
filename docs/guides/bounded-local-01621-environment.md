# bounded-local-01621/v1 本机环境准备

此命名后继提供离线准备实现，不授予 live 或科学资格。默认 `uv.lock` 和
`agent-openai` extra 的 SDK 0.154.0 保持原身份。支持 Linux x86_64/WSL、CPython
3.11.15、glibc >=2.35，使用 profile 固定的 uv 0.11.25。不是跨机器自包含发行版。

配置位于 `configs/runtime/bounded-local-01621/`：`lock.json` 固定 208 个发行物的
精确版本、PyPI URL、SHA256 和长度，共 472750199 字节；`requirements.lock`
固定安装输入。科学版本由已有锁选取，SDK/runtime 同时选取 0.162.1，另固定
setuptools 84.0.0 和 wheel 0.45.1，用于唯一 sdist `gym==0.26.2` 的离线构建。
随后 uv 对全部精确版本执行独立完整解析，处理依赖约束、markers 和传递 extras；
精确目标 `3.11.15 / x86_64-manylinux_2_35` 的结果与 208 项完全一致。
`resolution.json` 保留结果、输入和原始解析输出 hash，profile 绑定此结果。
不能将此次解析称为完成安装或科学执行。

解析也确认原锁的 `scs==3.3.0` 已被上游 yanked：manylinux x86_64 和 Windows
wheel 存在首次 solve 崩溃告警。此后继保留已有科学版本和该告警；本轮不执行
solver、不改变旧证明，也不声称新环境的科学路径已经验证。

宿主前提显式保留：基础 CPython prefix 及完整 Python 库树、系统共享库、uv、Qlib 官方
源码 checkout。profile 核对基础解释器和 libpython hash，
`host-stdlib-inventory.json` 这个文件名沿用本轮初稿；它实际核对完整 base
`lib/python3.11` 库树，包括 bootstrap site-packages 中的 pip/setuptools，范围超出
标准库。新 venv 不导入这些 base packages。glibc、libstdc++、libgomp
等操作系统库仍由受支持宿主提供。安装结果记录真实 base interpreter、源码和
Qlib checkout 的绝对路径；系统库未宣称完全封装。项目源码由显式 checkout 导入，
package 的既有 code provenance 继续固定 clean commit 和默认锁身份。

Qlib 工具不在 wheel 内。指定已有官方 checkout，要求 commit
`da920b7f954f48ab1bb64117c976710de198373e`，复用
`verify_official_qlib_tools` 检查版本、Git 原件及 `dump_bin.py`、
`check_data_health.py` hash；准备只核验、导入，不执行这些科学工具。

只读描述可以用已有开发 Python 执行；`--artifact-source` 可重复，指定只读的
平铺发行物目录。它只读取锁中明确的发行物，不扫描或复制认证、运行目录。

```bash
python3.11 -B scripts/prepare_runtime_environment.py describe \
  --profile configs/runtime/bounded-local-01621/profile.json \
  --artifact-source /path/to/fixed-public-distributions
```

准备必须通过既有 `hosted_storage_guard.py` 独占 lease。先刷新真实 `/mnt/c`
和 VHD 映射、宿主卷余量及并发预留，使用原安全 floor 和可验证硬配额 scratch。
完整增长预算为 6 GiB：发行物 0.5 GiB、独立安装 2 GiB、uv extraction/build cache
2 GiB、失败留证和安全收尾 1.5 GiB。单 worker；不复制市场输入。
下列变量必须填入实际、已核对的路径；准备输出必须为新的持久目录，位于 policy
evidence root 内。profile/hash 不符在下载和安装之前拒绝。

```bash
TASK_PYTHON=/path/to/existing/bootstrap-python3.11
TASK_BASE_PYTHON=/path/to/hash-matched/base-prefix/bin/python3.11
TASK_UV=/path/to/hash-matched/uv
TASK_POLICY=/path/to/existing/policy.json
TASK_POLICY_SHA256=<actual-policy-sha256>
TASK_ENV=/path/to/policy-evidence-root/new-environment-attempt
TASK_PROFILE="$PWD/configs/runtime/bounded-local-01621/profile.json"
TASK_QLIB=/path/to/official/qlib-0.9.7

"$TASK_PYTHON" -B scripts/hosted_storage_guard.py \
  --policy "$TASK_POLICY" --policy-sha256 "$TASK_POLICY_SHA256" \
  --stage deployment --expected-new-bytes 6442450944 -- \
  "$TASK_PYTHON" -B scripts/prepare_runtime_environment.py prepare \
  --profile "$TASK_PROFILE" --output "$TASK_ENV" \
  --base-python "$TASK_BASE_PYTHON" --uv "$TASK_UV" \
  --qlib-source "$TASK_QLIB" --artifact-source /path/to/fixed-public-distributions \
  --download

"$TASK_PYTHON" -B scripts/prepare_runtime_environment.py verify \
  --profile "$TASK_PROFILE" --output "$TASK_ENV"
```

`--download` 只下载缺少的锁定公开发行物；不带该参数时完全使用已提供原件。
新环境不使用 `.pth` overlay 或用户 site-packages；venv 不继承系统 site-packages，
安装使用独立 inode，固定 hash 校验后才离线构建/安装。完成后保存完整环境库存、
版本和导入路径、SDK 二进制 hash 及宿主前提。uv cache 是准备中间件，不是运行依赖。
`verify` 重新核对库存及隔离导入，不启动 provider、`runtime.run`、训练、回测或采集。

失败目录保留 `preparation-start.json`、已完成子命令的 start/exit 和 `failure.json`；
不会保存任意异常文本、stderr 或凭据。失败 attempt 不重写；恢复先对账既有 guard
退出和安装步骤，从固定发行物准备一个新的 attempt。当前入口没有安装中途续写功能，
不得把失败目录补标成功。已成功安装通过 `verify` 后可复用，不因总体 commit 改变
就重复安装。

两个 package preparer 新增成对的 `--runtime-environment` 和 `--runtime-profile`。
使用新环境的 Python 执行现有准备命令，并附加这两个选项；preparer 要求当前解释器
确实来自该环境及源码 checkout，并拒绝当前进程的外部 site-packages、已加载关键
依赖模块和 distribution metadata 来源污染，即使版本相同也拒绝。adaptive successor 的 manifest 进一步固定 profile、
result、inventory hash，并在包核验时重新核对；其 Python 路径不含旧 overlay/site。
未给这两个选项时保留旧入口语义。原 recipe、预算、TTL 和授权都不会因环境准备转移；
新环境准备仍不能启动旧包或赋予新任务运行许可。

2026-10-19 首次准备记录（历史）：完整固定闭包及独立解析已完成，必要小型离线反例通过；独立安装
验证 **BLOCKED**。原 policy 的 scratch quota 挂载不存在，guard 实际返回
`STORAGE_SCRATCH_HARD_QUOTA_UNAVAILABLE`；真实宿主 `sudo -n true` 也返回需要密码，
所以没有尝试挂载或安装。已核验 SDK/runtime 两个保留 wheel；其余 206 个发行物当前
未在指定原件目录提供，完整清单由 `describe` 输出，恢复 quota 权限后可按固定 URL
下载。实际解释器、venv 布局、全量安装库存和新环境的 Qlib 导入尚未证明。
持久证据位于主仓 `artifacts/delivery-consolidation-20261019/run-01/environment/`，
包含容量、guard/sudo 失败、resolver 退出、定向检查及发行物库存。

后继成功（2026-10-19，2026-10-20收尾核对）：上述BLOCKED为首次准备时点，
R0–R4交付已通过原WSL管理接口恢复quota，208项独立安装及隔离导入成功；
见[完成交接](../../artifacts/delivery-consolidation-20261019/run-01/handoff.md)与
[安装核对](../../artifacts/delivery-consolidation-20261019/run-01/environment/install-01/verified-summary.json)。
后继[库存恢复核验](../../artifacts/delivery-consolidation-20261019/run-01/environment/post-install-bytecode-01/verified-summary.json)
确认27961文件库存hash不变、真实退出及cleanup成功；启动必须加 `-B` 或 `PYTHONDONTWRITEBYTECODE=1`。
原guard/sudo失败保留，不覆盖失败目录；本条不证明新环境科学/live组合，亦不要求重新安装或全量库存扫描。
