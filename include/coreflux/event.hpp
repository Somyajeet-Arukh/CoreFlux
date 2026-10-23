#pragma once

#include <cstdint>

namespace coreflux {
inline constexpr std::uint32_t event_abi_version = 1;
enum class EventType : std::uint16_t { synthetic = 0, sched_switch = 1, buffer_drop = 2, policy = 3 };

// Timestamp is CLOCK_MONOTONIC nanoseconds; ids are Linux PID/TID values.
// Payload layout is selected by type and versioned separately when extended.
struct Event {
    std::uint32_t abi_version = event_abi_version;
    EventType type = EventType::synthetic;
    std::uint16_t payload_size = 0;
    std::uint64_t timestamp_ns = 0;
    std::uint32_t cpu = 0;
    std::uint32_t pid = 0;
    std::uint32_t tid = 0;
    std::uint32_t reserved = 0;
};
static_assert(sizeof(Event) == 32);
} // namespace coreflux
