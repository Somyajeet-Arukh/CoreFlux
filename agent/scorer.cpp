#include "coreflux/scorer.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace coreflux {
const char *state_name(State state) {
    switch (state) {
    case State::normal: return "NORMAL";
    case State::watch: return "WATCH";
    case State::contention: return "CONTENTION";
    case State::severe: return "SEVERE";
    case State::unknown: return "UNKNOWN";
    }
    return "UNKNOWN";
}
Scorer::Scorer(std::array<double, 5> weights, double hysteresis, std::uint64_t cooldown_ns)
    : weights_(weights), hysteresis_(hysteresis), cooldown_ns_(cooldown_ns) {
    double sum = 0;
    for (double weight : weights_) {
        if (!std::isfinite(weight) || weight < 0) throw std::invalid_argument("invalid weight");
        sum += weight;
    }
    if (sum <= 0 || hysteresis < 0 || hysteresis >= 0.1)
        throw std::invalid_argument("invalid scoring configuration");
    for (double &weight : weights_) weight /= sum;
}
Decision Scorer::update(const Sample &sample) {
    double weighted = 0, coverage = 0;
    std::array<double, 5> contributions{};
    for (std::size_t i = 0; i < 5; ++i) {
        const double value = sample.signal[i];
        if (value == -1) continue;
        if (!std::isfinite(value) || value < 0 || value > 1)
            throw std::invalid_argument("signal outside 0..1");
        weighted += weights_[i] * value;
        coverage += weights_[i];
        contributions[i] = weights_[i] * value;
    }
    if (coverage < 0.5) return {State::unknown, 0, coverage, {}, "none", false};
    for (double &value : contributions) value /= coverage;
    const double score = weighted / coverage;
    const std::array<double, 3> thresholds{0.3, 0.6, 0.8};
    int level = static_cast<int>(state_);
    if (level > 3) level = 0;
    const bool cooled = !initialized_ || sample.timestamp_ns >= last_transition_ns_ + cooldown_ns_;
    bool changed = false;
    if (cooled) {
        if (level < 3 && score >= thresholds[level] + hysteresis_) { ++level; changed = true; }
        else if (level > 0 && score < thresholds[level - 1] - hysteresis_) { --level; changed = true; }
    }
    if (changed) { state_ = static_cast<State>(level); last_transition_ns_ = sample.timestamp_ns; }
    initialized_ = true;
    const auto dominant_index = std::distance(contributions.begin(),
        std::max_element(contributions.begin(), contributions.end()));
    return {state_, score, coverage, contributions, signal_names[dominant_index], changed};
}
} // namespace coreflux
