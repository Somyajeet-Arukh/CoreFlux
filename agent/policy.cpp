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

namespace fs = std::filesystem;
static std::atomic<bool> interrupted{false};
static void on_signal(int) { interrupted.store(true); }
static void write_file(const fs::path &path, const std::string &value) {
    std::ofstream out(path);
    out << value;
    out.flush();
    if (!out) throw std::runtime_error("write failed: " + path.string() + ": " + std::strerror(errno));
}
static std::string read_file(const fs::path &path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("read failed: " + path.string());
    return std::string(std::istreambuf_iterator<char>(in), {});
}
static std::string start_identity(int pid) {
    std::string line = read_file("/proc/" + std::to_string(pid) + "/stat");
    std::istringstream fields(line.substr(line.rfind(')') + 2));
    std::string field;
    for (int i = 0; i <= 19; ++i) if (!(fields >> field)) throw std::runtime_error("bad process stat");
    return field;
}
static bool is_zombie(int pid) {
    const std::string line = read_file("/proc/" + std::to_string(pid) + "/stat");
    const auto position = line.rfind(')');
    return position != std::string::npos && line.size() > position + 2 && line[position + 2] == 'Z';
}
static std::vector<int> tids(int pid) {
    std::vector<int> result;
    for (const auto &entry : fs::directory_iterator("/proc/" + std::to_string(pid) + "/task"))
        result.push_back(std::stoi(entry.path().filename().string()));
    return result;
}
struct ThreadState { int tid; cpu_set_t affinity; int nice; };
class Change {
public:
    Change(int pid, std::string action, int value) : pid_(pid), action_(std::move(action)), value_(value), identity_(start_identity(pid)) {
        const std::string comm = read_file("/proc/" + std::to_string(pid) + "/comm");
        if (comm.rfind("coreflux-work", 0) != 0) throw std::runtime_error("target is not a CoreFlux workload");
        for (int tid : tids(pid)) {
            ThreadState state{tid, {}, 0};
            if (sched_getaffinity(tid, sizeof(state.affinity), &state.affinity)) throw std::runtime_error("get affinity failed");
            errno = 0;
            state.nice = getpriority(PRIO_PROCESS, tid);
            if (errno) throw std::runtime_error("get priority failed");
            original_.push_back(state);
        }
        if (original_.empty()) throw std::runtime_error("no target threads");
        if (action_ == "cgroup") {
            original_cgroup_ = read_file("/proc/" + std::to_string(pid_) + "/cgroup");
            const auto position = original_cgroup_.find("::");
            if (position == std::string::npos) throw std::runtime_error("cgroup v2 required");
            original_cgroup_ = original_cgroup_.substr(position + 2);
            original_cgroup_.erase(original_cgroup_.find_last_not_of("\n\r") + 1);
        }
    }
    std::string previous_state() const {
        if (action_ == "cgroup") return original_cgroup_;
        if (action_ == "nice") return std::to_string(original_.front().nice);
        std::string cpus;
        for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
            if (CPU_ISSET(cpu, &original_.front().affinity)) {
                if (!cpus.empty()) cpus += ',';
                cpus += std::to_string(cpu);
            }
        }
        return cpus;
    }
    ~Change() { try { restore(); } catch (const std::exception &e) { std::cerr << "rollback failed: " << e.what() << '\n'; } }
    void apply() {
        active_ = true;
        if (action_ == "affinity") {
            cpu_set_t allowed;
            if (sched_getaffinity(0, sizeof(allowed), &allowed) || value_ < 0 || value_ >= CPU_SETSIZE ||
                !CPU_ISSET(value_, &allowed)) throw std::runtime_error("CPU outside allowed set");
            cpu_set_t target;
            CPU_ZERO(&target);
            CPU_SET(value_, &target);
            for (const auto &state : original_) {
                if (sched_setaffinity(state.tid, sizeof(target), &target)) throw std::runtime_error("set affinity failed");
            }
        } else if (action_ == "nice") {
            if (value_ < 1 || value_ > 10) throw std::runtime_error("nice delta must be 1..10");
            for (const auto &state : original_) {
                if (state.nice + value_ > 19 || setpriority(PRIO_PROCESS, state.tid, state.nice + value_))
                    throw std::runtime_error("set priority failed");
            }
        } else if (action_ == "cgroup") {
            if (value_ < 10000 || value_ > 90000) throw std::runtime_error("quota must be 10000..90000 us");
            const fs::path root = "/sys/fs/cgroup";
            const std::string controllers = read_file(root / "cgroup.subtree_control");
            enabled_cpu_ = controllers.find("cpu") == std::string::npos;
            if (enabled_cpu_) write_file(root / "cgroup.subtree_control", "+cpu");
            group_ = root / ("coreflux-" + std::to_string(pid_));
            if (!fs::create_directory(group_)) throw std::runtime_error("cgroup already exists");
            write_file(group_ / "cpu.max", std::to_string(value_) + " 100000");
            write_file(group_ / "cgroup.procs", std::to_string(pid_));
        } else throw std::runtime_error("unknown action");
    }
    void restore() {
        if (!active_ && group_.empty()) return;
        bool same_process = false;
        try { same_process = start_identity(pid_) == identity_ && !is_zombie(pid_); } catch (...) {}
        if (same_process) {
            if (action_ == "affinity" || action_ == "nice") {
                for (int tid : tids(pid_)) {
                    auto found = std::find_if(original_.begin(), original_.end(), [tid](const auto &state) { return state.tid == tid; });
                    const auto &state = found == original_.end() ? original_.front() : *found;
                    if (action_ == "affinity") {
                        if (sched_setaffinity(tid, sizeof(state.affinity), &state.affinity))
                            throw std::runtime_error("restore affinity failed");
                    } else if (setpriority(PRIO_PROCESS, tid, state.nice))
                        throw std::runtime_error("restore priority failed");
                }
            } else if (action_ == "cgroup") {
                write_file(fs::path("/sys/fs/cgroup") / original_cgroup_.substr(1) / "cgroup.procs", std::to_string(pid_));
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
    std::string action_;
    int value_;
    std::string identity_;
    std::vector<ThreadState> original_;
    std::string original_cgroup_;
    fs::path group_;
    bool enabled_cpu_ = false;
    bool active_ = false;
};

int main(int argc, char **argv) {
    if (argc != 7 && argc != 8) {
        std::cerr << "usage: coreflux-policy PID affinity|nice|cgroup VALUE SECONDS DECISIONS.jsonl LOG.jsonl [--apply]\n";
        return 2;
    }
    try {
        const int pid = std::stoi(argv[1]), value = std::stoi(argv[3]), seconds = std::stoi(argv[4]);
        if (pid <= 1 || seconds < 1 || seconds > 30) throw std::invalid_argument("invalid PID or duration");
        const std::string action = argv[2];
        if (action != "affinity" && action != "nice" && action != "cgroup") throw std::invalid_argument("invalid action");
        std::string decisions = read_file(argv[5]);
        while (!decisions.empty() && (decisions.back() == '\n' || decisions.back() == '\r')) decisions.pop_back();
        decisions = decisions.substr(decisions.rfind('\n') == std::string::npos ? 0 : decisions.rfind('\n') + 1);
        if (decisions.find("\"state\":\"CONTENTION\"") == std::string::npos &&
            decisions.find("\"state\":\"SEVERE\"") == std::string::npos)
            throw std::invalid_argument("latest decision is not contention");
        Change change(pid, action, value);
        const bool apply = argc == 8 && std::string(argv[7]) == "--apply";
        if (argc == 8 && !apply) throw std::invalid_argument("expected --apply");
        std::ofstream log(argv[6], std::ios::app);
        if (!log) throw std::runtime_error("cannot open action log");
        log << "{\"pid\":" << pid << ",\"action\":\"" << action << "\",\"value\":" << value
            << ",\"previous\":\"" << change.previous_state() << "\",\"status\":\""
            << (apply ? "applying" : "dry_run") << "\"}\n";
        log.flush();
        if (!apply) { std::cout << "dry run: " << action << " " << value << " for PID " << pid << '\n'; return 0; }
        std::signal(SIGINT, on_signal);
        std::signal(SIGTERM, on_signal);
        change.apply();
        std::cout << "applied " << action << " to PID " << pid << std::endl;
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
        while (!interrupted.load() && std::chrono::steady_clock::now() < deadline)
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        change.restore();
        log << "{\"pid\":" << pid << ",\"action\":\"" << action << "\",\"status\":\"restored\"}\n";
        std::cout << "restored PID " << pid << '\n';
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
