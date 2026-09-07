// STTS process-scoped WASAPI capture. Windows 11, 16 kHz mono PCM16 to stdout.
// Uses the documented ActivateAudioInterfaceAsync process-loopback API.
#include <windows.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <mmdeviceapi.h>
#include <wrl.h>
#include <wrl/implements.h>
#include <cstdio>
#include <fcntl.h>
#include <io.h>
#include <vector>
using namespace Microsoft::WRL;
class Activation final : public RuntimeClass<RuntimeClassFlags<ClassicCom>,
    FtmBase, IActivateAudioInterfaceCompletionHandler> {
public:
    HANDLE done = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    HRESULT result = E_FAIL;
    ComPtr<IAudioClient> client;
    ~Activation() { CloseHandle(done); }
    STDMETHOD(ActivateCompleted)(IActivateAudioInterfaceAsyncOperation* op) override {
        ComPtr<IUnknown> value;
        HRESULT activation = E_FAIL;
        result = op->GetActivateResult(&activation, &value);
        if (SUCCEEDED(result)) result = activation;
        if (SUCCEEDED(result)) result = value.As(&client);
        SetEvent(done);
        return S_OK;
    }
};
static int fail(const char* step, HRESULT hr) {
    fprintf(stderr, "%s: 0x%08lx\n", step, static_cast<unsigned long>(hr));
    return 1;
}
int wmain(int argc, wchar_t** argv) {
    if (argc != 2) { fprintf(stderr, "Usage: STTSCapture.exe DISCORD_PID\n"); return 2; }
    wchar_t* end = nullptr;
    DWORD pid = wcstoul(argv[1], &end, 10);
    if (!pid || !end || *end) return 2;
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) return fail("CoInitializeEx", hr);
    auto activation = Make<Activation>();
    AUDIOCLIENT_ACTIVATION_PARAMS params = {};
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    params.ProcessLoopbackParams.TargetProcessId = pid;
    params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
    PROPVARIANT prop = {};
    prop.vt = VT_BLOB;
    prop.blob.cbSize = sizeof(params);
    prop.blob.pBlobData = reinterpret_cast<BYTE*>(&params);
    ComPtr<IActivateAudioInterfaceAsyncOperation> operation;
    hr = ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        __uuidof(IAudioClient), &prop, activation.Get(), &operation);
    if (FAILED(hr)) return fail("ActivateAudioInterfaceAsync", hr);
    if (WaitForSingleObject(activation->done, 15000) != WAIT_OBJECT_0) return fail("Activation timeout", E_FAIL);
    if (FAILED(activation->result)) return fail("Process loopback", activation->result);
    WAVEFORMATEX format = {};
    format.wFormatTag = WAVE_FORMAT_PCM;
    format.nChannels = 1;
    format.nSamplesPerSec = 16000;
    format.wBitsPerSample = 16;
    format.nBlockAlign = 2;
    format.nAvgBytesPerSec = 32000;
    hr = activation->client->Initialize(AUDCLNT_SHAREMODE_SHARED,
        AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM,
        0, 0, &format, nullptr);
    if (FAILED(hr)) return fail("Initialize", hr);
    HANDLE ready = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    hr = activation->client->SetEventHandle(ready);
    if (FAILED(hr)) return fail("SetEventHandle", hr);
    ComPtr<IAudioCaptureClient> capture;
    hr = activation->client->GetService(IID_PPV_ARGS(&capture));
    if (FAILED(hr)) return fail("GetService", hr);
    _setmode(_fileno(stdout), _O_BINARY);
    setvbuf(stdout, nullptr, _IONBF, 0);
    hr = activation->client->Start();
    if (FAILED(hr)) return fail("Start", hr);
    HANDLE target = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!target) return fail("OpenProcess", HRESULT_FROM_WIN32(GetLastError()));
    HANDLE waits[] = {ready, target};
    bool running = true;
    while (running) {
        DWORD wait = WaitForMultipleObjects(2, waits, FALSE, 3000);
        if (wait == WAIT_OBJECT_0 + 1 || wait == WAIT_FAILED) break;
        UINT32 count = 0;
        hr = capture->GetNextPacketSize(&count);
        if (FAILED(hr)) return fail("GetNextPacketSize", hr);
        while (count) {
            BYTE* data = nullptr; UINT32 frames = 0; DWORD flags = 0;
            hr = capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr);
            if (FAILED(hr)) return fail("GetBuffer", hr);
            const size_t bytes = static_cast<size_t>(frames) * 2;
            std::vector<BYTE> silence;
            if (flags & AUDCLNT_BUFFERFLAGS_SILENT) { silence.resize(bytes); data = silence.data(); }
            if (fwrite(data, 1, bytes, stdout) != bytes) running = false;
            capture->ReleaseBuffer(frames);
            if (!running) break;
            hr = capture->GetNextPacketSize(&count);
            if (FAILED(hr)) return fail("GetNextPacketSize", hr);
        }
    }
    activation->client->Stop();
    CloseHandle(target); CloseHandle(ready);
    return 0;
}
