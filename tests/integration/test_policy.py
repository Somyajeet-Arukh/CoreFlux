import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

binary, workload_binary = sys.argv[1:3]
fixture = tempfile.TemporaryDirectory(prefix="coreflux-policy-")
decisions = str(Path(fixture.name) / "decisions.jsonl")
Path(decisions).write_text('{"state":"CONTENTION"}\n')
log = str(Path(fixture.name) / "actions.jsonl")
affinity_cpu = min(os.sched_getaffinity(0))

def threads(pid):
    return [int(path.name) for path in Path(f"/proc/{pid}/task").iterdir()]

def group(pid):
    return Path(f"/proc/{pid}/cgroup").read_text().split("::", 1)[1].strip()

for action, value in (("affinity", str(affinity_cpu)), ("nice", "5"), ("cgroup", "50000")):
    workload = subprocess.Popen([workload_binary, "--mode", "cpu", "--seconds", "4", "--threads", "1"],
                                stdout=subprocess.DEVNULL)
    try:
        time.sleep(0.2)
        pid = workload.pid
        original_affinity = {tid: os.sched_getaffinity(tid) for tid in threads(pid)}
        original_nice = {tid: os.getpriority(os.PRIO_PROCESS, tid) for tid in threads(pid)}
        original_group = group(pid)
        command = [binary, str(pid), action, value, "1", decisions, log]
        subprocess.run(command, check=True, capture_output=True, text=True)
        assert all(os.sched_getaffinity(tid) == original_affinity[tid] for tid in original_affinity)
        policy = subprocess.Popen(command + ["--apply"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        message = policy.stdout.readline().strip()
        assert message.startswith("applied "), (message, policy.stderr.read())
        if action == "affinity":
            assert all(os.sched_getaffinity(tid) == {affinity_cpu} for tid in threads(pid))
        elif action == "nice":
            assert all(os.getpriority(os.PRIO_PROCESS, tid) == original_nice.get(tid, 0) + 5 for tid in threads(pid))
        else:
            assert group(pid).endswith(f"coreflux-{pid}")
            assert Path(f"/sys/fs/cgroup/coreflux-{pid}/cpu.max").read_text().startswith("50000 100000")
        stdout, stderr = policy.communicate(timeout=5)
        assert policy.returncode == 0, stderr
        assert "restored PID" in stdout
        assert all(os.sched_getaffinity(tid) == original_affinity.get(tid, original_affinity[pid]) for tid in threads(pid))
        assert all(os.getpriority(os.PRIO_PROCESS, tid) == original_nice.get(tid, original_nice[pid]) for tid in threads(pid))
        assert group(pid) == original_group
        assert not Path(f"/sys/fs/cgroup/coreflux-{pid}").exists()
        print(f"{action} apply and rollback passed")
    finally:
        workload.terminate()
        workload.wait(timeout=5)

entries = [json.loads(line) for line in Path(log).read_text().splitlines()]
assert sum(item["status"] == "restored" for item in entries) == 3

workload = subprocess.Popen([workload_binary, "--mode", "cpu", "--seconds", "4", "--threads", "1"],
                            stdout=subprocess.DEVNULL)
try:
    time.sleep(0.2)
    original = os.sched_getaffinity(workload.pid)
    policy = subprocess.Popen([binary, str(workload.pid), "affinity", str(affinity_cpu), "10", decisions, log, "--apply"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert policy.stdout.readline().startswith("applied ")
    policy.send_signal(signal.SIGTERM)
    stdout, stderr = policy.communicate(timeout=5)
    assert policy.returncode == 0, stderr
    assert "restored PID" in stdout
    assert os.sched_getaffinity(workload.pid) == original
    print("signal-triggered rollback passed")
finally:
    workload.terminate()
    workload.wait(timeout=5)

workload = subprocess.Popen([workload_binary, "--mode", "cpu", "--seconds", "1", "--threads", "1"],
                            stdout=subprocess.DEVNULL)
try:
    time.sleep(0.2)
    pid = workload.pid
    policy = subprocess.Popen([binary, str(pid), "cgroup", "50000", "2", decisions, log, "--apply"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert policy.stdout.readline().startswith("applied ")
    workload.wait(timeout=5)
    stdout, stderr = policy.communicate(timeout=5)
    assert policy.returncode == 0, stderr
    assert "restored PID" in stdout
    assert not Path(f"/sys/fs/cgroup/coreflux-{pid}").exists()
    print("target-exit cleanup passed")
finally:
    if workload.poll() is None:
        workload.terminate()
        workload.wait(timeout=5)
fixture.cleanup()
