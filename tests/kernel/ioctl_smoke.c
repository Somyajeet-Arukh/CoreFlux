#include "coreflux/uapi.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>

struct worker_args { int fd; int writer; };
static void *worker(void *opaque)
{
    struct worker_args *args = opaque;
    for (int i = 0; i < 1000; ++i) {
        if (args->writer) {
            struct cf_config value = { .size = sizeof(value), .abi_version = CF_ABI_VERSION,
                .event_mask = i & 1, .sample_interval_ms = 100 };
            assert(ioctl(args->fd, CF_SET_CONFIG, &value) == 0);
        } else {
            struct cf_stats value = { .size = sizeof(value), .abi_version = CF_ABI_VERSION };
            assert(ioctl(args->fd, CF_GET_STATS, &value) == 0);
            assert(value.mode == CF_MODE_OBSERVE && value.reserved == 0);
        }
    }
    return NULL;
}

int main(int argc, char **argv)
{
    struct cf_version version = { .size = sizeof(version), .abi_version = CF_ABI_VERSION };
    struct cf_stats stats = { .size = sizeof(stats), .abi_version = CF_ABI_VERSION };
    struct cf_config config = { .size = sizeof(config), .abi_version = CF_ABI_VERSION,
        .sample_interval_ms = 100 };
    struct cf_mode mode = { .size = sizeof(mode), .abi_version = CF_ABI_VERSION,
        .mode = CF_MODE_OBSERVE };
    struct cf_ring_info ring = { .size = sizeof(ring), .abi_version = CF_ABI_VERSION };
    pthread_t threads[4];
    struct worker_args args[4];
    int fd;
    if (argc != 2) return 2;
    fd = open(argv[1], O_RDWR);
    if (fd < 0) { perror("open"); return 1; }
    assert(ioctl(fd, CF_GET_VERSION, &version) == 0);
    assert(version.abi_version == CF_ABI_VERSION && version.module_minor == 1);
    assert(ioctl(fd, CF_GET_STATS, &stats) == 0);
    assert(stats.mode == CF_MODE_OBSERVE);
    assert(ioctl(fd, CF_SET_CONFIG, &config) == 0);
    assert(ioctl(fd, CF_SET_MODE, &mode) == 0);
    assert(ioctl(fd, CF_GET_RING_INFO, &ring) == 0 && ring.cpu_slots > 0);
    assert(ioctl(fd, CF_RESET_STATS) == 0);
    version.size--;
    assert(ioctl(fd, CF_GET_VERSION, &version) == -1 && errno == EINVAL);
    version.size++;
    version.abi_version++;
    assert(ioctl(fd, CF_GET_VERSION, &version) == -1 && errno == EINVAL);
    config.sample_interval_ms = 0;
    assert(ioctl(fd, CF_SET_CONFIG, &config) == -1 && errno == EINVAL);
    config.sample_interval_ms = 60001;
    assert(ioctl(fd, CF_SET_CONFIG, &config) == -1 && errno == EINVAL);
    config.sample_interval_ms = 100;
    config.event_mask = 2;
    assert(ioctl(fd, CF_SET_CONFIG, &config) == -1 && errno == EINVAL);
    config.event_mask = CF_EVENT_MASK_SCHED_SWITCH;
    mode.mode = CF_MODE_CONTROLLED;
    assert(ioctl(fd, CF_SET_MODE, &mode) == -1 && errno == EINVAL);
    mode.mode = CF_MODE_OBSERVE;
    mode.reserved = 1;
    assert(ioctl(fd, CF_SET_MODE, &mode) == -1 && errno == EINVAL);
    mode.reserved = 0;
    stats.abi_version++;
    assert(ioctl(fd, CF_GET_STATS, &stats) == -1 && errno == EINVAL);
    stats.abi_version--;
    ring.size--;
    assert(ioctl(fd, CF_GET_RING_INFO, &ring) == -1 && errno == EINVAL);
    ring.size++;
    assert(ioctl(fd, _IO(CF_IOC_MAGIC, 0x7f)) == -1 && errno == ENOTTY);
    assert(ioctl(fd, _IO('X', 0x01)) == -1 && errno == ENOTTY);
    assert(ioctl(fd, CF_GET_VERSION, NULL) == -1 && errno == EFAULT);
    assert(ioctl(fd, CF_SET_CONFIG, NULL) == -1 && errno == EFAULT);
    assert(ioctl(fd, CF_GET_STATS, NULL) == -1 && errno == EFAULT);
    assert(ioctl(fd, CF_SET_MODE, NULL) == -1 && errno == EFAULT);
    assert(ioctl(fd, CF_GET_RING_INFO, NULL) == -1 && errno == EFAULT);
    for (int i = 0; i < 4; ++i) {
        args[i] = (struct worker_args){ .fd = fd, .writer = i < 2 };
        assert(pthread_create(&threads[i], NULL, worker, &args[i]) == 0);
    }
    for (int i = 0; i < 4; ++i) assert(pthread_join(threads[i], NULL) == 0);
    assert(ioctl(fd, CF_SET_CONFIG, &config) == 0);
    close(fd);
    puts("coreflux ioctl smoke passed");
    return 0;
}
