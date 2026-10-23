#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>
#include "coreflux/uapi.h"

/* Layout verified against the target kernel's sched_switch tracepoint format. */
struct sched_switch_context {
    __u64 common;
    char prev_comm[16];
    __s32 prev_pid;
    __s32 prev_prio;
    __s64 prev_state;
    char next_comm[16];
    __s32 next_pid;
    __s32 next_prio;
};

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 1 << 16);
} events SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, __u64);
} drop_count SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, __u64);
} emit_count SEC(".maps");

SEC("tracepoint/sched/sched_switch")
int record_switch(struct sched_switch_context *ctx)
{
    struct cf_event *event = bpf_ringbuf_reserve(&events, sizeof(*event), 0);
    if (!event) {
        __u32 key = 0;
        __u64 *count = bpf_map_lookup_elem(&drop_count, &key);
        if (count) ++*count;
        return 0;
    }
    event->timestamp_ns = bpf_ktime_get_ns();
    event->cpu = bpf_get_smp_processor_id();
    event->prev_pid = ctx->prev_pid;
    event->next_pid = ctx->next_pid;
    event->type = CF_EVENT_SCHED_SWITCH;
    event->reserved16 = 0;
    event->reserved64 = 0;
    bpf_ringbuf_submit(event, 0);
    __u32 key = 0;
    __u64 *count = bpf_map_lookup_elem(&emit_count, &key);
    if (count) ++*count;
    return 0;
}
char LICENSE[] SEC("license") = "GPL";
