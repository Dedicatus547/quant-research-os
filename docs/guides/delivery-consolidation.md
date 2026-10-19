# 本机交付收敛操作说明

本轮仅交付 R0–R4：格式修复、独立环境准备、安全失败诊断、必要离线验证与源码发布。
支持 Linux x86_64 / WSL、Python 3.11；SDK/runtime 后继固定为 0.162.1。
环境准备不授予 live、科学或跨宿主资格，历史接受身份保持原 tuple。

## 已知基线与采用范围

基线 `09edac2070aff4eaa2e13d5b803aee0a8cd08e6a` 的
[CI 39060721924](https://github.com/Dedicatus547/quant-research-os/actions/runs/39060721924)
最终在 Ruff 格式检查失败；后续 lint、类型和测试跳过。旧交接的 `in_progress`
保留当时观察，本页补充最终事实。R1 提交 `afdc94e` 只修复该处排版及 execution profile 文档。

默认 legacy execution profile 仅有 `adjusted_close`；显式 `frozen-field-study/v1`
另支持 `adjusted_volume`，adaptive grammar 不因本轮改变。

历史证明按其真实依赖和原来源复用，不以本轮提交替换历史 PASS：
固定候选的两份 Validation 仍为 REJECT；两次 adaptive 首次 STOP 仍为新候选0、科学0；
`SOURCE_INCOMPLETE` 原因码片段已离线验证、尚未由新有效 recipe 采用。
参见[固定运行接受](../releases/agent-runtime-bounded-v1-2026-10-17.md)、
[首次 STOP 集成](../releases/bounded-adaptive-integration-2026-10-18.md)和
[后继 STOP 采用](../releases/adaptive-closure-integration-2026-10-18.md)。

本地审核与新执行证据分别保留在主仓绝对路径
`/home/zjw/quant-research-os/artifacts/project-review-20261019/` 和
`/home/zjw/quant-research-os/artifacts/delivery-consolidation-20261019/run-01/`，不随源码上传。
唯一主 handoff 为后者的 `handoff.md`。

## 历史包只读操作

采用既有包的入口（先确认包路径与其原身份），`--describe` 只显示 proposal，
`--verify` 只核对离线 pins，`--closeout` 只做既有只读收尾核对：

```bash
<原包声明的解释器> <原包入口> --describe
<原包声明的解释器> <原包入口> --verify
<原包声明的解释器> <原包入口> --closeout
```

实际解释器、包入口及冻结输入见原包 manifest，不能替换为本轮新环境后声称旧资格成立。
不执行 `--authorize`、`--run-approved` 或任何旧任务续跑。
失败仍为 FAILED / NOT_EVALUATED；未知原因继续 UNCLASSIFIED，null/NaN 不补零。
本次不执行 R5/R6、研究 SDK、采集、训练、回测、Validation 或部署。

## 本轮安装验证的宿主前提

已有 storage policy 指向的 `artifacts/hosted-scratch/recovery-runtime01` 当前缺少硬配额
挂载，guard 实际拒绝 `STORAGE_SCRATCH_HARD_QUOTA_UNAVAILABLE`。真实宿主
`sudo -n true` 需要密码，未尝试挂载；独立环境安装验证尚未完成。
需有权限的宿主操作员先核对该专用目录无运行作业和会被遮盖的证据，再恢复原有
64 MiB / 4096 inodes、`nosuid,nodev,noswap` 配额挂载，并重跑既有 guard。
不得仅因 WSL 内部 free 足够而放行，也不得省略 guard 或使用全局环境替代。
准备命令及后继 profile 的准确接口见环境专页；所有实际失败与退出保留在主 handoff。

## 只读诊断入口

详见[失败细类与只读查看](execution-failure-diagnostics.md)。从本任务 checkout 根运行：

```bash
PYTHONPATH=src /home/zjw/quant-research-os/.venv/bin/python \
  scripts/inspect_execution_diagnostics.py \
  --stage-completion /absolute/path/to/completion.json EXPECTED_SHA256
```

按需添加 `--feedback PATH SHA256`、`--selection-report PATH SHA256` 和
`--closeout PATH SHA256`，可分别查看执行状态、科学 verdict、父 selection 原因和已知 token usage。
输入关系由调用者提供，输出不代替 receipt 或完整证据核验。
新增 Workflow 非有限 required metric 与 recorder 接口缺失可输出固定细类；
现有 signal 两细类改用专用内部类型，外部同文异常与未知 cause 不能冒充。
只读检查真实历史 FAILED completion 后仍为 UNCLASSIFIED，未改写历史失败。

## 独立环境入口

完整参数、固定来源和宿主前提见[bounded-local-01621 环境准备](bounded-local-01621-environment.md)。
在 checkout 根可直接运行只读描述（使用现有开发环境，不安装、不调用 provider）：

```bash
/home/zjw/quant-research-os/.venv/bin/python -B \
  scripts/prepare_runtime_environment.py describe \
  --profile configs/runtime/bounded-local-01621/profile.json
```

`prepare` 在新的持久目录创建独立环境，必须由既有 guard 监督；
`verify` 核对已成功安装的完整库存与隔离导入。两个 preparer 通过成对的
`--runtime-environment`、`--runtime-profile` 显式采用此环境；默认 0.154.0 和旧包不变。
完整解析在 Python 3.11.15 / Linux x86_64 / glibc 2.35 下核对了 208 项；发行物共 472750199 字节，
完整增长预留 6 GiB。两个 SDK wheel 已核验，206 个科学/build 发行物仍需提供或按固定来源下载。
安装和新环境实际导入仍未验证；原科学 `scs==3.3.0` 的 yanked/solve crash 告警保留，
本轮没有运行 solver，也未据此改写历史证明。
