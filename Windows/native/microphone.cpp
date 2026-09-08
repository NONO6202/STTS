// Rename VB-CABLE capture and preserve the installing user's audio defaults.
#include <windows.h>
#include <mmdeviceapi.h>
#include <functiondiscoverykeys_devpkey.h>
#include <propvarutil.h>
#include <wrl/client.h>
#include <cstdio>
#include <string>
#include <array>
#include "default_devices.h"
using Microsoft::WRL::ComPtr;

// Audio policy interface used by AudioDeviceCmdlets. Property access includes
// bFxStore; SetDefaultEndpoint follows SetPropertyValue in this vtable.
struct __declspec(uuid("F8679F50-850A-41CF-9C72-430F290290C8")) IPolicyName : IUnknown {
    virtual HRESULT STDMETHODCALLTYPE Unused1() = 0;
    virtual HRESULT STDMETHODCALLTYPE Unused2() = 0;
    virtual HRESULT STDMETHODCALLTYPE Unused3() = 0;
    virtual HRESULT STDMETHODCALLTYPE Unused4() = 0;
    virtual HRESULT STDMETHODCALLTYPE Unused5() = 0;
    virtual HRESULT STDMETHODCALLTYPE Unused6() = 0;
    virtual HRESULT STDMETHODCALLTYPE Unused7() = 0;
    virtual HRESULT STDMETHODCALLTYPE Unused8() = 0;
    virtual HRESULT STDMETHODCALLTYPE GetPropertyValue(LPCWSTR, BOOL, const PROPERTYKEY*, PROPVARIANT*) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetPropertyValue(LPCWSTR, BOOL, const PROPERTYKEY*, const PROPVARIANT*) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetDefaultEndpoint(LPCWSTR, ERole) = 0;
};

static std::wstring value(IPropertyStore* store, REFPROPERTYKEY key) {
    PROPVARIANT prop{};
    if (FAILED(store->GetValue(key, &prop))) return {};
    std::wstring result = prop.vt == VT_LPWSTR ? prop.pwszVal : L"";
    PropVariantClear(&prop);
    return result;
}

static constexpr auto defaultsKey = L"SOFTWARE\\STTS\\PendingAudioDefaults";
static constexpr auto runOnceKey = L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\RunOnce";
static constexpr auto resumeName = L"STTS Restore Audio Defaults";

static HRESULT defaultID(IMMDeviceEnumerator* enumerator, EDataFlow flow, ERole role, std::wstring& id) {
    ComPtr<IMMDevice> device;
    HRESULT hr = enumerator->GetDefaultAudioEndpoint(flow, role, &device);
    id.clear();
    if (hr == HRESULT_FROM_WIN32(ERROR_NOT_FOUND)) return S_OK;
    LPWSTR raw = nullptr;
    if (SUCCEEDED(hr)) hr = device->GetId(&raw);
    if (SUCCEEDED(hr)) { id = raw; CoTaskMemFree(raw); }
    return hr;
}

static bool cable(IMMDevice* device) {
    ComPtr<IPropertyStore> properties;
    return SUCCEEDED(device->OpenPropertyStore(STGM_READ, &properties)) &&
        value(properties.Get(), PKEY_DeviceInterface_FriendlyName) == L"VB-Audio Virtual Cable";
}

static std::wstring roleName(int index) { return std::to_wstring(index / 3) + L"-" + std::to_wstring(index % 3); }

static ULONGLONG now() {
    FILETIME time{}; GetSystemTimeAsFileTime(&time);
    ULARGE_INTEGER value{}; value.LowPart = time.dwLowDateTime; value.HighPart = time.dwHighDateTime;
    return value.QuadPart;
}

static void clearDefaults() {
    RegDeleteTreeW(HKEY_CURRENT_USER, defaultsKey);
    HKEY key = nullptr;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, runOnceKey, 0, KEY_SET_VALUE, &key) == ERROR_SUCCESS) {
        RegDeleteValueW(key, resumeName); RegCloseKey(key);
    }
}

