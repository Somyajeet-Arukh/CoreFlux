#include "coreflux/uapi.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    struct cf_ring_info info = { .size = sizeof(info), .abi_version = CF_ABI_VERSION };
    void *mapped;
    int fd;
    if (argc != 2) return 2;
    fd = open(argv[1], O_RDWR);
    assert(fd >= 0);
    assert(ioctl(fd, CF_GET_RING_INFO, &info) == 0);
    assert(info.capacity == CF_RING_CAPACITY);
    assert(info.event_size == sizeof(struct cf_event));
    assert(info.region_size >= sizeof(struct cf_ring_header) + info.capacity * info.event_size);
    assert(info.mapping_size == (__u64)info.cpu_slots * info.region_size);
    mapped = mmap(NULL, info.mapping_size - info.region_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    assert(mapped == MAP_FAILED && errno == EINVAL);
    mapped = mmap(NULL, info.mapping_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    assert(mapped != MAP_FAILED);
    close(fd);
    pid_t child = fork();
    assert(child >= 0);
    if (child == 0) {
        assert(((struct cf_ring_header *)mapped)->head >= ((struct cf_ring_header *)mapped)->tail);
        _exit(0);
    }
    int status = 0;
    assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    assert(system("rmmod coreflux_main >/dev/null 2>&1") != 0);
    assert(((struct cf_ring_header *)mapped)->head >= ((struct cf_ring_header *)mapped)->tail);
    assert(munmap(mapped, info.mapping_size) == 0);
    return 0;
}
