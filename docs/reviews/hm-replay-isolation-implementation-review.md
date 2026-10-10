# HM 隔离与回放实施独立核验：5b31ec5

日期：2026-09-30。审查模型 override：`gpt-6.1-sol/high`；attempt：1；usage：`unavailable`。
结论：`IMPLEMENTATION_CHANGES_REQUIRED / NOT_QUALIFIED`。
对象：exact commit `5b31ec54407f590dcf15f9d74851fb8c7ace3dc8`。
后继依据：[原实施澄清](hm-replay-isolation-review.md)。
用户模型 override 只适用于开发/审查；冻结研究配置仍为 `gpt-6-sol/high`。
本文新增独立记录，未修改代码、已有审查或冻结 contract/acceptance/freeze 文件。

隔离 CAPI 启动、逐条 journal 比较与 SUBMIT publication allowlist 已落实主要设计，
但指定提交尚有下面三项阻塞。审查过程中主 agent 已开始修改工作树；所有正式发现绑定上述
commit，不把随后尚未提交/独立验证的改动算作该 commit 已修复。

## 发现与最小修复

### F1：恢复既存 INTENT 时先写工件，后核对原协议（P1）

定位：`hosted_store.py:265–287`，`hosted_replay.py:137–141`。
创建新 INTENT 时 `_append` 会先调用 `verify_journal_entry`，但
`recover_locked` 对已有 INTENT 直接调用 `_finish`。后者先 `_publish` 所有 publication，
再由 `_append(COMPLETE)` 核对保存源。`import_next_submission` 也先 recover，之后才
`verify_prefix`。因此合法 hash/sequence 的错误目标 INTENT 可以在被拒绝前发布业务工件。
这违反原澄清要求的“既存目标事实先核对保存原 bytes，再恢复其准确 publication”。

独立复现使用临时 disk fixture，并从 `git show 5b31ec5:.../hosted_store.py` 内存加载原实现：
保留完整原 prefix，移除最终 COMPLETE，修改末尾 BUSINESS INTENT 的 recorded_at 并重算
其 hash/文件名，删除其中一个 publication 工件模拟崩溃。结果为：

```text
publication_exists_before_recovery: False
recovery_rejected: replay generated journal differs from saved next entry
publication_exists_after_rejected_recovery: True
```

拒绝本身有效，但发生得太晚。最小修复是在恢复 `_finish` 前使用同一 callback 核对完整
已有 INTENT，并对原 prefix 的一致性保持原有检查。不能通过删除损坏 INTENT 或复制源
BUSINESS 整段修复。审查时已看到工作树增加此 precheck；对该工作树的相同临时 probe
得到 after=False，方向符合要求，尚需后继 clean commit 与新进程崩溃/损坏回归绑定。

### F2：Q11 将任何 G5 拒绝误当成零 eligible 例外（P1）

定位：`hosted_business_verification.py:343–356`。
每份报告的 gate severity 检查覆盖全部十一 gate，映射与现 ValidationService 一致；
gate 顺序由已解析的 ValidationReport 的严格 validator 固定。G5 以外拒绝与
NOT_EVALUATED 均拒绝。这部分实现符合冻结窄谓词。

问题在最终 `if rejected`：只要任意报告出现批准的 G5 拒绝，代码就强制 P14c 为
`FAILED/NOT_EVALUATED/SOURCE_INCOMPLETE`、无 selected candidate 且所有 disposition
为 NONPASS_VALIDATION。C11 明确允许“一或多个候选 PASS，其余符合窄 G5 拒绝谓词”
沿用原 P14c 选择。当前实现会拒绝一个 PASS 加一个批准 G5 拒绝的合法完整轨道。
在全部报告 PASS 时，旧分支还未显式要求 P14c native run_status=SUCCEEDED。

最小修复是区分零 PASS 和 mixed：只有零 PASS 且至少一个批准拒绝进入自然失败例外；
存在 PASS 时保留且核验原 P14c 结果，拒绝任何 source/sidecar 缺口导致的 native FAILED。
不要改写 P14c 或将它强制转为 NO_SELECTION。需要 all PASS、all 窄 G5 reject、
PASS+窄 G5 reject、其他 SOFT gate reject、HARD failure、severity 篡改的分支测试。
审查时工作树已开始按 passed_reports 分流，并增加正常 P14c 成功检查；未授予其资格。

### F3：生产 offline 导入尚未证明保存源是真实 live 来源（P1）

定位：`hosted_offline.py:53–54,85–95`，`hosted_replay.py:55–66`，
`hosted_verification.py:444–459`，`hosted_launcher.py:334`。
SavedHostedProtocol.load 核验 raw inventory、canonical journal/object/hash 和基本协议预算，
然后生产 REEXECUTE 路径即 bootstrap 和执行。该路径没有从管理 evidence/projection 根
调用现有 `TrustedLauncherEvidenceStore.verify_response_source`。指定 commit 全仓库的
调用点只有 launcher 组件测试；production live driver 保存了 source 工件，但没有独立
底向上核验它们后把验证身份绑定给此导入入口。

基本 accepted exchange 检查也没有核对 `exchange.host_observation_hash` 与 response 的
完整 HostObservation 及独立观察对象；reported configuration、外部 record 引用和原
实际捕获输出只因 envelope 自洽而存在，尚不能证明可信来源。纯 hash/标签的自洽协议不
等于“保存且已验证的 live 协议”。手写/Scripted 源能供现组件 fixture 重执行是合理测试，
但同样路径不能直接成为 canonical Q10 的已验证 source 导入。

