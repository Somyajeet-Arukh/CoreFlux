#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <numeric>
#include <random>
#include <string>
#include <string_view>
#include <thread>
#include <unistd.h>
#include <vector>

using namespace std;

int main(int argc, char **argv) {
    if ((argc != 7 && argc != 9 && argc != 10) || string_view(argv[1]) != "--mode" || string_view(argv[3]) != "--seconds" || string_view(argv[5]) != "--threads" || (argc >= 9 && string_view(argv[7]) != "--memory-mib") || (argc == 10 && string_view(argv[9]) != "--controlled")) {
        cerr << "usage: coreflux-workload --mode cpu|mixed|sequential|random|context-switch|telemetry-stress|latency --seconds N --threads N [--memory-mib N [--controlled]]\n";
        return 2;
    }
    const string_view mode = argv[2];
    const int seconds = atoi(argv[4]);
    const int threads = atoi(argv[6]);
    const int memory_mib = argc >= 9 ? atoi(argv[8]) : 32;
    if ((mode != "cpu" && mode != "mixed" && mode != "sequential" && mode != "random" && mode != "context-switch" && mode != "telemetry-stress" && mode != "latency") || seconds < 1 || seconds > 60 || threads < 1 || threads > 64 || (mode == "latency" && threads != 1) || memory_mib < 4 || memory_mib > 256 || (argc >= 9 && mode != "sequential" && mode != "random")) return 2;
    if (mode == "sequential" || mode == "random") {
        const size_t count = static_cast<size_t>(memory_mib) * 1024 * 1024 / sizeof(uint32_t);
        vector<vector<uint32_t>> data(static_cast<size_t>(threads));
        for (int i = 0; i < threads; ++i) {
            auto &array = data[static_cast<size_t>(i)];
            array.resize(count);
            if (mode == "sequential") {
                iota(array.begin(), array.end(), 1);
            } else {
                vector<uint32_t> order(count);
                iota(order.begin(), order.end(), 0);
                mt19937 generator(12345U + static_cast<unsigned>(i));
                shuffle(order.begin(), order.end(), generator);
                for (size_t n = 0; n < count; ++n) array[order[n]] = order[(n + 1) % count];
            }
        }
        if (argc == 10) {
            cout << "READY\n" << flush;
            string signal;
            if (!getline(cin, signal) || signal != "GO") return 2;
        }
        const auto memory_deadline = chrono::steady_clock::now() + chrono::seconds(seconds);
        atomic<uint64_t> operations{0};
        atomic<uint64_t> checksum{0};
        vector<thread> workers;
        for (int i = 0; i < threads; ++i) workers.emplace_back([&, i] {
            uint64_t local = 0;
            uint64_t sum = 0;
            const auto &array = data[static_cast<size_t>(i)];
            if (mode == "sequential") {
                while (chrono::steady_clock::now() < memory_deadline) {
                    for (const auto value : array) sum += value;
                    local += count;
                }
            } else {
                uint32_t cursor = 0;
                while (chrono::steady_clock::now() < memory_deadline) {
                    for (int n = 0; n < 4096; ++n) cursor = array[cursor];
                    local += 4096;
                }
                sum = cursor;
            }
            operations.fetch_add(local, memory_order_relaxed);
            checksum.fetch_add(sum, memory_order_relaxed);
        });
        for (auto &worker : workers) worker.join();
        if (argc == 10) {
            cout << "DONE\n" << flush;
            string signal;
            if (!getline(cin, signal) || signal != "STOP") return 2;
        }
        cout << "{\"mode\":\"" << mode << "\",\"threads\":" << threads
                  << ",\"duration_seconds\":" << seconds << ",\"operations\":" << operations.load()
                  << ",\"checksum\":" << checksum.load() << ",\"memory_mib_per_thread\":" << memory_mib << "}\n";
        return 0;
    }
    const auto deadline = chrono::steady_clock::now() + chrono::seconds(seconds);
    if (mode == "latency") {
        vector<uint64_t> samples;
        auto wake = chrono::steady_clock::now();
        while (wake + chrono::milliseconds(1) < deadline) {
            wake += chrono::milliseconds(1);
            this_thread::sleep_until(wake);
            const auto observed = chrono::steady_clock::now();
            samples.push_back(static_cast<uint64_t>(max<int64_t>(0, chrono::duration_cast<chrono::microseconds>(observed - wake).count())));
        }
        sort(samples.begin(), samples.end());
        const auto percentile = [&](size_t hundredths) { return samples[(samples.size() - 1) * hundredths / 100]; };
        cout << "{\"mode\":\"latency\",\"pid\":" << getpid() << ",\"threads\":1,\"duration_seconds\":" << seconds
                  << ",\"operations\":" << samples.size() << ",\"latency_p50_us\":" << percentile(50)
                  << ",\"latency_p95_us\":" << percentile(95) << ",\"latency_p99_us\":" << percentile(99) << "}\n";
        return 0;
    }
    atomic<uint64_t> operations{0};
    atomic<uint64_t> checksum{0};
    vector<thread> workers;
    for (int i = 0; i < threads; ++i) workers.emplace_back([&, i] {
        uint64_t local = 0;
        uint64_t sum = 0;
        if (mode == "context-switch" || mode == "telemetry-stress") {
            while (chrono::steady_clock::now() < deadline) {
                this_thread::yield();
                if (mode == "telemetry-stress") this_thread::sleep_for(chrono::microseconds(50));
                ++local;
            }
            sum = local;
        } else {
            double state = static_cast<double>(i + 1);
            while (chrono::steady_clock::now() < deadline) {
                for (int n = 0; n < 1024; ++n) state = sqrt(state * state + 1.0);
                local += 1024;
                if (mode == "mixed") this_thread::sleep_for(chrono::microseconds(100));
            }
            sum = static_cast<uint64_t>(state);
        }
        operations.fetch_add(local, memory_order_relaxed);
        checksum.fetch_add(sum, memory_order_relaxed);
    });
    for (auto &worker : workers) worker.join();
    cout << "{\"mode\":\"" << mode << "\",\"threads\":" << threads
              << ",\"duration_seconds\":" << seconds << ",\"operations\":" << operations.load()
              << ",\"checksum\":" << checksum.load() << ",\"memory_mib_per_thread\":" << (mode == "sequential" || mode == "random" ? memory_mib : 0) << "}\n";
}
