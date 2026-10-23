#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>

struct event { __u64 timestamp_ns; __u32 cpu; };

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 4096);
} events SEC(".maps");

SEC("tracepoint/sched/sched_switch")
int coreflux_sched_switch(void *ctx)
{
    struct event *event;
    (void)ctx;
    event = bpf_ringbuf_reserve(&events, sizeof(*event), 0);
    if (!event) return 0;
    event->timestamp_ns = bpf_ktime_get_ns();
    event->cpu = bpf_get_smp_processor_id();
    bpf_ringbuf_submit(event, 0);
    return 0;
}

char LICENSE[] SEC("license") = "GPL";
