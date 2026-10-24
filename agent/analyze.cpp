#include "coreflux/scorer.hpp"
#include <array>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>

using namespace std;

static array<double, 5> parse_five(const string &value) {
    array<double, 5> result{};
    stringstream input(value);
    string field;
    for (double &number : result) {
        if (!getline(input, field, ',')) throw invalid_argument("expected five values");
        number = stod(field);
    }
    if (getline(input, field, ',')) throw invalid_argument("expected five values");
    return result;
}
int main(int argc, char **argv) {
    if (argc != 3 && argc != 4) {
        cerr << "usage: coreflux-analyze SIGNALS.csv OUTPUT.jsonl [five,comma,separated,weights]\n";
        return 2;
    }
    try {
        const auto weights = argc == 4 ? parse_five(argv[3]) :
            array<double, 5>{0.35, 0.2, 0.25, 0.1, 0.1};
        coreflux::Scorer scorer(weights);
        ifstream input(argv[1]);
        ofstream output(argv[2]);
        if (!input || !output) return 1;
        string line;
        getline(input, line); // header
        size_t rows = 0;
        uint64_t previous_timestamp = 0;
        while (getline(input, line)) {
            if (line.empty()) continue;
            const auto comma = line.find(',');
            if (comma == string::npos) throw invalid_argument("invalid row");
            const auto timestamp = stoull(line.substr(0, comma));
            if (rows && timestamp <= previous_timestamp)
                throw invalid_argument("timestamps must increase");
            previous_timestamp = timestamp;
            const auto signal = parse_five(line.substr(comma + 1));
            const auto decision = scorer.update({timestamp, signal});
            output << "{\"timestamp_ns\":" << timestamp << ",\"state\":\""
                   << coreflux::state_name(decision.state) << "\",\"score\":" << decision.score
                   << ",\"coverage\":" << decision.coverage << ",\"dominant\":\""
                   << decision.dominant << "\",\"transition\":" << (decision.transition ? "true" : "false")
                   << ",\"contributions\":{\"cpu_pressure\":" << decision.contributions[0]
                   << ",\"runnable_pressure\":" << decision.contributions[1]
                   << ",\"context_switch_intensity\":" << decision.contributions[2]
                   << ",\"memory_pressure\":" << decision.contributions[3]
                   << ",\"scheduler_latency\":" << decision.contributions[4] << "}}\n";
            ++rows;
        }
        if (!rows || !output) return 1;
        cout << "analyzed " << rows << " samples\n";
    } catch (const exception &error) {
        cerr << error.what() << '\n';
        return 1;
    }
}
