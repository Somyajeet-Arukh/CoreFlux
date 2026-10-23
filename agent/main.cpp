#include "coreflux/event.hpp"
#include <chrono>
#include <fstream>
#include <iostream>
#include <string_view>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc != 4 || std::string_view(argv[1]) != "--synthetic" || std::string_view(argv[2]) != "--output") {
        std::cerr << "usage: coreflux-agent --synthetic --output FILE\n";
        return 2;
    }
    std::ofstream out(argv[3]);
    if (!out) { std::cerr << "cannot open output\n"; return 1; }
    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    coreflux::Event event;
    event.timestamp_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
    event.pid = static_cast<std::uint32_t>(getpid());
    event.tid = event.pid;
    out << "{\"abi_version\":" << event.abi_version << ",\"type\":" << static_cast<int>(event.type)
        << ",\"timestamp_ns\":" << event.timestamp_ns << ",\"cpu\":" << event.cpu
        << ",\"pid\":" << event.pid << ",\"tid\":" << event.tid << "}\n";
    if (!out) return 1;
    std::cout << "recorded 1 synthetic event\n";
}
