#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstring>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <sched.h>
#include <thread>
#include <unistd.h>
#include <vector>

using namespace std;

namespace fs = filesystem;
static atomic<bool> interrupted{false};
static void on_signal(int) { interrupted.store(true); }
static void write_file(const fs::path &path, const string &value) {
    ofstream out(path);
    out << value;
    out.flush();
    if (!out) throw runtime_error("write failed: " + path.string() + ": " + strerror(errno));
}
static string read_file(const fs::path &path) {
    ifstream in(path);
    if (!in) throw runtime_error("read failed: " + path.string());
    return string(istreambuf_iterator<char>(in), {});
}
static string start_identity(int pid) {
    string line = read_file("/proc/" + to_string(pid) + "/stat");
    istringstream fields(line.substr(line.rfind(')') + 2));
    string field;
    for (int i = 0; i <= 19; ++i) if (!(fields >> field)) throw runtime_error("bad process stat");
    return field;
}
static bool is_zombie(int pid) {
    const string line = read_file("/proc/" + to_string(pid) + "/stat");
    const auto position = line.rfind(')');
    return position != string::npos && line.size() > position + 2 && line[position + 2] == 'Z';
}
static vector<int> tids(int pid) {
    vector<int> result;
    for (const auto &entry : fs::directory_iterator("/proc/" + to_string(pid) + "/task"))
        result.push_back(stoi(entry.path().filename().string()));
    return result;
}
struct ThreadState { int tid; cpu_set_t affinity; int nice; };
class Change {
public:
    Change(int pid, string action, int value) : pid_(pid), action_(move(action)), value_(value), identity_(start_identity(pid)) {
        const string comm = read_file("/proc/" + to_string(pid) + "/comm");
        if (comm.rfind("coreflux-work", 0) != 0) throw runtime_error("target is not a CoreFlux workload");
        for (int tid : tids(pid)) {
            ThreadState state{tid, {}, 0};
            if (sched_getaffinity(tid, sizeof(state.affinity), &state.affinity)) throw runtime_error("get affinity failed");
            errno = 0;
            state.nice = getpriority(PRIO_PROCESS, tid);
            if (errno) throw runtime_error("get priority failed");
            original_.push_back(state);
        }
        if (original_.empty()) throw runtime_error("no target threads");
        if (action_ == "cgroup") {
            original_cgroup_ = read_file("/proc/" + to_string(pid_) + "/cgroup");
            const auto position = original_cgroup_.find("::");
            if (position == string::npos) throw runtime_error("cgroup v2 required");
            original_cgroup_ = original_cgroup_.substr(position + 2);
            original_cgroup_.erase(original_cgroup_.find_last_not_of("\n\r") + 1);
        }
    }
    string previous_state() const {
        if (action_ == "cgroup") return original_cgroup_;
        if (action_ == "nice") return to_string(original_.front().nice);
        string cpus;
        for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
            if (CPU_ISSET(cpu, &original_.front().affinity)) {
                if (!cpus.empty()) cpus += ',';
                cpus += to_string(cpu);
            }
        }
        return cpus;
    }
    ~Change() { try { restore(); } catch (const exception &e) { cerr << "rollback failed: " << e.what() << '\n'; } }
    void apply() {
        active_ = true;
        if (action_ == "affinity") {
            cpu_set_t allowed;
            if (sched_getaffinity(0, sizeof(allowed), &allowed) || value_ < 0 || value_ >= CPU_SETSIZE ||
                !CPU_ISSET(value_, &allowed)) throw runtime_error("CPU outside allowed set");
            cpu_set_t target;
            CPU_ZERO(&target);
            CPU_SET(value_, &target);
            for (const auto &state : original_) {
                if (sched_setaffinity(state.tid, sizeof(target), &target)) throw runtime_error("set affinity failed");
            }
        } else if (action_ == "nice") {
            if (value_ < 1 || value_ > 10) throw runtime_error("nice delta must be 1..10");
            for (const auto &state : original_) {
                if (state.nice + value_ > 19 || setpriority(PRIO_PROCESS, state.tid, state.nice + value_))
                    throw runtime_error("set priority failed");
            }
        } else if (action_ == "cgroup") {
            if (value_ < 10000 || value_ > 90000) throw runtime_error("quota must be 10000..90000 us");
            const fs::path root = "/sys/fs/cgroup";
            const string controllers = read_file(root / "cgroup.subtree_control");
            enabled_cpu_ = controllers.find("cpu") == string::npos;
            if (enabled_cpu_) write_file(root / "cgroup.subtree_control", "+cpu");
            group_ = root / ("coreflux-" + to_string(pid_));
            if (!fs::create_directory(group_)) throw runtime_error("cgroup already exists");
            write_file(group_ / "cpu.max", to_string(value_) + " 100000");
            write_file(group_ / "cgroup.procs", to_string(pid_));
        } else throw runtime_error("unknown action");
    }
    void restore() {
        if (!active_ && group_.empty()) return;
        bool same_process = false;
        try { same_process = start_identity(pid_) == identity_ && !is_zombie(pid_); } catch (...) {}
        if (same_process) {
            if (action_ == "affinity" || action_ == "nice") {
                for (int tid : tids(pid_)) {
                    auto found = find_if(original_.begin(), original_.end(), [tid](const auto &state) { return state.tid == tid; });
                    const auto &state = found == original_.end() ? original_.front() : *found;
                    if (action_ == "affinity") {
                        if (sched_setaffinity(tid, sizeof(state.affinity), &state.affinity))
                            throw runtime_error("restore affinity failed");
                    } else if (setpriority(PRIO_PROCESS, tid, state.nice))
                        throw runtime_error("restore priority failed");
                }
            } else if (action_ == "cgroup") {
                write_file(fs::path("/sys/fs/cgroup") / original_cgroup_.substr(1) / "cgroup.procs", to_string(pid_));
            }
        }
        if (!group_.empty()) {
            fs::remove(group_);
            group_.clear();
            if (enabled_cpu_) write_file("/sys/fs/cgroup/cgroup.subtree_control", "-cpu");
        }
        active_ = false;
    }
