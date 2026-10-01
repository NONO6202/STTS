#pragma once
#include <string>

// A role is retired after one successful repair, a disconnection, or another
// device choice. An installation must not keep enforcing an old preference.
struct DefaultDeviceRole {
    std::wstring original;
    bool finished = false;
    bool shouldRestore(const std::wstring& current, bool currentIsNewCable, bool originalActive) {
        if (finished) return false;
        if (original.empty() || !originalActive) { finished = true; return false; }
        if (current == original || current.empty()) return false;
        if (!currentIsNewCable) { finished = true; return false; }
        return true;
    }
};
