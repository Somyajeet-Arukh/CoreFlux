#pragma once
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <vector>

namespace coreflux {
class LatencyHistogram {
public:
    void observe(std::uint64_t event_ns) {
        const auto now = std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
        if (now < 0 || static_cast<std::uint64_t>(now) < event_ns) { ++invalid_; return; }
        const auto microseconds = (static_cast<std::uint64_t>(now) - event_ns) / 1000;
        const auto bucket = std::min<std::uint64_t>(microseconds, max_us);
        ++bins_[bucket];
        ++samples_;
        if (microseconds > max_us) ++clamped_;
    }
    std::uint64_t percentile(unsigned percent) const {
        if (!samples_) return 0;
        const auto target = (samples_ * percent + 99) / 100;
        std::uint64_t cumulative = 0;
        for (std::uint64_t i = 0; i < bins_.size(); ++i) {
            cumulative += bins_[i];
            if (cumulative >= target) return i;
        }
        return max_us;
    }
    std::uint64_t samples() const { return samples_; }
    std::uint64_t clamped() const { return clamped_; }
    std::uint64_t invalid() const { return invalid_; }
private:
    static constexpr std::uint64_t max_us = 100000;
    std::vector<std::uint64_t> bins_ = std::vector<std::uint64_t>(max_us + 1);
    std::uint64_t samples_ = 0;
    std::uint64_t clamped_ = 0;
    std::uint64_t invalid_ = 0;
};
}
