// Rename only the capture endpoint of the original VB-CABLE adapter.
// The signed driver, endpoint ID, playback endpoint and default devices stay intact.
#include <windows.h>
#include <mmdeviceapi.h>
#include <functiondiscoverykeys_devpkey.h>
#include <propvarutil.h>
#include <wrl/client.h>
#include <cstdio>
#include <string>
using Microsoft::WRL::ComPtr;

// Windows audio policy interface, used by Windows audio configuration utilities. Only the endpoint
// name property is written; no default-device or visibility methods are called.
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
};

static std::wstring value(IPropertyStore* store, REFPROPERTYKEY key) {
    PROPVARIANT prop{};
    if (FAILED(store->GetValue(key, &prop))) return {};
    std::wstring result = prop.vt == VT_LPWSTR ? prop.pwszVal : L"";
    PropVariantClear(&prop);
    return result;
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
    if (!rename && !restore && wcscmp(argv[1], L"--list") != 0) return 2;
    if (argc == 3) {
        FILE* output = nullptr;
        if (_wfreopen_s(&output, argv[2], L"w", stdout) != 0) return 2;
    }
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) return 1;
    ComPtr<IMMDeviceEnumerator> enumerator;
    hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&enumerator));
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
