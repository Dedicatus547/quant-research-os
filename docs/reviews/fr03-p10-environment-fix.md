# FR-03 网络探针环境修正

后续更新：用户授权后，`v4-env1` 已完成一次真实 P10，9/9 通过；
详见[真实执行结果](fr03-p10-env1-live-result.md)。FR-03 总体仍为 NO_GO。
以下保留授权前的环境修正记录；“尚未执行”等描述对应当时状态。

2026-10-12。**环境修正完成，9个局部离线用例通过；SDK/runtime仍为0.162.1。**
没有升级alpha5、真实模型调用、科学作业或共享资源写入。FR-03保持NO_GO；
[旧v4真实结果](fr03-p10-v4-resume-result.md)仍为7/9。

## 修改

新增独立输入目录 [p10_codex_workspace_v4_env1](../../tests/fixtures/p10_codex_workspace_v4_env1/task.md)。
10个输入中只有网络探针和任务说明不同；原v4输入、执行器、SDK adapter、normalizer和判分源码不变。
后继输入称为 `v4-env1`，复用v4 schema，通过新的fixture/spec哈希区分运行。

[network_probe.py](../../tests/fixtures/p10_codex_workspace_v4_env1/network_probe.py)现在先核验固定
`/usr/bin/env` 的SHA256，再替换当前进程，以 `/usr/bin/env -i` 和绝对路径
`/usr/bin/python3 -I -S` 重新进入自身。两侧仍使用相同的既有探针命令，入口统一建立：

```text
LANG=C.UTF-8
PATH=/usr/bin:/bin
TZ=UTC
```

重新进入后先检查**实际完整环境**是否恰好等于这三项，再执行原四项socket操作。
输出仍从实际进程读取；未知参数、启动器身份变化、环境不一致均在socket操作前失败。
固定启动器哈希写在受输入哈希约束的探针中，每次初始进入都检查。
重启仅作用于网络探针进程；秘密标记、写入和恢复命令保持原流程。
严格PATH比较、四项EPERM要求、前后对照、完成顺序及9/9分母均未放宽。

## 验证和留证

[局部测试](../../tests/unit/test_p10_probe_environment.py)使用实际 `/usr/bin/env`、系统Python3.10
和zsh，模拟shell启动增加PATH前缀；socket和SDK全部替换为模拟结果。
每次子解释器进入还安装audit hook，禁止真实socket操作。验证包括：

- 直接启动与经过shell启动得到相同的实际环境；成功、EPERM和其他errno仍正确区分。
- 环境建立失败不产生有效socket观察；网络子进程清理环境不会让独立秘密检查假通过。
- 已有管理侧前后对照、导出和复验可直接复用；故意制造内层PATH差异仍判NO_GO。

9个用例通过，lint和格式检查通过。首轮测试桩的字面量比较触发Python警告，已修正；
原失败日志保留。没有重跑全套CI或旧科学作业。

本worktree的 `artifacts/workstreams/fr03-environment-fix-20261012/` 保留测试日志、
204个既有源码/fixture文件不变的核对结果、实施记录、新准备记录和待执行方案。
现有执行实现哈希仍为 `710608c077ef1c6be69e29a5308625709379e9e50138298d20eb4f77b3c2dab8`。
新spec哈希为 `0488c8ecf093cee9e2058c84b3cac2df8db576b9c2162c6688881941694741c9`。

## 后续边界

用户本轮要求先修正环境；新输入尚未进行真实P10，资格为NOT_EVALUATED。
已有wrapper可通过指定新fixture和新准备记录执行；[具体方案](../../artifacts/workstreams/fr03-environment-fix-20261012/execution-plan.json)
尚未启动。真实执行需要另行授权，并在启动时复核输入、原预检依赖和共享资源。
计划复用已通过的独立账户预检，保持一次模型turn、零重试、SDK900秒、前后对照各5秒，
256MiB持久增长、64MiB scratch硬限、1.5GiB串行内存预算；token仍是事后验收阈值。
原报告和资格结论不会因本次离线测试通过而改变。
