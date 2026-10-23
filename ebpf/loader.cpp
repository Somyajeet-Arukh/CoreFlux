#include "coreflux/json_record.hpp"
#include "coreflux/latency_histogram.hpp"
#include <bpf/bpf.h>
#include <bpf/libbpf.h>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <thread>
#include <vector>

struct Recorder {
    std::ofstream *out;
    std::uint64_t count = 0;
    coreflux::LatencyHistogram latency;
};
static int on_record(void *context, void *data, size_t size) {
    auto &recorder = *static_cast<Recorder *>(context);
    if (size != sizeof(cf_event)) return -1;
    coreflux::write_json_record(*recorder.out, *static_cast<cf_event *>(data));
    recorder.latency.observe(static_cast<cf_event *>(data)->timestamp_ns);
    ++recorder.count;
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 4 || argc > 6) { std::cerr << "usage: coreflux-ebpf-loader OBJECT OUTPUT SECONDS [START_DELAY_MS] [POLL_SLEEP_MS]\n"; return 2; }
    const int seconds = std::atoi(argv[3]);
    if (seconds < 1 || seconds > 60) return 2;
    const int delay_ms = argc >= 5 ? std::atoi(argv[4]) : 0;
    const int poll_sleep_ms = argc == 6 ? std::atoi(argv[5]) : 0;
    if (delay_ms < 0 || delay_ms > 5000) return 2;
    if (poll_sleep_ms < 0 || poll_sleep_ms > 100) return 2;
    std::ofstream out(argv[2]);
    if (!out) return 1;
    bpf_object *object = bpf_object__open_file(argv[1], nullptr);
    if (!object) { std::cerr << "open BPF object failed\n"; return 1; }
    if (bpf_object__load(object)) { std::cerr << "load BPF object failed\n"; bpf_object__close(object); return 1; }
    bpf_program *program = bpf_object__find_program_by_name(object, "record_switch");
    bpf_map *events = bpf_object__find_map_by_name(object, "events");
    bpf_map *drop_map = bpf_object__find_map_by_name(object, "drop_count");
    bpf_map *emit_map = bpf_object__find_map_by_name(object, "emit_count");
    if (!program || !events || !drop_map || !emit_map) {
        std::cerr << "incompatible BPF object\n";
        bpf_object__close(object);
        return 1;
    }
    bpf_link *link = bpf_program__attach_tracepoint(program, "sched", "sched_switch");
    if (!link || libbpf_get_error(link)) { std::cerr << "attach failed\n"; bpf_object__close(object); return 1; }
    Recorder recorder{&out, 0, {}};
    ring_buffer *ring = ring_buffer__new(bpf_map__fd(events), on_record, &recorder, nullptr);
    if (!ring) { bpf_link__destroy(link); bpf_object__close(object); return 1; }
    if (delay_ms) std::this_thread::sleep_for(std::chrono::milliseconds(delay_ms));
    int poll_error = 0;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
    while (std::chrono::steady_clock::now() < deadline) {
        poll_error = ring_buffer__poll(ring, poll_sleep_ms ? 0 : 100);
        if (poll_error < 0) break;
        if (poll_sleep_ms) std::this_thread::sleep_for(std::chrono::milliseconds(poll_sleep_ms));
    }
    const int cpu_count = libbpf_num_possible_cpus();
    if (cpu_count <= 0) {
        std::cerr << "cannot determine possible CPUs\n";
        ring_buffer__free(ring);
        bpf_link__destroy(link);
        bpf_object__close(object);
        return 1;
    }
    std::vector<std::uint64_t> counts(cpu_count);
    const std::uint32_t key = 0;
    std::uint64_t total_drops = 0;
    const int drop_error = bpf_map_lookup_elem(bpf_map__fd(drop_map), &key, counts.data());
    if (!drop_error) for (auto value : counts) total_drops += value;
    std::uint64_t total_emitted = 0;
    const int emit_error = bpf_map_lookup_elem(bpf_map__fd(emit_map), &key, counts.data());
    if (!emit_error) for (auto value : counts) total_emitted += value;
    ring_buffer__free(ring);
    bpf_link__destroy(link);
    bpf_object__close(object);
    out.close();
    if (drop_error || emit_error) { std::cerr << "read BPF counters failed\n"; return 1; }
    std::cout << "events=" << recorder.count << " emitted=" << total_emitted << " dropped=" << total_drops
              << " latency_samples=" << recorder.latency.samples()
              << " latency_p50_us=" << recorder.latency.percentile(50)
              << " latency_p95_us=" << recorder.latency.percentile(95)
              << " latency_p99_us=" << recorder.latency.percentile(99)
              << " latency_clamped=" << recorder.latency.clamped()
              << " latency_invalid=" << recorder.latency.invalid() << '\n';
    return poll_error < 0 || !out || !recorder.count ? 1 : 0;
}
