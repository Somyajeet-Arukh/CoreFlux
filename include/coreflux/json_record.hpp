#pragma once
#include "coreflux/uapi.h"
#include <ostream>

namespace coreflux {
inline void write_json_record(std::ostream &out, const cf_event &event) {
    out << "{\"timestamp_ns\":" << event.timestamp_ns << ",\"cpu\":" << event.cpu
        << ",\"prev_pid\":" << event.prev_pid << ",\"next_pid\":" << event.next_pid
        << ",\"type\":" << event.type << "}\n";
}
}
