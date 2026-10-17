# 历史事实投影与只读收尾：主线采用范围

2026-10-18。适合合入主线作为已实现、已定向离线验证的工程能力。
获授权 N4 只观察到真实首次 STOP 及自动收尾；新提案、科学执行、本任务反馈后决策与修订仍待证。
换手率问题没有实验答案，资格保持 `NOT_QUALIFIED`，P14d-C 不变。

## 身份与采用

- 合并前主线：`ca1b6031bce9fe12f39e8a6961eee05667cb8c46`；读取远端后与 origin/main 一致。
- 主仓四份规划原稿按原字节先保存为 `a52b6db5dfbe0d7d59221cf4ee286216a29e8e67`，原待实施文本可从该提交读取。
- 固定开发与真实运行源码：`b0725b7c88a3d255eda61d0010cf291fba6f330a`，
  分支 `work/adaptive-closure-20261018`。保留该工作树、运行包、失败与证据的原身份。
- 普通 merge 保留开发父提交。生产源码、scripts、测试、依赖与工作流采用开发提交原字节；
  合并只更新当前文档。唯一 add/add 冲突是规划页的旧/新状态头，原规划正文保持。
- 本次用户授权提交、合并并推送；没有部署、移动历史 tag、升级环境、额外模型或科学执行。
  实际合并提交、推送及远端确认见本机[集成交接](../../artifacts/adaptive-closure-20261018/integration-01/handoff.md)。

N1 对新 v2 recipe 进行原件哈希、batch/引用集合、白名单字段及精确值核验，生成有限 context；
推断单独标记，保留 null、科学 REJECT 和执行 FAILED/NOT_EVALUATED。
N2 复用 capture、receipt 和反馈核验，以只读入口输出分项观察及独立库存；缺件不补写，
UNKNOWN 不重发，已完成科学不重复执行，STOP 和科学判据不变。
既有 AR0–AR5、Qlib、科学执行/门、历史失败和资格不重新实现或重分类。

## 已有验证按实际依赖采用

合并只涉及文档，未重新运行测试、完整 CI、资格矩阵或科学任务。
合并前核对源码/脚本/测试/依赖树与固定开发提交一致，并核对以下 JUnit 哈希；
不把既有通过改标成合并提交重新执行。

| 原件 | SHA256 / 范围 |
|---|---|
| [N1 定向 JUnit](../../artifacts/adaptive-closure-20261018/n1/junit-01.xml) | `c33c44e2f3c0af166551aeb3eb49afc17ade3d2c5c8d1fd1d85a54b23b4be175`；20 项 |
| [N2/包最终源码 JUnit](../../artifacts/adaptive-closure-20261018/n3/junit-final-source.xml) | `255cde833cd4a16f4abd212b2ce9615e68ddf996b5e53063ddd40bf7c5568a90`；21 项 |
| [采用与源码记录](../../artifacts/adaptive-closure-20261018/n3/local-verification.json) | 合计 41 个不同用例；受影响源码 Pyright 与 Ruff 通过 |

反例覆盖原件替换、null 填零、失败改成功、未 pin 引用、缺 receipt/第二响应/科学退出、
串任务反馈、错 operation 的 guard、错 thread/turn echo、PASS 子串误认等；
正例覆盖模拟的科学后 STOP 及两次完成科学后的预算停止。
原 61 用例保留原 originating tuple，不合并计作新的全量通过；失败尝试与修复记录不删除。
远端 push 可能触发仓库原有 CI，结果须绑定实际 checkout，不能从基线或本地定向验证继承。

## 真实观察与未证明范围

任务 `2b573b7595b83e03c152781a0453a2424d74235c903f637a61b2e8a813c5f950`
收到一次真实 SDK STOP。实际为 SDK 1/2、新候选 0/2、科学 0/2，
policy units 消耗和占用均 0/36。retry、UNKNOWN 重发、科学 restart、管理恢复均 0。
23 字段 / 6163 字符历史投影进入实际请求，完成 thread/turn 的 provider user echo 对应。
自动收尾 `issues=[]`、`input_stable=true`；SDK、controller、operator、guard 与外层 observer
退出均 0，namespace/waitpid/cleanup 已核对，最终 93 份库存闭合。

模型建议保留暂停；这不是全部允许结构失败的科学证明，也没有回答新结构是否满足换手阈值。
模型对历史父 FAILED/NOT_EVALUATED 的 execution-failure 措辞保持原样，但只采用原 selection 的
`SOURCE_INCOMPLETE`，不提升为科学进程崩溃证据。两份历史 Validation 的科学 REJECT 分别保留。

真实新 AST→科学→本任务反馈→后继决策及修订仍 `NOT_OBSERVED`；
反馈因果改善、长期可靠、跨宿主、sealed 或历史 vendor-vintage PIT 均未证明。
新旧两个任务各自首次 STOP，不能拼成同任务两步反馈证据。

## 原件及终态边界

原件留在本机持久 `artifacts/adaptive-closure-20261018/`，不随 Git 上传数据或 SDK 原始记录。

| 原件 | SHA256 |
|---|---|
| [N4 机器收尾](../../artifacts/adaptive-closure-20261018/authorized-run-01/closeout.json) | `a28f156065e400121d8a8929b0f528013b2be070ffb3375a46ecc5ddd7c42621` |
| [N4 完成库存](../../artifacts/adaptive-closure-20261018/authorized-run-01/evidence-inventory-completed.json) | `e17073c6caba97ac0e23e971ae6308bc515215702962186e5c85f65776e99484` |
| [自动收尾](../../artifacts/adaptive-closure-20261018/package-01-audits/20261017T182801134590Z/result.json) | 逐项观察、核验源码与原件引用 |
| [运行交接](../../artifacts/adaptive-closure-20261018/runtime-handoff.md) | 本次终态与独立退出入口 |

原[离线交付](adaptive-closure-offline-2026-10-18.md)、原运行包及提示词保留准备时点；
“待授权”不覆盖本次已完成 STOP。两个终态包均不按旧提示词重跑，剩余机会不自动续用或转移。
任何新实验先说明未解决的问题及必要检验，再准备新的具体包和授权。
