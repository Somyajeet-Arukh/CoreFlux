#include "coreflux/uapi.h"
#include "coreflux/json_record.hpp"
#include "coreflux/latency_histogram.hpp"
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <thread>
#include <unistd.h>
#include <fcntl.h>

using namespace std;

int main(int argc, char **argv) {
    if (argc != 4) { cerr << "usage: coreflux-ring-reader DEVICE OUTPUT SECONDS\n"; return 2; }
    int seconds = atoi(argv[3]);
    if (seconds < 1 || seconds > 60) return 2;
    const int fd = open(argv[1], O_RDWR);
    if (fd < 0) { cerr << "open: " << strerror(errno) << '\n'; return 1; }
    cf_ring_info info{sizeof(info), CF_ABI_VERSION, 0, 0, 0, 0, 0};
    if (ioctl(fd, CF_GET_RING_INFO, &info) || !info.cpu_slots || !info.capacity ||
        info.event_size != sizeof(cf_event) ||
        info.region_size < sizeof(cf_ring_header) + static_cast<uint64_t>(info.capacity) * sizeof(cf_event) ||
        info.mapping_size != static_cast<uint64_t>(info.cpu_slots) * info.region_size ||
        info.mapping_size > numeric_limits<size_t>::max()) {
        cerr << "incompatible ring layout\n"; close(fd); return 1;
    }
    void *mapped = mmap(nullptr, info.mapping_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (mapped == MAP_FAILED) { cerr << "mmap: " << strerror(errno) << '\n'; close(fd); return 1; }
    ofstream out(argv[2]);
    if (!out) { munmap(mapped, info.mapping_size); close(fd); return 1; }
    uint64_t count = 0;
    coreflux::LatencyHistogram latency;
    const auto deadline = chrono::steady_clock::now() + chrono::seconds(seconds);
    while (chrono::steady_clock::now() < deadline) {
        cf_event next{};
        cf_ring_header *chosen = nullptr;
        for (uint32_t cpu = 0; cpu < info.cpu_slots; ++cpu) {
            auto *base = static_cast<char *>(mapped) + static_cast<size_t>(cpu) * info.region_size;
            auto *header = reinterpret_cast<cf_ring_header *>(base);
            const auto head = __atomic_load_n(&header->head, __ATOMIC_ACQUIRE);
            const auto tail = __atomic_load_n(&header->tail, __ATOMIC_RELAXED);
            if (tail >= head) continue;
            auto *events = reinterpret_cast<cf_event *>(base + sizeof(cf_ring_header));
            const auto candidate = events[tail % info.capacity];
            if (!chosen || candidate.timestamp_ns < next.timestamp_ns) { next = candidate; chosen = header; }
        }
        if (!chosen) { this_thread::sleep_for(chrono::milliseconds(1)); continue; }
        coreflux::write_json_record(out, next);
        latency.observe(next.timestamp_ns);
        const auto tail = __atomic_load_n(&chosen->tail, __ATOMIC_RELAXED);
        __atomic_store_n(&chosen->tail, tail + 1, __ATOMIC_RELEASE);
        ++count;
    }
    out.close();
    cf_stats stats{sizeof(stats), CF_ABI_VERSION, 0, 0, 0, 0};
    if (ioctl(fd, CF_GET_STATS, &stats)) { munmap(mapped, info.mapping_size); close(fd); return 1; }
    munmap(mapped, info.mapping_size);
    close(fd);
    cout << "events=" << count << " emitted=" << stats.events_emitted
              << " dropped=" << stats.events_dropped << " latency_samples=" << latency.samples()
              << " latency_p50_us=" << latency.percentile(50) << " latency_p95_us=" << latency.percentile(95)
              << " latency_p99_us=" << latency.percentile(99) << " latency_clamped=" << latency.clamped()
              << " latency_invalid=" << latency.invalid() << '\n';
    return out && count ? 0 : 1;
}