static HRESULT saveDefaults(IMMDeviceEnumerator* enumerator) {
    // Only the installer calls this, before installing a missing driver. Run in
    // the original user's session, never in a different administrator's HKCU.
    std::array<std::wstring, 6> ids;
    for (int i = 0; i < 6; ++i) {
        HRESULT hr = defaultID(enumerator, static_cast<EDataFlow>(i / 3), static_cast<ERole>(i % 3), ids[i]);
        if (FAILED(hr)) return hr;
    }
    clearDefaults();
    auto stamp = now();
    LSTATUS status = RegSetKeyValueW(HKEY_CURRENT_USER, defaultsKey, L"Created", REG_QWORD, &stamp, sizeof(stamp));
    for (int i = 0; status == ERROR_SUCCESS && i < 6; ++i) {
        status = RegSetKeyValueW(HKEY_CURRENT_USER, defaultsKey, roleName(i).c_str(), REG_SZ,
            ids[i].c_str(), static_cast<DWORD>((ids[i].size() + 1) * sizeof(wchar_t)));
    }
    wchar_t executable[32768]{};
    DWORD length = GetModuleFileNameW(nullptr, executable, ARRAYSIZE(executable));
    if (!length || length >= ARRAYSIZE(executable)) { clearDefaults(); return E_FAIL; }
    std::wstring command = L"\"" + std::wstring(executable) + L"\" --resume-defaults";
    // RunOnce commands are limited to 260 characters. Fail before driver setup
    // instead of silently losing restoration after a delayed device install.
    if (command.size() >= 260) { clearDefaults(); return HRESULT_FROM_WIN32(ERROR_FILENAME_EXCED_RANGE); }
    if (status == ERROR_SUCCESS) status = RegSetKeyValueW(HKEY_CURRENT_USER, runOnceKey, resumeName,
        REG_SZ, command.c_str(), static_cast<DWORD>((command.size() + 1) * sizeof(wchar_t)));
    if (status != ERROR_SUCCESS) clearDefaults();
    return HRESULT_FROM_WIN32(status);
}

