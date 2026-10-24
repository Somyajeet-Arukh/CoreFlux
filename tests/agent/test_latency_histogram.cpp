#include "coreflux/latency_histogram.hpp"
#include <chrono>
#include <cstdint>

using namespace std;

int main() {
    coreflux::LatencyHistogram histogram;
    if (histogram.percentile(95) != 0 || histogram.samples() != 0) return 1;

    const auto now = chrono::duration_cast<chrono::nanoseconds>(
        chrono::steady_clock::now().time_since_epoch()).count();
    histogram.observe(static_cast<uint64_t>(now) + 3600000000000ULL);
    if (histogram.invalid() != 1 || histogram.samples() != 0) return 2;

    histogram.observe(static_cast<uint64_t>(now) - 200000000ULL);
    if (histogram.samples() != 1 || histogram.clamped() != 1 ||
        histogram.percentile(50) != 100000 || histogram.percentile(99) != 100000) return 3;
    return 0;
}
