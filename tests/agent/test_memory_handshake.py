import json
import subprocess
import sys


process = subprocess.Popen([sys.argv[1], "--mode", "random", "--seconds", "1", "--threads", "1", "--memory-mib", "4", "--controlled"],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
assert process.stdout.readline().strip() == "READY"
process.stdin.write("GO\n")
process.stdin.flush()
assert process.stdout.readline().strip() == "DONE"
process.stdin.write("STOP\n")
process.stdin.flush()
stdout, stderr = process.communicate(timeout=5)
assert process.returncode == 0, stderr
result = json.loads(stdout)
assert result["mode"] == "random" and result["memory_mib_per_thread"] == 4 and result["operations"] > 0
