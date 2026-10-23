#!/usr/bin/env bash
# Read-only capability inventory. Run inside the target Linux environment.
set -u
section() { printf '\n## %s\n' "$1"; }
section 'Operating system'
uname -a
cat /etc/os-release
id
section 'Build and analysis tools'
for tool in gcc g++ make clang llvm-strip bpftool perf cmake pkg-config; do
    command -v "$tool" || printf 'MISSING: %s\n' "$tool"
done
pkg-config --modversion libbpf 2>/dev/null || echo 'MISSING: libbpf development package'
section 'Matching kernel build directory'
if test -d "/lib/modules/$(uname -r)/build"; then
    ls -ld "/lib/modules/$(uname -r)/build"
else
    echo 'MISSING: matching kernel build tree'
fi
section 'Kernel configuration'
if test -r /proc/config.gz; then
    zcat /proc/config.gz | grep -E '^CONFIG_(MODULES|MODVERSIONS|BPF|BPF_SYSCALL|BPF_EVENTS|DEBUG_INFO_BTF|TRACEPOINTS|PERF_EVENTS|CGROUPS|SCHEDSTATS)='
else
    echo 'UNVERIFIED: /proc/config.gz unavailable'
fi
section 'BTF and scheduler tracepoints'
ls -l /sys/kernel/btf/vmlinux 2>/dev/null || true
for root in /sys/kernel/tracing /sys/kernel/debug/tracing; do
    if test -r "$root/events/sched/sched_switch/format"; then
        cat "$root/events/sched/sched_switch/format"
    fi
done
section 'Resource controllers'
cat /sys/fs/cgroup/cgroup.controllers 2>/dev/null || true
section 'Performance counter sources and restrictions'
ls /sys/bus/event_source/devices
cat /proc/sys/kernel/perf_event_paranoid
section 'Module loading restriction'
cat /proc/sys/kernel/modules_disabled
section 'Noninteractive privilege availability'
if sudo -n true 2>/dev/null; then
    echo 'Passwordless sudo available'
else
    echo 'Privileged tests require a separately authorized root session'
fi
echo 'Inventory only: presence does not prove successful module or BPF loading.'
