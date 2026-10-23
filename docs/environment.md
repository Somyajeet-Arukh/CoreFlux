# Environment assessment

Checked on 23 October 2026. The runtime feasibility checks passed. Hardware performance counters are unavailable on this WSL host, so microarchitecture measurements need a different host.

## Verified environment

The workspace started empty. Ubuntu-24.04 is the default WSL 2 distribution. Its installed release is Ubuntu 24.04.2 LTS, running kernel `6.6.87.2-microsoft-standard-WSL2` on x86-64. Docker Desktop is also running in WSL, so changes to the shared WSL kernel require care and a planned restart.

| Capability | Observed result | Consequence |
| --- | --- | --- |
| C and C++ toolchain | gcc, g++, make and pkg-config present | Basic user-space development can begin |
| Kernel modules | CONFIG_MODULES=y; modules_disabled=0 | Matching test and CoreFlux modules built, loaded and unloaded successfully |
| Matching kernel build tree | Not installed in WSL; generated in isolated Docker volume | Module smoke test passed using that build |
| eBPF support | CONFIG_BPF, BPF_SYSCALL and BPF_EVENTS enabled | Program loading and scheduler-event delivery passed live smoke tests |
| Kernel BTF | /sys/kernel/btf/vmlinux present | Type information available for eBPF development |
| eBPF tools | clang, bpftool and libbpf development metadata absent | Install development dependencies before eBPF smoke test |
| Other tools | cmake and perf absent from PATH | Build orchestration and performance tooling need setup |
| Tracing and scheduler statistics | CONFIG_TRACEPOINTS and CONFIG_SCHEDSTATS enabled | Runtime access and event attachment still need verification |
| Resource control | cpuset, cpu, io, memory, hugetlb, pids and rdma controllers listed | Bounded affinity, priority and CPU-cgroup actions and rollback were tested in the resource-control integration checks |
| CPU performance counters | No standard cpu PMU listed; software and tracepoint sources present | Hardware cycles, instructions and IPC are not verified; do not promise these results on this host |
| perf permissions | perf_event_paranoid=2 | Some measurements require a privileged session |
| Privilege | Noninteractive sudo requires a password | Privileged setup and smoke tests need an authorized root session |

## Environment decision

Use a Docker development container for user-space and eBPF build work. A disposable container successfully resolved `archive.ubuntu.com` and fetched the Ubuntu release file on 23 October 2026, although the Ubuntu WSL distribution could not reach an IP address directly. The `coreflux-dev` image built successfully and a container verified Clang 18.1.3, libbpf 1.3.0 and bpftool. Build the image with `docker build -f Dockerfile.dev -t coreflux-dev .` and run it with `docker run --rm -it -v "${PWD}:/workspace" coreflux-dev` from PowerShell in the repository.

Docker Desktop uses the same `6.6.87.2-microsoft-standard-WSL2` kernel, and its distribution lacks an installed `/lib/modules/6.6.87.2-microsoft-standard-WSL2/build`. Microsoft source and the running configuration were used to generate matching build artifacts in an isolated Docker volume. Do not substitute generic Ubuntu kernel headers for the running Microsoft WSL kernel.

The eBPF smoke test passed in a disposable privileged container: `tests/smoke/sched_switch.bpf.c` compiled with Clang, loaded into the running WSL kernel, and `tests/smoke/attach_sched_switch.c` attached it to the `sched/sched_switch` tracepoint, received scheduler records through a BPF ring buffer, then detached it cleanly. Tracefs needed to be mounted inside the container for libbpf to locate the tracepoint event ID. This verifies end-to-end eBPF event delivery on the current WSL kernel.

The Docker image now provides the eBPF dependencies. The matching kernel build tree and symbol table are in the `coreflux-kernel-build` Docker volume. Do not switch the shared WSL kernel silently.

The running kernel is `6.6.87.2-microsoft-standard-WSL2` and reports `CONFIG_MODVERSIONS=y`. Microsoft's matching source tag is `linux-msft-wsl-6.6.87.2`; its source, generated headers and symbol version data are retained in the isolated Docker volume. The smoke module source and Makefile are in `tests/smoke/`.

A further local check found no installed VirtualBox, VMware, Multipass or Hyper-V command, and no initially installed `Module.symvers` or generated kernel headers. Microsoft's `linux-msft-wsl-6.6.87.2` source was downloaded into the isolated Docker volume `coreflux-kernel-build`. Using `/proc/config.gz`, a full `vmlinux` build and the kernel `modules` target generated `Module.symvers`. The resulting kernel release matched `6.6.87.2-microsoft-standard-WSL2`. The minimal `tests/smoke/coreflux_hello.c` module then compiled with matching vermagic, loaded into the running kernel, appeared in `/proc/modules`, and unloaded cleanly. The running WSL kernel image was not replaced.

Final CPU microarchitecture experiments need a host that actually exposes the required counters. WSL results must retain virtualization and host-load limitations in the experiment metadata.

## Runtime feasibility checks

- Minimal module build, load and unload: passed against the running WSL kernel.
- eBPF compile, load, attach, ring-buffer event delivery and detach: passed.
- Software performance counter: `perf stat -e task-clock -- true` passed in a privileged container.
- Hardware counters: no standard CPU PMU exposed by WSL; native-Linux measurement remains optional experimental work outside the module telemetry characterization scope.
- Cgroup controllers are present. The policy integration checks later verified bounded CPU-cgroup changes and rollback in the privileged container setup.
- Build and test tools are captured in `Dockerfile.dev`; kernel source and build artifacts remain in the `coreflux-kernel-build` Docker volume.

## Setup attempt and current blocker

An authorized root session was available through WSL. Dependency setup was attempted for clang, LLVM, libbpf, libelf, zlib, CMake and Linux performance tools. The package-index download produced no output or progress and was stopped before the install step. A bounded retry also failed to complete successfully. Bounded hostname lookups for archive.ubuntu.com and security.ubuntu.com returned no addresses. This points to a WSL name-resolution or network-access problem; its precise cause has not yet been established. No successful dependency installation is claimed.

Further diagnosis: Windows successfully resolved `archive.ubuntu.com` to IPv4 addresses, while WSL reported `No route to host` when connecting directly to `1.1.1.1:80`. WSL has an IPv4 default route via `172.27.128.1` and an automatically generated resolver at `10.255.255.254`. This is a wider WSL networking failure, not solely a DNS failure. Replacing `/etc/resolv.conf` alone would not address the direct connection failure. The Docker Desktop WSL distribution is running, so a global WSL shutdown or network-mode change should be planned rather than performed silently.

Docker network access allowed the environment setup to complete despite the Ubuntu WSL distribution's direct network failure. Restoring that distribution's connectivity may improve convenience later, but it is not a gate for the chosen container workflow.

## Repeating the inventory

From the repository in Linux, run `bash scripts/check-environment.sh`. It reads environment information without installing packages, loading modules, changing cgroups or changing kernel settings. This is an inventory, not a pass/fail substitute for runtime smoke tests.
