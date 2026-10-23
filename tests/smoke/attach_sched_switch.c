#include <bpf/libbpf.h>
#include <stdio.h>
#include <unistd.h>

struct event { unsigned long long timestamp_ns; unsigned int cpu; };
static int received;
static int on_event(void *context, void *data, size_t size)
{
    const struct event *event = data;
    (void)context;
    if (size < sizeof(*event) || !event->timestamp_ns) return -1;
    printf("received scheduler event from CPU %u\n", event->cpu);
    received++;
    return 0;
}

int main(int argc, char **argv)
{
    struct bpf_object *object;
    struct bpf_program *program;
    struct bpf_link *link;
    struct ring_buffer *buffer;
    int error;

    if (argc != 2) return 2;
    object = bpf_object__open_file(argv[1], NULL);
    if (!object) return 3;
    error = bpf_object__load(object);
    if (error) { fprintf(stderr, "load: %d\n", error); bpf_object__close(object); return 4; }
    program = bpf_object__next_program(object, NULL);
    link = bpf_program__attach_tracepoint(program, "sched", "sched_switch");
    if (!link || libbpf_get_error(link)) {
        fprintf(stderr, "attach failed\n");
        bpf_object__close(object);
        return 5;
    }
    buffer = ring_buffer__new(bpf_map__fd(bpf_object__find_map_by_name(object, "events")), on_event, NULL, NULL);
    if (!buffer) { bpf_link__destroy(link); bpf_object__close(object); return 6; }
    for (int attempt = 0; attempt < 20 && !received; attempt++) {
        usleep(10000);
        if (ring_buffer__poll(buffer, 100) < 0) break;
    }
    ring_buffer__free(buffer);
    bpf_link__destroy(link);
    bpf_object__close(object);
    return received ? 0 : 7;
}
