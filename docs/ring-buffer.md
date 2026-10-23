# Per-CPU telemetry rings

The module registers a `sched_switch` tracepoint probe. Each possible CPU owns one page in a single bounded `vmalloc_user` mapping. Its first 64 bytes are a ring header; 64 fixed 32-byte scheduler records follow. The user obtains the layout with `CF_GET_RING_INFO` and maps the complete region with shared `mmap`.

The kernel is the sole producer for its CPU page. It writes an event and publishes the new `head` with release ordering. The user reads `head` with acquire ordering, reads events, then publishes `tail` with release ordering. The kernel reads `tail` with acquire ordering. Each ring drops a new event when full; `dropped` in the ring header and `events_dropped` in `CF_GET_STATS` make loss visible. No allocation or blocking work occurs in the tracepoint callback.

The prototype exposes writable ring metadata to the root-only client so it can advance `tail`. This assumes a trusted reader; a hostile privileged process could corrupt its own telemetry view. The mapping pins the module until unmapped, including after closing the device file. The probe is unregistered and synchronized before module memory is freed.

`coreflux-ring-reader` merges the currently visible oldest event from each CPU page and writes JSONL. Records retain monotonic timestamps and CPU IDs. Because CPUs publish independently, the output is a best-effort cross-CPU merge, not a strict global ordering guarantee. Per-CPU ordering is preserved. The live test checks event shape, per-CPU ordering, mapping lifetime, visible overflow accounting and clean unload.
