#!/usr/bin/env bash
# Run only in a privileged container with the prepared WSL kernel volume mounted.
set -euo pipefail
trap 'rm -f /tmp/coreflux-device; rmmod coreflux_main 2>/dev/null || true' EXIT
cd /kernel
mkdir -p phase2
cp /workspace/kernel/coreflux_main.c /workspace/kernel/Makefile phase2/
mkdir -p phase2/include/coreflux
cp /workspace/include/coreflux/uapi.h phase2/include/coreflux/
# The module Makefile resolves ../include; keep a copy at the build root.
mkdir -p include/coreflux
cp /workspace/include/coreflux/uapi.h include/coreflux/
make -C phase2 KDIR=/kernel/src
cc -Wall -Wextra -Werror -pthread -I/workspace/include /workspace/tests/kernel/ioctl_smoke.c -o phase2/ioctl_smoke
for round in 1 2 3; do
    insmod phase2/coreflux_main.ko
    minor=$(awk '$2 == "coreflux" {print $1}' /proc/misc)
    test -n "$minor"
    mknod /tmp/coreflux-device c 10 "$minor"
    phase2/ioctl_smoke /tmp/coreflux-device
    rm /tmp/coreflux-device
    rmmod coreflux_main
done
echo 'three module load/unload and ABI smoke rounds passed'
