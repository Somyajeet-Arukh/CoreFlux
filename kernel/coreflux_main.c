#include <linux/atomic.h>
#include <linux/errno.h>
#include <linux/fs.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mm.h>
#include <linux/mutex.h>
#include <linux/sched.h>
#include <linux/string.h>
#include <linux/tracepoint.h>
#include <linux/vmalloc.h>
#include <linux/uaccess.h>
#include "coreflux/uapi.h"

static DEFINE_MUTEX(state_lock);
static struct cf_config config = { .size = sizeof(config), .abi_version = CF_ABI_VERSION,
    .event_mask = CF_EVENT_MASK_SCHED_SWITCH, .sample_interval_ms = 100 };
static atomic64_t events_emitted = ATOMIC64_INIT(0);
static atomic64_t events_dropped = ATOMIC64_INIT(0);
static __u32 mode = CF_MODE_OBSERVE;
static void *ring_area;
static unsigned int cpu_slots;
static struct tracepoint *sched_switch_tracepoint;

static void find_sched_switch(struct tracepoint *tracepoint, void *unused)
{
    (void)unused;
    if (!strcmp(tracepoint->name, "sched_switch")) sched_switch_tracepoint = tracepoint;
}

static void on_sched_switch(void *unused, bool preempt, struct task_struct *prev,
                            struct task_struct *next, unsigned int prev_state)
{
    struct cf_ring_header *header;
    struct cf_event *events;
    struct cf_event *event;
    unsigned int cpu = raw_smp_processor_id();
    __u64 head, tail;
    (void)unused; (void)preempt; (void)prev_state;
    if (!(READ_ONCE(config.event_mask) & CF_EVENT_MASK_SCHED_SWITCH)) return;
    if (unlikely(cpu >= cpu_slots)) return;
    header = ring_area + (size_t)cpu * PAGE_SIZE;
    events = (void *)((char *)header + sizeof(*header));
    head = READ_ONCE(header->head);
    tail = smp_load_acquire(&header->tail);
    if (unlikely(tail > head || head - tail >= CF_RING_CAPACITY)) {
        WRITE_ONCE(header->dropped, READ_ONCE(header->dropped) + 1);
        atomic64_inc(&events_dropped);
        return;
    }
    event = &events[head % CF_RING_CAPACITY];
    event->timestamp_ns = ktime_get_ns();
    event->cpu = cpu;
    event->prev_pid = prev->pid;
    event->next_pid = next->pid;
    event->type = CF_EVENT_SCHED_SWITCH;
    event->reserved16 = 0;
    event->reserved64 = 0;
    smp_store_release(&header->head, head + 1);
    atomic64_inc(&events_emitted);
}

static bool valid_header(__u32 size, __u32 version, size_t expected)
{
    return size == expected && version == CF_ABI_VERSION;
}

static long coreflux_ioctl(struct file *file, unsigned int command, unsigned long argument)
{
    void __user *arg = (void __user *)argument;
    (void)file;
    if (_IOC_TYPE(command) != CF_IOC_MAGIC) return -ENOTTY;
    switch (command) {
    case CF_GET_VERSION: {
        struct cf_version value;
        if (copy_from_user(&value, arg, sizeof(value))) return -EFAULT;
        if (!valid_header(value.size, value.abi_version, sizeof(value))) return -EINVAL;
        value.module_major = 0;
        value.module_minor = 1;
        return copy_to_user(arg, &value, sizeof(value)) ? -EFAULT : 0;
    }
    case CF_SET_CONFIG: {
        struct cf_config value;
        if (copy_from_user(&value, arg, sizeof(value))) return -EFAULT;
        if (!valid_header(value.size, value.abi_version, sizeof(value)) ||
            value.sample_interval_ms < 1 || value.sample_interval_ms > 60000 ||
            value.event_mask & ~CF_EVENT_MASK_SCHED_SWITCH) return -EINVAL;
        mutex_lock(&state_lock);
        config = value;
        mutex_unlock(&state_lock);
        return 0;
    }
    case CF_GET_STATS: {
        struct cf_stats value;
        if (copy_from_user(&value, arg, sizeof(value))) return -EFAULT;
        if (!valid_header(value.size, value.abi_version, sizeof(value))) return -EINVAL;
        value.events_emitted = atomic64_read(&events_emitted);
        value.events_dropped = atomic64_read(&events_dropped);
        value.reserved = 0;
        mutex_lock(&state_lock);
        value.mode = mode;
        mutex_unlock(&state_lock);
        return copy_to_user(arg, &value, sizeof(value)) ? -EFAULT : 0;
    }
    case CF_RESET_STATS:
        atomic64_set(&events_emitted, 0);
        atomic64_set(&events_dropped, 0);
        return 0;
    case CF_SET_MODE: {
        struct cf_mode value;
        if (copy_from_user(&value, arg, sizeof(value))) return -EFAULT;
        if (!valid_header(value.size, value.abi_version, sizeof(value)) ||
            value.mode != CF_MODE_OBSERVE || value.reserved) return -EINVAL;
        mutex_lock(&state_lock);
        mode = value.mode;
        mutex_unlock(&state_lock);
        return 0;
    }
    case CF_GET_RING_INFO: {
        struct cf_ring_info value;
        if (copy_from_user(&value, arg, sizeof(value))) return -EFAULT;
        if (!valid_header(value.size, value.abi_version, sizeof(value))) return -EINVAL;
        value.cpu_slots = cpu_slots;
        value.region_size = PAGE_SIZE;
        value.capacity = CF_RING_CAPACITY;
        value.event_size = sizeof(struct cf_event);
        value.mapping_size = (size_t)cpu_slots * PAGE_SIZE;
        return copy_to_user(arg, &value, sizeof(value)) ? -EFAULT : 0;
    }
    default:
        return -ENOTTY;
    }
}

