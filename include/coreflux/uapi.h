#ifndef COREFLUX_UAPI_H
#define COREFLUX_UAPI_H
#include <linux/ioctl.h>
#include <linux/types.h>

#define CF_ABI_VERSION 1U
#define CF_IOC_MAGIC 'C'
#define CF_MODE_OBSERVE 0U
#define CF_MODE_CONTROLLED 1U
#define CF_RING_CAPACITY 64U
#define CF_EVENT_MASK_SCHED_SWITCH 1U

struct cf_version {
    __u32 size;
    __u32 abi_version;
    __u32 module_major;
    __u32 module_minor;
};
struct cf_config {
    __u32 size;
    __u32 abi_version;
    __u32 event_mask;
    __u32 sample_interval_ms;
};
struct cf_stats {
    __u32 size;
    __u32 abi_version;
    __u64 events_emitted;
    __u64 events_dropped;
    __u32 mode;
    __u32 reserved;
};
struct cf_mode {
    __u32 size;
    __u32 abi_version;
    __u32 mode;
    __u32 reserved;
};
struct cf_ring_info {
    __u32 size;
    __u32 abi_version;
    __u32 cpu_slots;
    __u32 region_size;
    __u32 capacity;
    __u32 event_size;
    __u64 mapping_size;
};
struct cf_event {
    __u64 timestamp_ns;
    __u32 cpu;
    __u32 prev_pid;
    __u32 next_pid;
    __u16 type;
    __u16 reserved16;
    __u64 reserved64;
};
struct cf_ring_header {
    __u64 head; /* kernel producer writes, user consumer acquires */
    __u64 tail; /* user consumer writes, kernel producer acquires */
    __u64 dropped;
    __u8 reserved[40];
};

#define CF_GET_VERSION _IOWR(CF_IOC_MAGIC, 0x01, struct cf_version)
#define CF_SET_CONFIG  _IOW(CF_IOC_MAGIC, 0x02, struct cf_config)
#define CF_GET_STATS   _IOWR(CF_IOC_MAGIC, 0x03, struct cf_stats)
#define CF_RESET_STATS _IO(CF_IOC_MAGIC, 0x04)
#define CF_SET_MODE    _IOW(CF_IOC_MAGIC, 0x05, struct cf_mode)
#define CF_GET_RING_INFO _IOWR(CF_IOC_MAGIC, 0x06, struct cf_ring_info)
#define CF_EVENT_SCHED_SWITCH 1U
#endif
