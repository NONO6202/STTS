// Streaming effects behind a small C ABI; no allocations inside process().
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

#ifdef _WIN32
#define STTS_EXPORT extern "C" __declspec(dllexport)
#else
#define STTS_EXPORT extern "C" __attribute__((visibility("default")))
#endif

namespace {
constexpr double pi = 3.14159265358979323846;
struct Section {
    double b0, b1, b2, a1, a2, z1 = 0, z2 = 0;
    double run(double x) {
        double y = b0 * x + z1;
        z1 = b1 * x - a1 * y + z2; z2 = b2 * x - a2 * y;
        return y;
    }
};
struct Effects {
    int rate, effect = 0, crushPeriod;
    double window, decay, phase = .25, ratio = 1, mix = 0, gate = 0, crushHold = 0;
    std::uint64_t position = 0, period;
    std::vector<double> ring, echo;
    std::array<double, 7> weights{};
    std::array<Section, 6> eq{};
    Effects(int hz, int echoFrames, int crush, const double* coefficients)
        : rate(hz), crushPeriod(crush), window(hz * .05), decay(std::exp(-1.0 / (hz * .015))),
          ring(static_cast<std::size_t>(window) + 512), echo(echoFrames) {
        period = static_cast<std::uint64_t>(rate) * ring.size() * echo.size();
        for (int i = 0; i < 6; ++i) {
            const double* c = coefficients + i * 6;
            eq[i] = {c[0], c[1], c[2], c[4], c[5], 0, 0};
        }
    }
    double head(std::uint64_t index, double p) const {
        double location = static_cast<double>(index) - 129 - p * window;
        auto base = static_cast<std::int64_t>(std::floor(location));
        double fraction = location - static_cast<double>(base);
        auto size = static_cast<std::int64_t>(ring.size());
        auto a = static_cast<std::size_t>((base % size + size) % size);
        return ring[a] * (1 - fraction) + ring[(a + 1) % ring.size()] * fraction;
    }
    void process(const double* input, float* output, std::size_t count, double pitch, int nextEffect, double strength) {
        pitch = std::isfinite(pitch) ? std::clamp(pitch, -12.0, 12.0) : 0;
        strength = std::isfinite(strength) ? std::clamp(strength, 0.0, 1.0) : 0;
        if (effect != nextEffect) {
            if (nextEffect == 3) { std::fill(echo.begin(), echo.end(), 0); gate = 0; }
            if (nextEffect == 2) for (int j = 0; j < 4; ++j) eq[j].z1 = eq[j].z2 = 0;
            if (nextEffect == 4) for (int j = 4; j < 6; ++j) eq[j].z1 = eq[j].z2 = 0;
            effect = nextEffect;
        }
        double targetRatio = std::pow(2.0, pitch / 12), targetMix = std::abs(pitch) > .001 ? 1 : 0;
        std::array<double, 7> target{};
        if (effect > 0 && effect <= 7) target[effect - 1] = strength;
        // Preserve all delay positions/history even when the audible result is dry.
        if (pitch == 0 && ratio == 1 && mix == 0 && effect == 0 &&
            std::all_of(weights.begin(), weights.end(), [](double x) { return x == 0; })) {
            for (std::size_t i = 0; i < count; ++i) {
                double x = std::isfinite(input[i]) ? input[i] : 0;
                ring[position % ring.size()] = x; echo[position % echo.size()] = 0;
                output[i] = static_cast<float>(std::clamp(x, -1.0, 1.0));
                position = (position + 1) % period;
            }
            gate *= std::pow(decay, static_cast<double>(count));
            return;
        }
        for (std::size_t offset = 0; offset < count; offset += 128) {
            const std::size_t n = std::min<std::size_t>(128, count - offset);
            std::array<double, 128> x{}, smooth{}, phases{};
            const double startRatio = ratio, startMix = mix, startPhase = phase, startGate = gate;
            const auto startWeights = weights;
            double phaseDelta = 0;
            for (std::size_t i = 0; i < n; ++i) {
                x[i] = std::isfinite(input[offset + i]) ? input[offset + i] : 0;
                ring[(position + i) % ring.size()] = x[i];
                smooth[i] = std::pow(decay, static_cast<double>(i + 1));
                ratio = targetRatio + (startRatio - targetRatio) * smooth[i];
                phaseDelta += (1 - ratio) / window;
                phases[i] = startPhase + phaseDelta; phases[i] -= std::floor(phases[i]);
            }
            phase = phases[n - 1];
            std::array<bool, 7> active{};
            for (int j = 0; j < 7; ++j) {
                weights[j] = target[j] + (startWeights[j] - target[j]) * smooth[n - 1];
                active[j] = std::max(target[j] + (startWeights[j] - target[j]) * smooth[0], weights[j]) > 1e-6;
            }
            for (std::size_t i = 0; i < n; ++i) {
                auto index = position + i;
                double sine = std::sin(pi * phases[i]), blend = sine * sine;
                double other = phases[i] + .5; other -= std::floor(other);
                double shifted = head(index, phases[i]) * blend + head(index, other) * (1 - blend);
                mix = targetMix + (startMix - targetMix) * smooth[i];
                double dry = x[i] + (shifted - x[i]) * mix, y = dry;
                std::array<double, 7> w{};
                for (int j = 0; j < 7; ++j) w[j] = target[j] + (startWeights[j] - target[j]) * smooth[i];
                double clock = static_cast<double>(index % rate) / rate;
                if (active[0]) y += w[0] * (.65 * std::tanh(6 * dry) * std::cos(2 * pi * 80 * clock) - dry);
                if (active[1]) {
                    double filtered = dry;
                    for (int j = 0; j < 4; ++j) filtered = eq[j].run(filtered);
                    y += w[1] * (.7 * std::tanh(4 * filtered) - dry);
                }
                if (active[3]) {
                    double filtered = eq[5].run(eq[4].run(dry));
                    y += w[3] * (.65 * std::tanh(16 * filtered) - dry);
                }
                if (active[4]) y += w[4] * (.7 * std::tanh(18 * dry) - dry);
                if (active[5]) {
                    if (index % crushPeriod == 0) crushHold = std::nearbyint(.7 * std::tanh(4 * dry) * 127) / 127;
                    y += w[5] * (crushHold - dry);
                }
                if (active[6]) {
                    double amplitude = .5 + .5 * std::cos(2 * pi * 8 * clock);
                    y += w[6] * (dry * amplitude * amplitude * amplitude - dry);
                }
                auto echoIndex = index % echo.size(); double delayed = echo[echoIndex];
                double targetGate = effect == 3 ? 1 : 0;
                gate = targetGate + (startGate - targetGate) * smooth[i];
                echo[echoIndex] = effect == 3 || weights[2] > 1e-6 ? dry * gate + .55 * delayed : 0;
                y += w[2] * delayed;
                output[offset + i] = static_cast<float>(std::clamp(y, -1.0, 1.0));
            }
            position = (position + n) % period;
        }
    }
};
}
STTS_EXPORT void* stts_effects_create(int rate, int echoFrames, int crushPeriod, const double* coefficients) noexcept {
    if (rate < 8000 || rate > 384000 || echoFrames < 1 || echoFrames > rate || crushPeriod < 1 || !coefficients) return nullptr;
    try { return new Effects(rate, echoFrames, crushPeriod, coefficients); } catch (...) { return nullptr; }
}
STTS_EXPORT void stts_effects_destroy(void* state) noexcept { delete static_cast<Effects*>(state); }
STTS_EXPORT void stts_effects_process(void* state, const double* samples, float* output, std::size_t count,
                                      double pitch, int effect, double strength) noexcept {
    if (state && samples && output) static_cast<Effects*>(state)->process(samples, output, count, pitch, effect, strength);
}
