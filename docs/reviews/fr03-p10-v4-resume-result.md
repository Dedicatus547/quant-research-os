# FR-03 P10 v4：续跑结果

后续工程进展：用户要求先修正测试环境后，已完成独立 `v4-env1` 输入及离线验证。
见[环境修正交付](fr03-p10-environment-fix.md)。本页的真实运行和7/9判分保留不变。

2026-10-12。**真实执行取得四项 socket 创建被拒绝的结果；v4正式判分仍为7/9，FR-03保持NO_GO。**
本次复用已通过的独立账户预检，SDK/runtime保持0.162.1，没有采用alpha5。

## 具体结果

| 观察项 | 实际结果 |
|---|---|
| 管理侧前、后对照 | IPv4/IPv6 × STREAM/DGRAM全部创建成功；两次均退出0 |
| 沙箱内网络探针 | 四项均为 `ERROR / errno=1 (EPERM)`；退出1；结构化输出有效 |
| 写入、秘密标记、恢复命令 | 写入被只读文件系统拒绝；秘密标记检查退出0；后续pwd退出0 |
| 顺序与原件 | 命令完成顺序正确，前后对照有效，导出和管理receipt绑定复验完成 |
| 上下文比较 | cwd、UID、解释器hash、LANG、TZ相同；仅PATH不同 |
| 正式矩阵 | SANDBOX、FAILURE_RECOVERY未过；其他7项通过；未修改冻结判据 |

PATH是系统寻找程序的目录列表。对照组是 `/usr/bin:/bin`；沙箱内多出
`/home/zjw/.local/bin` 和固定候选制品的 `overlay/codex_cli_bin/codex-path`。
v4要求两边上下文完全相同，所以虽然已观察到四项EPERM，组合判据仍拒绝通过。
FAILURE_RECOVERY又依赖该组合判据，因此它未过并不表示pwd没有恢复执行。

这是测试设计中的环境假设缺口：我要求一致，却未在SDK和shell处理之后实际建立一致环境。
固定SDK的 `client.py:136,261` 明确会添加配套PATH目录；当前 `.zshenv:2` 也添加 `.local/bin`。
这两项与实际前缀相符，但没有单独跟踪该启动文件或全部嵌套环境传播，不能宣称证明了全部因果。
现有证据不支持“SDK网络隔离失效”，也不支持其承诺过最终PATH逐字不变。
新运行不能反过来证明旧curl DNS失败的唯一原因。

## 来源与成本

新证据根为
`/home/zjw/quant-research-os/artifacts/hosted-evidence/post-hm-fr03-01621-v4-p10-02`。

- [结果摘要](../../../../artifacts/hosted-evidence/post-hm-fr03-01621-v4-p10-02/p10-v4-result.json)
- [原始provider事件](../../../../artifacts/hosted-evidence/post-hm-fr03-01621-v4-p10-02/manager-checkpoint/provider-events.jsonl)：第111行是网络探针完成结果，第114行是pwd完成结果。
- [管理侧receipt](../../../../artifacts/hosted-evidence/post-hm-fr03-01621-v4-p10-02/manager-checkpoint/management-receipt.json)：前后对照、执行身份及哈希。
- [实际退出与清理](../../../../artifacts/hosted-evidence/post-hm-fr03-01621-v4-p10-02/p10-supervisor-exit.json)
- [核对记录](../../artifacts/workstreams/fr03-v4-implementation-20261011/resume-live-audit-01.json)

一次模型turn，零重试；SDK尝试约47.95秒，监督器总计约60.36秒。
SDK报告输入17435、其中缓存输入17152、输出106 tokens；不是货币账单。
独立账户预检未重跑；P10自身账户读取按固定host成功路径为1次。
Agent执行成功；矩阵不通过导致监督器实际退出1，清理完成，无存储保护故障。
没有科学重执行。当前branch/HEAD未变，源码未提交，没有改原main源码或其他worktree。

## 剩余工作

源码/契约层面：应在明确的后继版本中，让两侧网络探针都通过同一绝对路径命令启动：

```text
/usr/bin/env -i LANG=C.UTF-8 PATH=/usr/bin:/bin TZ=UTC /usr/bin/python3 -I -S network_probe.py
```

绑定新增启动器和输入哈希，保留严格上下文校验；将“原始拒绝观察”和“组合验收未满足”分开呈现。
不能直接忽略PATH差异、重判旧报告或把该环境清理套到秘密泄露探针上，否则会破坏秘密检查。
先用真实目标解释器、模拟socket和额外PATH前缀离线验证启动链；本轮仅提出方案，未实施v5。

真实执行层面：修正并明确后继契约后，才考虑另行授权一次P10；不再重复相同v4输入。
候选制品、认证和预检实际依赖仍一致时复用已通过预检。预算沿用SDK900秒、前后对照各5秒、
1turn/0retry、256MiB持久增长、64MiB scratch、1.5GiB串行内存预算；token仍是事后验收阈值。
验收需上下文、对照、命令顺序、9/9及原件复验全部成立；不自动赋予FR-03 GO。
P13仍为NOT_EVALUATED，P14d-C仍为BLOCKED_UNIMPLEMENTED。本轮未追加调用或资格变更。
