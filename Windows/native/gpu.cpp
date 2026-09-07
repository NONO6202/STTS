#include <windows.h>
#include <dxgi1_2.h>
#include <d3d12.h>
#include <wrl/client.h>
#include <iostream>
#include <string>
using Microsoft::WRL::ComPtr;

int main() {
    ComPtr<IDXGIFactory1> factory;
    if (FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory)))) return 1;
    std::cout << "[";
    bool first = true;
    for (UINT index = 0;; ++index) {
        ComPtr<IDXGIAdapter1> adapter;
        if (factory->EnumAdapters1(index, &adapter) == DXGI_ERROR_NOT_FOUND) break;
        if (!adapter) continue;
        DXGI_ADAPTER_DESC1 desc{};
        if (FAILED(adapter->GetDesc1(&desc)) || (desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE)) continue;
        if (FAILED(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, __uuidof(ID3D12Device), nullptr))) continue;
        char buffer[1024]{};
        WideCharToMultiByte(CP_UTF8, 0, desc.Description, -1, buffer, sizeof(buffer), nullptr, nullptr);
        std::string name;
        for (const char c : std::string(buffer)) {
            if (c == '"' || c == '\\') name += '\\';
            name += c;
        }
        if (!first) std::cout << ",";
        first = false;
        std::cout << "{\"index\":" << index << ",\"memory\":" << desc.DedicatedVideoMemory
                  << ",\"name\":\"" << name << "\"}";
    }
    std::cout << "]\n";
}
