#include "../Windows/native/default_devices.h"
#include <cassert>
#include <array>
#include <cstdio>

int main() {
    DefaultDeviceRole role{L"headset"};
    assert(!role.shouldRestore(L"headset", false, true));
    assert(role.shouldRestore(L"cable", true, true));
    role.finished = true;
    assert(!role.shouldRestore(L"cable", true, true));
    DefaultDeviceRole chosen{L"headset"};
    assert(!chosen.shouldRestore(L"speakers", false, true));
    assert(!chosen.shouldRestore(L"cable", true, true));
    DefaultDeviceRole disconnected{L"headset"};
    assert(!disconnected.shouldRestore(L"cable", true, false));
    assert(!disconnected.shouldRestore(L"cable", true, true));
    DefaultDeviceRole missing{L""}, alreadyCable{L"cable"};
    assert(!missing.shouldRestore(L"cable", true, false));
    assert(!alreadyCable.shouldRestore(L"cable", true, true));
    DefaultDeviceRole delayed{L"headset"};
    assert(!delayed.shouldRestore(L"", false, true));
    assert(delayed.shouldRestore(L"cable", true, true));
    std::array<DefaultDeviceRole, 6> roles{{{L"speakers"}, {L"speakers"}, {L"headset"},
        {L"mic"}, {L"mic"}, {L"headset-mic"}}};
    for (auto& entry : roles) assert(entry.shouldRestore(L"cable", true, true));
    roles[0].finished = true;
    assert(!roles[0].shouldRestore(L"cable", true, true));
    for (size_t i = 1; i < roles.size(); ++i) assert(roles[i].shouldRestore(L"cable", true, true));
    puts("Audio default role tests passed.");
}
