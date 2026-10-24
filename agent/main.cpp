#include "coreflux/event.hpp"
#include <chrono>
#include <fstream>
#include <iostream>
#include <string_view>
#include <unistd.h>

using namespace std;

int main(int argc, char **argv) {
    if (argc != 4 || string_view(argv[1]) != "--synthetic" || string_view(argv[2]) != "--output") {
        cerr << "usage: coreflux-agent --synthetic --output FILE\n";
        return 2;
    }
    ofstream out(argv[3]);
    if (!out) { cerr << "cannot open output\n"; return 1; }
    const auto now = chrono::steady_clock::now().time_since_epoch();
    coreflux::Event event;
    event.timestamp_ns = chrono::duration_cast<chrono::nanoseconds>(now).count();
    event.pid = static_cast<uint32_t>(getpid());
    event.tid = event.pid;
    out << "{\"abi_version\":" << event.abi_version << ",\"type\":" << static_cast<int>(event.type)
        << ",\"timestamp_ns\":" << event.timestamp_ns << ",\"cpu\":" << event.cpu
        << ",\"pid\":" << event.pid << ",\"tid\":" << event.tid << "}\n";
    if (!out) return 1;
    cout << "recorded 1 synthetic event\n";
}