private:
    int pid_;
    string action_;
    int value_;
    string identity_;
    vector<ThreadState> original_;
    string original_cgroup_;
    fs::path group_;
    bool enabled_cpu_ = false;
    bool active_ = false;
};

int main(int argc, char **argv) {
    if (argc != 7 && argc != 8) {
        cerr << "usage: coreflux-policy PID affinity|nice|cgroup VALUE SECONDS DECISIONS.jsonl LOG.jsonl [--apply]\n";
        return 2;
    }
    try {
        const int pid = stoi(argv[1]), value = stoi(argv[3]), seconds = stoi(argv[4]);
        if (pid <= 1 || seconds < 1 || seconds > 30) throw invalid_argument("invalid PID or duration");
        const string action = argv[2];
        if (action != "affinity" && action != "nice" && action != "cgroup") throw invalid_argument("invalid action");
        string decisions = read_file(argv[5]);
        while (!decisions.empty() && (decisions.back() == '\n' || decisions.back() == '\r')) decisions.pop_back();
        decisions = decisions.substr(decisions.rfind('\n') == string::npos ? 0 : decisions.rfind('\n') + 1);
        if (decisions.find("\"state\":\"CONTENTION\"") == string::npos &&
            decisions.find("\"state\":\"SEVERE\"") == string::npos)
            throw invalid_argument("latest decision is not contention");
        Change change(pid, action, value);
        const bool apply = argc == 8 && string(argv[7]) == "--apply";
        if (argc == 8 && !apply) throw invalid_argument("expected --apply");
        ofstream log(argv[6], ios::app);
        if (!log) throw runtime_error("cannot open action log");
        log << "{\"pid\":" << pid << ",\"action\":\"" << action << "\",\"value\":" << value
            << ",\"previous\":\"" << change.previous_state() << "\",\"status\":\""
            << (apply ? "applying" : "dry_run") << "\"}\n";
        log.flush();
        if (!apply) { cout << "dry run: " << action << " " << value << " for PID " << pid << '\n'; return 0; }
        signal(SIGINT, on_signal);
        signal(SIGTERM, on_signal);
        change.apply();
        cout << "applied " << action << " to PID " << pid << endl;
        const auto deadline = chrono::steady_clock::now() + chrono::seconds(seconds);
        while (!interrupted.load() && chrono::steady_clock::now() < deadline)
            this_thread::sleep_for(chrono::milliseconds(50));
        change.restore();
        log << "{\"pid\":" << pid << ",\"action\":\"" << action << "\",\"status\":\"restored\"}\n";
        cout << "restored PID " << pid << '\n';
    } catch (const exception &e) {
        cerr << e.what() << '\n';
        return 1;
    }
}
