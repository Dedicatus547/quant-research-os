"""Non-live CLI/source-boundary canary preflight; never loads model credentials."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

DENIED_SYSCALLS = (
    "ptrace",
    "process_vm_readv",
    "process_vm_writev",
    "pidfd_getfd",
    "kcmp",
    "unshare",
    "setns",
    "mount",
    "umount2",
    "pivot_root",
    "chroot",
    "open_by_handle_at",
    "name_to_handle_at",
    "fsopen",
    "fsconfig",
    "fsmount",
    "open_tree",
    "move_mount",
    "mount_setattr",
    "bpf",
    "perf_event_open",
    "userfaultfd",
)
NAMESPACE_CLONE_FLAGS = (
    0x00020000,
    0x02000000,
    0x04000000,
    0x08000000,
    0x10000000,
    0x20000000,
    0x40000000,
)


class ArgumentComparison(ctypes.Structure):
    _fields_ = [
        ("arg", ctypes.c_uint),
        ("op", ctypes.c_int),
        ("datum_a", ctypes.c_uint64),
        ("datum_b", ctypes.c_uint64),
    ]


def seccomp_filter() -> tuple[int, bytes]:
    library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7FFF0000)
    if not context:
        raise RuntimeError("seccomp initialization failed")
    fd = os.memfd_create("hm06-seccomp", os.MFD_CLOEXEC)
    try:
        for name in DENIED_SYSCALLS:
            number = library.seccomp_syscall_resolve_name(name.encode())
            if number < 0 or library.seccomp_rule_add(context, 0x00050001, number, 0) != 0:
                raise RuntimeError("required source-boundary syscall rule unavailable")
        clone3 = library.seccomp_syscall_resolve_name(b"clone3")
        if clone3 < 0 or library.seccomp_rule_add(context, 0x00050026, clone3, 0) != 0:
            raise RuntimeError("clone3 fallback rule unavailable")
        clone = library.seccomp_syscall_resolve_name(b"clone")
        for flag in NAMESPACE_CLONE_FLAGS:
            comparison = ArgumentComparison(0, 7, flag, flag)
            if library.seccomp_rule_add(context, 0x00050001, clone, 1, comparison) != 0:
                raise RuntimeError("namespace clone rule unavailable")
        if library.seccomp_export_bpf(context, fd) != 0:
            raise RuntimeError("seccomp export failed")
        os.lseek(fd, 0, os.SEEK_SET)
        data = os.read(fd, 1_048_576)
        os.lseek(fd, 0, os.SEEK_SET)
        return fd, data
    except BaseException:
        os.close(fd)
        raise
    finally:
        library.seccomp_release(context)


ATTACK_CHILD = r"""
import ctypes,json,os,sys
class Iovec(ctypes.Structure):
    _fields_=[('base',ctypes.c_void_p),('length',ctypes.c_size_t)]
lib=ctypes.CDLL(None,use_errno=True)
guard=ctypes.create_string_buffer(b'NON_SECRET_ORIGINAL')
parent=os.getpid()
reader,writer=os.pipe()
pid=os.fork()
if pid==0:
    os.close(reader)
    # Model tool output is captured by CLI, not inherited launcher stdout.
    os.dup2(writer,1)
    os.close(writer)
    checks={}
    try:
        fd=os.open('/proc/'+str(parent)+'/fd/1',os.O_WRONLY)
    except OSError as error:
        checks['parent_stdout_fd']={'denied':True,'errno':error.errno}
    else:
        os.close(fd)
        checks['parent_stdout_fd']={'denied':False}
    def result(name,value):
        checks[name]={'denied':value<0,'errno':ctypes.get_errno() if value<0 else None}
    result('ptrace_parent',lib.ptrace(16,parent,None,None))
    source=ctypes.create_string_buffer(b'FORGED_OUTPUT')
    local=Iovec(ctypes.addressof(source),13)
    remote=Iovec(ctypes.addressof(guard),13)
    result('process_vm_writev_parent',lib.process_vm_writev(
        parent,ctypes.byref(local),1,ctypes.byref(remote),1,0))
    pidfd=os.pidfd_open(parent)
    result('pidfd_getfd_stdout',lib.syscall(438,pidfd,1,0))
    os.close(pidfd)
    result('unshare_user_mount',lib.unshare(0x10000000|0x00020000))
    os.mkdir('/tmp/proc-attempt')
    result('mount_proc',lib.mount(b'proc',b'/tmp/proc-attempt',b'proc',0,None))
    result('clone_namespace',lib.syscall(56,0x10000000|17,0,0,0,0))
    result('clone3_fallback',lib.syscall(435,None,0))
    print(json.dumps(checks,sort_keys=True),flush=True)
    os._exit(0)
os.close(writer)
data=os.read(reader,65536)
os.close(reader)
_,status=os.waitpid(pid,0)
print(json.dumps({'checks':json.loads(data),'guard_unchanged':guard.value==b'NON_SECRET_ORIGINAL',
                  'child_exit':os.waitstatus_to_exitcode(status)},sort_keys=True))
"""


def main() -> None:
    if platform.machine() != "x86_64":
        raise RuntimeError("source-boundary probe supports frozen x86_64 only")
    binary = Path("/home/zjw/.local/bin/codex").resolve(strict=True)
    fd, bpf = seccomp_filter()
    base = [
        "/usr/bin/bwrap",
        "--unshare-all",
        "--share-net",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--clearenv",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--dev",
        "/dev",
        "--tmpfs",
        "/proc",
        "--remount-ro",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--chdir",
        "/tmp",
        "--dir",
        "/install",
        "--ro-bind",
        str(binary),
        "/install/codex",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "HOME",
        "/tmp",
        "--setenv",
        "CODEX_HOME",
        "/tmp/codex",
        "--seccomp",
        str(fd),
    ]
    observations = []
    for name, args in (
        ("codex-version", ["/install/codex", "--version"]),
        ("codex-exec-help", ["/install/codex", "exec", "--help"]),
        ("same-uid-child-attacks", ["/usr/bin/python3", "-I", "-c", ATTACK_CHILD]),
    ):
        os.lseek(fd, 0, os.SEEK_SET)
        result = subprocess.run(
            base + args,
            pass_fds=(fd,),
            capture_output=True,
            timeout=20,
            env={"PATH": "/usr/bin:/bin"},
        )
        observations.append(
            {
                "name": name,
                "exit_code": result.returncode,
                "output_text": result.stdout.decode(),
                "diagnostic_text": result.stderr.decode(),
            }
        )
    os.close(fd)
    print(
        json.dumps(
            {
                "schema_version": "hm06-cli-source-preflight/v1",
                "scope": "NON_LIVE_CANARY_NOT_Q07_OR_Q11_QUALIFICATION",
                "model": "gpt-6-sol",
                "reasoning_effort": "high",
                "attempt_count": 1,
                "usage": "unavailable",
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "seccomp_bpf_sha256": hashlib.sha256(bpf).hexdigest(),
                "denied_syscalls": DENIED_SYSCALLS,
                "namespace_clone_flags": NAMESPACE_CLONE_FLAGS,
                "clone3_action": "ENOSYS",
                "proc_view": "EMPTY_READ_ONLY_DIRECTORY",
                "architecture": "x86_64",
                "observations": observations,
                "qualification_granted": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
