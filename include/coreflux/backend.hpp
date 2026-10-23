#pragma once

#include "coreflux/event.hpp"
#include <cstddef>
#include <span>

namespace coreflux {
// Both future telemetry backends supply normalized events through this boundary.
// poll returns a count; lost_events is cumulative and must never silently reset.
class Backend {
public:
    virtual ~Backend() = default;
    virtual std::size_t poll(std::span<Event> output) = 0;
    virtual std::uint64_t lost_events() const = 0;
};
} // namespace coreflux
