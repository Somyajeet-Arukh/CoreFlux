#pragma once
#include <array>
#include <cstdint>
#include <string>

namespace coreflux {
inline constexpr std::array<const char *, 5> signal_names = {
    "cpu_pressure", "runnable_pressure", "context_switch_intensity",
    "memory_pressure", "scheduler_latency"};
enum class State { normal, watch, contention, severe, unknown };
struct Sample {
    std::uint64_t timestamp_ns;
    std::array<double, 5> signal; // -1 means unavailable, otherwise 0..1
};
struct Decision {
    State state;
    double score;
    double coverage;
    std::array<double, 5> contributions;
    std::string dominant;
    bool transition;
};
class Scorer {
public:
    explicit Scorer(std::array<double, 5> weights, double hysteresis = 0.05,
                    std::uint64_t cooldown_ns = 1'000'000'000ULL);
    Decision update(const Sample &sample);
private:
    std::array<double, 5> weights_;
    double hysteresis_;
    std::uint64_t cooldown_ns_;
    State state_ = State::normal;
    std::uint64_t last_transition_ns_ = 0;
    bool initialized_ = false;
};
const char *state_name(State state);
} // namespace coreflux
