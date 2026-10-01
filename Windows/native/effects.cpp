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
    static constexpr int filters = 10;
    int rate, effect = 0, crushPeriod;
    double window, decay, release, phase = .25, ratio = 1, mix = 0, gate = 0, crushHold = 0, level = 0;
    std::uint64_t position = 0, period;
    std::vector<double> ring, echo, history, buzz;
    std::array<std::vector<double>, 4> combs;
    std::array<std::vector<double>, 2> allpasses;
    std::array<double, 4> damped{};
    std::array<std::size_t, 4> combAt{};
    std::array<std::size_t, 2> allpassAt{};
    std::size_t historyAt = 0, buzzAt = 0;
    std::array<double, 3> lfo{};
    std::array<double, filters> weights{};
    std::array<Section, 8> eq{};
    Effects(int hz, int echoFrames, int crush, const double* coefficients)
        : rate(hz), crushPeriod(crush), window(hz * .05), decay(std::exp(-1.0 / (hz * .015))), release(std::exp(-1.0 / (hz * .08))),
          ring(static_cast<std::size_t>(window) + 512), echo(echoFrames), history(static_cast<std::size_t>(hz * .05)),
          buzz(static_cast<std::size_t>(hz / 100)) {
        period = static_cast<std::uint64_t>(rate) * ring.size() * echo.size();
        for (int i = 0; i < 8; ++i) {
            const double* c = coefficients + i * 6;
            eq[i] = {c[0], c[1], c[2], c[4], c[5], 0, 0};
        }
        // Freeverb's comb and allpass lengths, scaled from 44.1 kHz.
        const std::array<double, 4> combSeconds{1116 / 44100.0, 1188 / 44100.0, 1277 / 44100.0, 1356 / 44100.0};
        const std::array<double, 2> allpassSeconds{556 / 44100.0, 441 / 44100.0};
        for (int i = 0; i < 4; ++i) combs[i].assign(static_cast<std::size_t>(combSeconds[i] * hz), 0);
        for (int i = 0; i < 2; ++i) allpasses[i].assign(static_cast<std::size_t>(allpassSeconds[i] * hz), 0);
    }
    double past(double delay) const {
        double location = static_cast<double>(historyAt) - delay;
        auto size = static_cast<std::int64_t>(history.size());
        auto base = static_cast<std::int64_t>(std::floor(location));
        double fraction = location - static_cast<double>(base);
        auto a = static_cast<std::size_t>((base % size + size) % size);
        return history[a] * (1 - fraction) + history[(a + 1) % history.size()] * fraction;
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
        if (nextEffect < 0 || nextEffect > filters) nextEffect = 0;
        if (effect != nextEffect) {
            if (nextEffect == 1) std::fill(buzz.begin(), buzz.end(), 0);
            if (nextEffect == 3) { std::fill(echo.begin(), echo.end(), 0); gate = 0; }
            if (nextEffect == 2) for (int j = 0; j < 4; ++j) eq[j].z1 = eq[j].z2 = 0;
            if (nextEffect == 4) for (int j = 4; j < 6; ++j) eq[j].z1 = eq[j].z2 = 0;
            if (nextEffect == 8) {
                for (auto& comb : combs) std::fill(comb.begin(), comb.end(), 0);
                for (auto& allpass : allpasses) std::fill(allpass.begin(), allpass.end(), 0);
                damped.fill(0);
            }
            if (nextEffect == 10) for (int j = 6; j < 8; ++j) eq[j].z1 = eq[j].z2 = 0;
            effect = nextEffect;
        }
        double targetRatio = std::pow(2.0, pitch / 12), targetMix = std::abs(pitch) > .001 ? 1 : 0;
        std::array<double, filters> target{};
        if (effect > 0) target[effect - 1] = strength;
        // Preserve all delay positions/history even when the audible result is dry.
        if (pitch == 0 && ratio == 1 && mix == 0 && effect == 0 &&
            std::all_of(weights.begin(), weights.end(), [](double x) { return x == 0; })) {
            for (std::size_t i = 0; i < count; ++i) {
                double x = std::isfinite(input[i]) ? input[i] : 0;
                ring[position % ring.size()] = x; echo[position % echo.size()] = 0;
                history[historyAt] = x; historyAt = (historyAt + 1) % history.size();
                level = std::max(std::abs(x), level * release);
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
            std::array<bool, filters> active{};
            for (int j = 0; j < filters; ++j) {
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
                history[historyAt] = dry;
                // High-gain effects would turn room noise into hiss; fade them in between about -44 and -34 dBFS.
                level = std::max(std::abs(dry), level * release);
                double gated = dry * std::clamp((level - .006) / .014, 0.0, 1.0);
                std::array<double, filters> w{};
                for (int j = 0; j < filters; ++j) w[j] = target[j] + (startWeights[j] - target[j]) * smooth[i];
                double clock = static_cast<double>(index % rate) / rate;
                for (int j = 0; j < 3; ++j) {
                    static constexpr std::array<double, 3> hertz{.8, 1.1, 5};
                    lfo[j] += hertz[j] / rate; lfo[j] -= std::floor(lfo[j]);
                }
                double fed = 0;
                if (active[0]) {
                    // Ring modulation through a short metallic comb.
                    fed = .9 * std::tanh(2.5 * gated) * std::cos(2 * pi * 80 * clock) + .45 * buzz[buzzAt];
                    y += w[0] * (.8 * fed - dry);
                }
                buzz[buzzAt] = fed; buzzAt = (buzzAt + 1) % buzz.size();
                if (active[1]) {
                    double filtered = dry;
                    for (int j = 0; j < 4; ++j) filtered = eq[j].run(filtered);
                    y += w[1] * (.7 * std::tanh(4 * filtered) - dry);
                }
                if (active[3]) {
                    double filtered = eq[5].run(eq[4].run(gated));
                    y += w[3] * (.65 * std::tanh(16 * filtered) - dry);
                }
                if (active[4]) y += w[4] * (.7 * std::tanh(18 * gated) - dry);
                if (active[5]) {
                    if (index % crushPeriod == 0) crushHold = std::nearbyint(.7 * std::tanh(4 * gated) * 127) / 127;
                    y += w[5] * (crushHold - dry);
                }
                if (active[6]) {
                    double amplitude = .5 + .5 * std::cos(2 * pi * 8 * clock);
                    y += w[6] * (dry * amplitude * amplitude * amplitude - dry);
                }
                if (active[7]) {
                    double wet = 0;
                    for (int j = 0; j < 4; ++j) {
                        double out = combs[j][combAt[j]];
                        damped[j] = out * .75 + damped[j] * .25;
                        combs[j][combAt[j]] = dry * .3 + damped[j] * .82; wet += out;
                    }
                    for (int j = 0; j < 2; ++j) {
                        double stored = allpasses[j][allpassAt[j]];
                        allpasses[j][allpassAt[j]] = wet + stored * .5; wet = stored - wet;
                    }
                    y += w[7] * .8 * wet;
                }
                for (int j = 0; j < 4; ++j) combAt[j] = (combAt[j] + 1) % combs[j].size();
                for (int j = 0; j < 2; ++j) allpassAt[j] = (allpassAt[j] + 1) % allpasses[j].size();
                if (active[8]) {
                    double first = past(rate * (.020 + .003 * std::sin(2 * pi * lfo[0])));
                    double second = past(rate * (.027 + .003 * std::sin(2 * pi * lfo[1])));
                    y += w[8] * .35 * (first + second);
                }
                if (active[9]) {
                    double wobble = past(rate * (.006 + .003 * std::sin(2 * pi * lfo[2])));
                    y += w[9] * (1.4 * eq[7].run(eq[6].run(wobble)) - dry);
                }
                historyAt = (historyAt + 1) % history.size();
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
