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

int main(int argc, char **argv) {
    if ((argc != 7 && argc != 9 && argc != 10) || std::string_view(argv[1]) != "--mode" || std::string_view(argv[3]) != "--seconds" || std::string_view(argv[5]) != "--threads" || (argc >= 9 && std::string_view(argv[7]) != "--memory-mib") || (argc == 10 && std::string_view(argv[9]) != "--controlled")) {
        std::cerr << "usage: coreflux-workload --mode cpu|mixed|sequential|random|context-switch|telemetry-stress|latency --seconds N --threads N [--memory-mib N [--controlled]]\n";
        return 2;
    }
    const std::string_view mode = argv[2];
    const int seconds = std::atoi(argv[4]);
    const int threads = std::atoi(argv[6]);
    const int memory_mib = argc >= 9 ? std::atoi(argv[8]) : 32;
    if ((mode != "cpu" && mode != "mixed" && mode != "sequential" && mode != "random" && mode != "context-switch" && mode != "telemetry-stress" && mode != "latency") || seconds < 1 || seconds > 60 || threads < 1 || threads > 64 || (mode == "latency" && threads != 1) || memory_mib < 4 || memory_mib > 256 || (argc >= 9 && mode != "sequential" && mode != "random")) return 2;
    if (mode == "sequential" || mode == "random") {
        const std::size_t count = static_cast<std::size_t>(memory_mib) * 1024 * 1024 / sizeof(std::uint32_t);
        std::vector<std::vector<std::uint32_t>> data(static_cast<std::size_t>(threads));
        for (int i = 0; i < threads; ++i) {
            auto &array = data[static_cast<std::size_t>(i)];
            array.resize(count);
            if (mode == "sequential") {
                std::iota(array.begin(), array.end(), 1);
            } else {
                std::vector<std::uint32_t> order(count);
                std::iota(order.begin(), order.end(), 0);
                std::mt19937 generator(12345U + static_cast<unsigned>(i));
                std::shuffle(order.begin(), order.end(), generator);
                for (std::size_t n = 0; n < count; ++n) array[order[n]] = order[(n + 1) % count];
            }
        }
        if (argc == 10) {
            std::cout << "READY\n" << std::flush;
            std::string signal;
            if (!std::getline(std::cin, signal) || signal != "GO") return 2;
        }
        const auto memory_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
        std::atomic<std::uint64_t> operations{0};
        std::atomic<std::uint64_t> checksum{0};
        std::vector<std::thread> workers;
        for (int i = 0; i < threads; ++i) workers.emplace_back([&, i] {
            std::uint64_t local = 0;
            std::uint64_t sum = 0;
            const auto &array = data[static_cast<std::size_t>(i)];
            if (mode == "sequential") {
                while (std::chrono::steady_clock::now() < memory_deadline) {
                    for (const auto value : array) sum += value;
                    local += count;
                }
            } else {
                std::uint32_t cursor = 0;
                while (std::chrono::steady_clock::now() < memory_deadline) {
                    for (int n = 0; n < 4096; ++n) cursor = array[cursor];
                    local += 4096;
                }
                sum = cursor;
            }
            operations.fetch_add(local, std::memory_order_relaxed);
            checksum.fetch_add(sum, std::memory_order_relaxed);
        });
        for (auto &worker : workers) worker.join();
        if (argc == 10) {
            std::cout << "DONE\n" << std::flush;
            std::string signal;
            if (!std::getline(std::cin, signal) || signal != "STOP") return 2;
        }
        std::cout << "{\"mode\":\"" << mode << "\",\"threads\":" << threads
                  << ",\"duration_seconds\":" << seconds << ",\"operations\":" << operations.load()
                  << ",\"checksum\":" << checksum.load() << ",\"memory_mib_per_thread\":" << memory_mib << "}\n";
        return 0;
    }
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
    if (mode == "latency") {
        std::vector<std::uint64_t> samples;
        auto wake = std::chrono::steady_clock::now();
        while (wake + std::chrono::milliseconds(1) < deadline) {
            wake += std::chrono::milliseconds(1);
            std::this_thread::sleep_until(wake);
            const auto observed = std::chrono::steady_clock::now();
            samples.push_back(static_cast<std::uint64_t>(std::max<std::int64_t>(0, std::chrono::duration_cast<std::chrono::microseconds>(observed - wake).count())));
        }
        std::sort(samples.begin(), samples.end());
        const auto percentile = [&](std::size_t hundredths) { return samples[(samples.size() - 1) * hundredths / 100]; };
        std::cout << "{\"mode\":\"latency\",\"pid\":" << getpid() << ",\"threads\":1,\"duration_seconds\":" << seconds
                  << ",\"operations\":" << samples.size() << ",\"latency_p50_us\":" << percentile(50)
                  << ",\"latency_p95_us\":" << percentile(95) << ",\"latency_p99_us\":" << percentile(99) << "}\n";
        return 0;
    }
    std::atomic<std::uint64_t> operations{0};
    std::atomic<std::uint64_t> checksum{0};
    std::vector<std::thread> workers;
    for (int i = 0; i < threads; ++i) workers.emplace_back([&, i] {
        std::uint64_t local = 0;
        std::uint64_t sum = 0;
        if (mode == "context-switch" || mode == "telemetry-stress") {
            while (std::chrono::steady_clock::now() < deadline) {
                std::this_thread::yield();
                if (mode == "telemetry-stress") std::this_thread::sleep_for(std::chrono::microseconds(50));
                ++local;
            }
            sum = local;
        } else {
            double state = static_cast<double>(i + 1);
            while (std::chrono::steady_clock::now() < deadline) {
                for (int n = 0; n < 1024; ++n) state = std::sqrt(state * state + 1.0);
                local += 1024;
                if (mode == "mixed") std::this_thread::sleep_for(std::chrono::microseconds(100));
            }
            sum = static_cast<std::uint64_t>(state);
        }
        operations.fetch_add(local, std::memory_order_relaxed);
        checksum.fetch_add(sum, std::memory_order_relaxed);
    });
    for (auto &worker : workers) worker.join();
    std::cout << "{\"mode\":\"" << mode << "\",\"threads\":" << threads
              << ",\"duration_seconds\":" << seconds << ",\"operations\":" << operations.load()
              << ",\"checksum\":" << checksum.load() << ",\"memory_mib_per_thread\":" << (mode == "sequential" || mode == "random" ? memory_mib : 0) << "}\n";
}
