// Opt-in desktop test: briefly selects VB-CABLE, then verifies all six saved
// defaults are restored. RAII restores the starting state even on a failure.
#define wmain sttsMicrophoneMain
#include "../Windows/native/microphone.cpp"
#undef wmain
#include <stdexcept>

static void require(bool passed, const char* message) { if (!passed) throw std::runtime_error(message); }

struct OriginalDefaults {
    ComPtr<IMMDeviceEnumerator> enumerator;
    ComPtr<IPolicyName> policy;
    std::array<std::wstring, 6> ids;
    ~OriginalDefaults() {
        if (policy) for (int i = 0; i < 6; ++i)
            if (!ids[i].empty()) policy->SetDefaultEndpoint(ids[i].c_str(), static_cast<ERole>(i % 3));
        clearDefaults();
    }
};

int main() {
    HKEY existing = nullptr;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, defaultsKey, 0, KEY_READ, &existing) == ERROR_SUCCESS) {
        RegCloseKey(existing); puts("An audio restoration is already pending; refusing to overwrite it."); return 1;
    }
    try {
        require(SUCCEEDED(CoInitializeEx(nullptr, COINIT_MULTITHREADED)), "COM initialization");
        OriginalDefaults original;
        require(SUCCEEDED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
            IID_PPV_ARGS(&original.enumerator))), "Enumerator");
        CLSID clsid{}; CLSIDFromString(L"{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}", &clsid);
        require(SUCCEEDED(CoCreateInstance(clsid, nullptr, CLSCTX_ALL, IID_PPV_ARGS(&original.policy))), "Policy");
        for (int i = 0; i < 6; ++i)
            require(SUCCEEDED(defaultID(original.enumerator.Get(), static_cast<EDataFlow>(i / 3),
                static_cast<ERole>(i % 3), original.ids[i])), "Read original default");
        ComPtr<IMMDeviceCollection> devices;
        require(SUCCEEDED(original.enumerator->EnumAudioEndpoints(eAll, DEVICE_STATE_ACTIVE, &devices)), "Enumerate");
        UINT count = 0; devices->GetCount(&count);
        std::array<std::wstring, 2> cables;
        for (UINT i = 0; i < count; ++i) {
            ComPtr<IMMDevice> device; devices->Item(i, &device);
            if (!cable(device.Get())) continue;
            ComPtr<IMMEndpoint> endpoint; device.As(&endpoint);
            EDataFlow flow; endpoint->GetDataFlow(&flow);
            LPWSTR id = nullptr; device->GetId(&id); cables[flow] = id; CoTaskMemFree(id);
        }
        require(!cables[0].empty() && !cables[1].empty(), "Both VB-CABLE endpoints required");
        require(SUCCEEDED(saveDefaults(original.enumerator.Get())), "Save defaults");
        int changed = 0;
        for (int i = 0; i < 6; ++i) if (!original.ids[i].empty() && original.ids[i] != cables[i / 3]) {
            require(SUCCEEDED(original.policy->SetDefaultEndpoint(cables[i / 3].c_str(), static_cast<ERole>(i % 3))), "Simulate installation selection");
            ++changed;
        }
        require(changed > 0, "No physical defaults available to exercise restoration");
        require(restoreDefaults(original.enumerator.Get(), false) == S_OK, "Restore defaults");
        for (int i = 0; i < 6; ++i) {
            std::wstring current;
            require(SUCCEEDED(defaultID(original.enumerator.Get(), static_cast<EDataFlow>(i / 3),
                static_cast<ERole>(i % 3), current)) && current == original.ids[i], "Default not restored");
        }
        require(RegOpenKeyExW(HKEY_CURRENT_USER, defaultsKey, 0, KEY_READ, &existing) == ERROR_FILE_NOT_FOUND,
            "Pending snapshot was not removed");
        printf("All six audio defaults verified; %d roles repaired.\n", changed);
        // After completion, choosing STTS manually must survive another helper
        // invocation. Then exercise the same restoration entry used at login.
        require(SUCCEEDED(original.policy->SetDefaultEndpoint(cables[0].c_str(), eCommunications)), "Manual choice");
        require(restoreDefaults(original.enumerator.Get(), false) == S_OK, "Completed restore is a no-op");
        std::wstring chosen;
        require(SUCCEEDED(defaultID(original.enumerator.Get(), eRender, eCommunications, chosen)) && chosen == cables[0],
            "A later manual choice was overwritten");
        for (int i = 0; i < 6; ++i) if (!original.ids[i].empty())
            require(SUCCEEDED(original.policy->SetDefaultEndpoint(original.ids[i].c_str(), static_cast<ERole>(i % 3))), "Reset test defaults");
        require(SUCCEEDED(saveDefaults(original.enumerator.Get())), "Save login defaults");
        for (int i = 0; i < 6; ++i) if (!original.ids[i].empty())
            require(SUCCEEDED(original.policy->SetDefaultEndpoint(cables[i / 3].c_str(), static_cast<ERole>(i % 3))), "Simulate delayed selection");
        require(restoreDefaults(original.enumerator.Get(), true) == S_OK, "Login restoration");
        for (int i = 0; i < 6; ++i) {
            std::wstring current;
            require(SUCCEEDED(defaultID(original.enumerator.Get(), static_cast<EDataFlow>(i / 3),
                static_cast<ERole>(i % 3), current)) && current == original.ids[i], "Login default not restored");
        }
        puts("Later manual choice and one-shot login restoration verified.");
    } catch (const std::exception& error) { fprintf(stderr, "%s\n", error.what()); return 1; }
    return 0;
}