static HRESULT restoreDefaults(IMMDeviceEnumerator* enumerator, bool resume) {
    ULONGLONG stamp = 0; DWORD bytes = sizeof(stamp);
    auto status = RegGetValueW(HKEY_CURRENT_USER, defaultsKey, L"Created", RRF_RT_REG_QWORD, nullptr, &stamp, &bytes);
    if (status == ERROR_FILE_NOT_FOUND) return S_OK;
    if (status != ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
    if (now() < stamp || now() - stamp > 24ULL * 60 * 60 * 10000000) { clearDefaults(); return S_OK; }
    std::array<DefaultDeviceRole, 6> roles;
    for (int i = 0; i < 6; ++i) {
        wchar_t id[1024]{}; bytes = sizeof(id);
        status = RegGetValueW(HKEY_CURRENT_USER, defaultsKey, roleName(i).c_str(), RRF_RT_REG_SZ, nullptr, id, &bytes);
        if (status != ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
        roles[i].original = id;
    }
    CLSID clsid{};
    HRESULT hr = CLSIDFromString(L"{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}", &clsid);
    ComPtr<IPolicyName> policy;
    if (SUCCEEDED(hr)) hr = CoCreateInstance(clsid, nullptr, CLSCTX_ALL, IID_PPV_ARGS(&policy));
    if (FAILED(hr)) return hr;
    ULONGLONG deadline = GetTickCount64() + (resume ? 30000 : 5000), readySince = 0;
    std::array<bool, 2> ready{};
    do {
        ready = {};
        ComPtr<IMMDeviceCollection> devices;
        hr = enumerator->EnumAudioEndpoints(eAll, DEVICE_STATE_ACTIVE, &devices);
        UINT count = 0;
        if (SUCCEEDED(hr)) hr = devices->GetCount(&count);
        if (FAILED(hr)) return hr;
        for (UINT i = 0; i < count; ++i) {
            ComPtr<IMMDevice> device; ComPtr<IMMEndpoint> endpoint;
            if (SUCCEEDED(devices->Item(i, &device)) && cable(device.Get()) && SUCCEEDED(device.As(&endpoint))) {
                EDataFlow flow;
                if (SUCCEEDED(endpoint->GetDataFlow(&flow)) && flow < eAll) ready[flow] = true;
            }
        }
        std::array<bool, 6> repair{};
        for (int i = 0; i < 6; ++i) {
            auto& role = roles[i];
            if (role.finished || role.original.empty()) continue;
            std::wstring current;
            hr = defaultID(enumerator, static_cast<EDataFlow>(i / 3), static_cast<ERole>(i % 3), current);
            if (FAILED(hr)) return hr;
            ComPtr<IMMDevice> original, selected;
            DWORD state = 0;
            bool active = SUCCEEDED(enumerator->GetDevice(role.original.c_str(), &original)) &&
                SUCCEEDED(original->GetState(&state)) && state == DEVICE_STATE_ACTIVE;
            bool selectedCable = !current.empty() && SUCCEEDED(enumerator->GetDevice(current.c_str(), &selected)) && cable(selected.Get());
            repair[i] = role.shouldRestore(current, selectedCable, active);
            if (role.finished) {
                status = RegSetKeyValueW(HKEY_CURRENT_USER, defaultsKey, roleName(i).c_str(), REG_SZ, L"", sizeof(wchar_t));
                if (status != ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
            }
        }
        // Snapshot decisions before writing: setting the console role can also
        // change multimedia on Windows. Our own write is not a new user choice.
        for (int i = 0; i < 6; ++i) {
            auto& role = roles[i];
            if (repair[i]) {
                hr = policy->SetDefaultEndpoint(role.original.c_str(), static_cast<ERole>(i % 3));
                if (FAILED(hr)) return hr;
                std::wstring verified;
                hr = defaultID(enumerator, static_cast<EDataFlow>(i / 3), static_cast<ERole>(i % 3), verified);
                if (FAILED(hr) || verified != role.original) return E_FAIL;
                role.finished = true;
                wprintf(L"Restored audio role %ls\n", roleName(i).c_str());
            }
            if (repair[i]) {
                // Retire this role across reboot too; preserve later user changes.
                status = RegSetKeyValueW(HKEY_CURRENT_USER, defaultsKey, roleName(i).c_str(), REG_SZ, L"", sizeof(wchar_t));
                if (status != ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
            }
        }
        if (ready[0] && ready[1]) {
            if (!readySince) readySince = GetTickCount64();
            if (GetTickCount64() - readySince >= 1500) { clearDefaults(); return S_OK; }
        } else { readySince = 0; }
        Sleep(100);
    } while (GetTickCount64() < deadline);
    // Only unresolved flows survive to the one-shot login retry. There is no
    // background agent enforcing defaults during normal application use.
    if (resume) { clearDefaults(); return HRESULT_FROM_WIN32(ERROR_TIMEOUT); }
    for (int i = 0; i < 6; ++i) {
        if (ready[i / 3]) RegSetKeyValueW(HKEY_CURRENT_USER, defaultsKey, roleName(i).c_str(), REG_SZ, L"", sizeof(wchar_t));
    }
    return S_FALSE;
}

static HRESULT renameDevice(IMMDevice* device, bool restore) {
    ComPtr<IPropertyStore> store;
    HRESULT hr = device->OpenPropertyStore(STGM_READ, &store);
    if (FAILED(hr)) return hr;
    auto current = value(store.Get(), PKEY_Device_DeviceDesc);
    LPWSTR id = nullptr;
    hr = device->GetId(&id);
    if (FAILED(hr)) return hr;
    std::wstring endpoint = id;
    std::wstring key = L"SOFTWARE\\STTS\\MicrophoneNames\\" + endpoint;
    CoTaskMemFree(id);
    wchar_t original[1024]{};
    DWORD size = sizeof(original);
    LSTATUS status = RegGetValueW(HKEY_LOCAL_MACHINE, key.c_str(), L"OriginalDescription",
                                 RRF_RT_REG_SZ, nullptr, original, &size);
    if (restore && (status != ERROR_SUCCESS || current != L"STTS")) return S_OK;
    if (!restore && current == L"STTS") return S_OK;
    if (!restore) {
        if (status != ERROR_SUCCESS && status != ERROR_FILE_NOT_FOUND) return HRESULT_FROM_WIN32(status);
        status = RegSetKeyValueW(HKEY_LOCAL_MACHINE, key.c_str(), L"OriginalDescription", REG_SZ,
                                current.c_str(), static_cast<DWORD>((current.size() + 1) * sizeof(wchar_t)));
        if (status != ERROR_SUCCESS) return HRESULT_FROM_WIN32(status);
    }
    const wchar_t* name = restore ? original : L"STTS";
    CLSID clsid{};
    hr = CLSIDFromString(L"{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}", &clsid);
    ComPtr<IPolicyName> policy;
    if (SUCCEEDED(hr)) hr = CoCreateInstance(clsid, nullptr, CLSCTX_ALL, IID_PPV_ARGS(&policy));
    if (FAILED(hr)) return hr;
    PROPVARIANT prop{};
    hr = InitPropVariantFromString(name, &prop);
    if (SUCCEEDED(hr)) hr = policy->SetPropertyValue(endpoint.c_str(), FALSE, &PKEY_Device_DeviceDesc, &prop);
    PropVariantClear(&prop);
    store.Reset();
    if (SUCCEEDED(hr)) hr = device->OpenPropertyStore(STGM_READ, &store);
    if (SUCCEEDED(hr) && value(store.Get(), PKEY_Device_DeviceDesc) != name) hr = E_FAIL;
    return hr;
}

int wmain(int argc, wchar_t** argv) {
    if (argc < 2 || argc > 3) return 2;
    bool rename = wcscmp(argv[1], L"--rename") == 0;
    bool restore = wcscmp(argv[1], L"--restore") == 0;
    bool save = wcscmp(argv[1], L"--save-defaults") == 0;
    bool defaults = wcscmp(argv[1], L"--restore-defaults") == 0;
    bool resume = wcscmp(argv[1], L"--resume-defaults") == 0;
    if (!rename && !restore && !save && !defaults && !resume && wcscmp(argv[1], L"--list") != 0) return 2;
    if (argc == 3) {
        FILE* output = nullptr;
        if (_wfreopen_s(&output, argv[2], L"w", stdout) != 0) return 2;
    }
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) return 1;
    ComPtr<IMMDeviceEnumerator> enumerator;
    hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&enumerator));
    if (save || defaults || resume) {
        if (SUCCEEDED(hr)) hr = save ? saveDefaults(enumerator.Get()) : restoreDefaults(enumerator.Get(), resume);
        wprintf(L"Audio defaults: 0x%08lx\n", hr);
        return FAILED(hr) ? 1 : hr == S_FALSE ? 3010 : 0;
    }
    ComPtr<IMMDeviceCollection> devices;
    if (SUCCEEDED(hr)) hr = enumerator->EnumAudioEndpoints(eCapture, DEVICE_STATE_ACTIVE | DEVICE_STATE_DISABLED, &devices);
    UINT count = 0, matched = 0;
    if (SUCCEEDED(hr)) hr = devices->GetCount(&count);
    for (UINT index = 0; SUCCEEDED(hr) && index < count; ++index) {
        ComPtr<IMMDevice> device;
        ComPtr<IPropertyStore> store;
        hr = devices->Item(index, &device);
        if (SUCCEEDED(hr)) hr = device->OpenPropertyStore(STGM_READ, &store);
        if (FAILED(hr)) break;
        if (value(store.Get(), PKEY_DeviceInterface_FriendlyName) != L"VB-Audio Virtual Cable") continue;
        ++matched;
        if (rename || restore) hr = renameDevice(device.Get(), restore);
        wprintf(L"VB-CABLE capture: %ls (0x%08lx)\n", value(store.Get(), PKEY_Device_FriendlyName).c_str(), hr);
    }
    if (!matched && !restore && SUCCEEDED(hr)) hr = HRESULT_FROM_WIN32(ERROR_NOT_FOUND);
    wprintf(L"Result: 0x%08lx; matched: %u\n", hr, matched);
    return FAILED(hr) ? 1 : 0;
}