static void coreflux_vma_open(struct vm_area_struct *vma)
{
    (void)vma;
    __module_get(THIS_MODULE);
}
static void coreflux_vma_close(struct vm_area_struct *vma)
{
    (void)vma;
    module_put(THIS_MODULE);
}
static const struct vm_operations_struct coreflux_vm_ops = {
    .open = coreflux_vma_open,
    .close = coreflux_vma_close,
};
static int coreflux_mmap(struct file *file, struct vm_area_struct *vma)
{
    int error;
    (void)file;
    if (!(vma->vm_flags & VM_SHARED) || vma->vm_pgoff ||
        vma->vm_end - vma->vm_start != (size_t)cpu_slots * PAGE_SIZE)
        return -EINVAL;
    if (!try_module_get(THIS_MODULE)) return -ENODEV;
    error = remap_vmalloc_range(vma, ring_area, 0);
    if (error) { module_put(THIS_MODULE); return error; }
    vma->vm_ops = &coreflux_vm_ops;
    return 0;
}

static const struct file_operations coreflux_fops = {
    .owner = THIS_MODULE,
    .unlocked_ioctl = coreflux_ioctl,
    .mmap = coreflux_mmap,
#ifdef CONFIG_COMPAT
    .compat_ioctl = compat_ptr_ioctl,
#endif
    .llseek = no_llseek,
};
static struct miscdevice coreflux_device = {
    .minor = MISC_DYNAMIC_MINOR,
    .name = "coreflux",
    .fops = &coreflux_fops,
    .mode = 0600,
};
static int __init coreflux_init(void)
{
    int error;
    BUILD_BUG_ON(sizeof(struct cf_ring_header) != 64);
    BUILD_BUG_ON(sizeof(struct cf_event) != 32);
    BUILD_BUG_ON(sizeof(struct cf_ring_header) + CF_RING_CAPACITY * sizeof(struct cf_event) > PAGE_SIZE);
    cpu_slots = nr_cpu_ids;
    ring_area = vmalloc_user((size_t)cpu_slots * PAGE_SIZE);
    if (!ring_area) return -ENOMEM;
    error = misc_register(&coreflux_device);
    if (error) goto free_ring;
    for_each_kernel_tracepoint(find_sched_switch, NULL);
    if (!sched_switch_tracepoint) { error = -ENOENT; goto remove_device; }
    error = tracepoint_probe_register(sched_switch_tracepoint, on_sched_switch, NULL);
    if (error) goto remove_device;
    return 0;
remove_device:
    misc_deregister(&coreflux_device);
free_ring:
    vfree(ring_area);
    return error;
}
static void __exit coreflux_exit(void)
{
    tracepoint_probe_unregister(sched_switch_tracepoint, on_sched_switch, NULL);
    tracepoint_synchronize_unregister();
    misc_deregister(&coreflux_device);
    vfree(ring_area);
}
module_init(coreflux_init);
module_exit(coreflux_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("CoreFlux scheduler telemetry control device");