最小修复：在生产 offline 初始化目标业务或执行前，从管理域只读保存来源根逐个核验
accepted response；复用现 verifier，固定原 D/S/R/I0/Pi/Ii、launcher binary/config/model
交接、原输出/提取 proposal、auth principal 和全部原 protocol hashes。
若外部管理 verifier 提前做此工作，导入必须实际核验其不可变绑定及完整源工件，不能只
接收 PASS/source 标签或 response 自报。增加 missing/fake source、交换 projection、
错误 observation hash、真实输出与 proposal 不符的 production-import 负例，要求目标
研究调用数为零。原 source read-only、原 bytes 不改，无法核验则停止。

当前 qualification verifier 对有协议证据的 case 仍返回 SCENARIO_PREDICATE_UNAVAILABLE /
NOT_EVALUATED，而非误授 PASS，这保留了最终资格安全边界；它不能填补此导入前置条件。

## 已落实的边界与尚需实际证据

* `hosted_python.c` 在任何 Python 初始化前检查 exec 环境 seed 精确为 `"0"`，使用
  isolated PyConfig 并显式 `use_hash_seed=1/hash_seed=0`。SetBytesArgv 已移到 SetBytesString
  之前，初始化错误停止；配置 write_bytecode=0，显式安装 signal handler。
  launcher 检查实际 flags，service bootstrap 再核验五项 flags 和 seed 环境。
* 管理 namespace `--clearenv` 后在 exec 前设 PYTHONHASHSEED=0，固定线程数值环境。
  管理服务命令固定 `/install/python-seeded -m quantos.infrastructure.hosted_service
  --profile-hash <hash>`；线上研究入口没有 replay-import/时钟/source root/任意 command 参数。
* manager 将 native binary、完整 Python 安装及初始化记录绑定到 install inventory 和 D。
  固定系统 gcc/libseccomp 路径 resolve 处理的是系统设施，不放宽 authority 文件的
  symlink/hardlink 规则。实际安装 namespace 和 libpython 解析仍须记录并通过 Q07。
* SUBMIT publication allowlist 排除 BUSINESS、trial/execution/results。每次新生成
  INTENT/COMPLETE 在持久化 journal 前比对保存源的同序 full canonical bytes；最后比较
  完整 protocol object 集合。原拒绝/冲突计数没有过滤，TERMINATE 明确拒绝支持。
* replay 时钟保留原 active R.issued_at，后继 ISSUE 使用原 anchor；不重走 live submit 或
  当前 auth/TTL。原 principal/time/budget bytes 留存，REEXECUTE 与 RECEIPT_REUSE 区分。
* run_offline 拒绝已有 target protocol/business/lock/observation 根；旧源 load 使用
  recover=False，并在正常结束重新检查源 raw inventory。当前源码没看到复制原结果供
  目标 execution adapter 复用的路径。
* offline 观察分别记录 execution adapter 与 Qlib Workflow 调用；receipt reuse 调用这两者
  立即失败，REEXECUTE 核对 execution 分母和非空 Workflow 记录。socket hooks 与服务
  namespace 网络隔离是实际无网络证据的组成部分，不能仅据 monkeypatch 授予门 PASS。
* principal comparison 仍只允许 C11 七种 schema 顶层 created_at。原 journal/receipt 没有
  新投影或差异排除。额外 Q09/Q10/Q11 场景验证器、真实 calls 和完整 bundle 尚须完成。

上述都是代码落实观察，不是 Q07/Q09/Q10/Q11 实际接受。此次独立测试使用临时 fixtures；
没有执行真实研究/live 模型，也没有消费 attempt02 的原始完整证据。
管理者报告 99 hosted tests 和 5 actual CPython tests 通过、完整 CI 仍在运行；本文未独立
重算其 saved check artifacts，不把该报告当资格通过。attempt01 的系统路径读取失败须继续
保留，不能由后继安装成功覆盖。

## 输入身份与后继审查义务

首次读取 HEAD 为 clean `5b31ec54407f590dcf15f9d74851fb8c7ace3dc8`；期间工作树变化已与
`git show` 原代码区分。下表 SHA-256 全从该 exact commit 的文件 bytes 重算。

| 文件（src/quantos/infrastructure/ 下） | SHA-256 |
|---|---|
| hosted_python.c | f377bf190c0dae6e02870c6c3cbf3ed0d75d8bcc12eac3d6feab70e2cf39f2a7 |
| hosted_store.py | c05a027270a59a401f8b207fb82e5c42b0f3c3b199c8f085eb3ca826c3efdfd3 |
| hosted_replay.py | 8d9b1fbb61107d15f67e22a17bdd9503b2cbc05599f3bf540c4ba89d7d1e8d48 |
| hosted_offline.py | 64b5db7d1944d31d43246ff5dfa196658ce0b226485b5efff4c7ff1c69a44830 |
| hosted_service.py | 28d588f7197f8b3a42ee4bf27d6ec4dbe82a324eaf7cdd06732e2b8764147d0d |
| hosted_manager.py | 869019560fa3ecf56cd4baba084ba5bce3dbe71da07de8e4900c740009e86b06 |
| hosted_verification.py | cde39ff5a98cfc2a6a1f0c8b08f85483c61d02b03e44e543d036aeaef11d291f |
| hosted_business_verification.py | d2b9c3e05bcacc3ee90610c398f82cf7c1f76349434193813ebe320996cabc37 |
| hosted_launcher.py | 70da913957f6acdce82ef54ddad85c7aa722ae35739b66be07e460826686df73 |

关闭发现需要新 exact clean commit、相应负例/崩溃回归、真实冻结安装的 Q07 探针、独立两根
Qlib 重执行、Q09 reuse 与保存 live 来源的完整 bottom-up bundle。此前实施澄清、这次代码
审查、功能 fixture 或 profitability 均不能代替该证据。整体保持 `NOT_QUALIFIED`。
