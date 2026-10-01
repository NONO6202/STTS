"""Select working accelerators; keep CPU execution available on every machine."""
import gc
import json
import os
from pathlib import Path
import subprocess
import sys

DLL_DIRECTORIES = []


def cuda_device():
    import torch
    if os.name == 'nt':
        directory = str(Path(torch.__file__).parent / 'lib')
        if not DLL_DIRECTORIES: DLL_DIRECTORIES.append(os.add_dll_directory(directory))
        if directory not in os.environ.get('PATH', '').split(os.pathsep):
            os.environ['PATH'] = directory + os.pathsep + os.environ.get('PATH', '')
    if not torch.cuda.is_available(): return None
    devices = []
    for index in range(torch.cuda.device_count()):
        try:
            with torch.cuda.device(index):
                probe = torch.ones(1, device=f'cuda:{index}') * 2
                torch.cuda.synchronize(index)
                del probe
                free, _ = torch.cuda.mem_get_info(index)
            devices.append((free, index, torch.cuda.get_device_name(index)))
        except (RuntimeError, AssertionError):
            continue
    if not devices: return None
    _, index, name = max(devices)
    return {'device': f'cuda:{index}', 'index': index, 'name': name}


def directml_device():
    if os.name != 'nt': return None
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent / 'build/bundle'
    probe = base / 'STTSGPU.exe'
    if not probe.is_file(): return None
    result = subprocess.run([str(probe)], capture_output=True, text=True, encoding='utf-8', timeout=10,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode: return None
    devices = json.loads(result.stdout)
    if not devices: return None
    return max(devices, key=lambda value: value['memory'])


def accelerator_error(error):
    text = str(error).lower()
    return any(value in text for value in ('cuda', 'cudnn', 'cublas', 'out of memory', 'outofmemory',
        'directml', 'dml', 'dxgi', 'd3d12', 'device removed', 'device lost', 'gpu', 'not implemented for'))


def release_cuda():
    gc.collect()
    if 'torch' in sys.modules:
        torch = sys.modules['torch']
        try:
            if torch.cuda.is_available(): torch.cuda.empty_cache()
        except RuntimeError:
            pass


def enable_directml(engine, directory, device):
    import onnxruntime as ort
    from supertonic import loader
    if 'DmlExecutionProvider' not in ort.get_available_providers(): return False
    options = ort.SessionOptions()
    options.enable_mem_pattern = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    providers = [('DmlExecutionProvider', {'device_id': str(device['index'])}), 'CPUExecutionProvider']
    sessions = {}
    for attr, path in [('dp_ort', loader.DP_ONNX_REL_PATH), ('text_enc_ort', loader.TEXT_ENC_ONNX_REL_PATH),
                       ('vector_est_ort', loader.VECTOR_EST_ONNX_REL_PATH), ('vocoder_ort', loader.VOCODER_ONNX_REL_PATH)]:
        session = ort.InferenceSession(str(directory / path), sess_options=options, providers=providers)
        if 'DmlExecutionProvider' not in session.get_providers():
            raise RuntimeError('DirectML 장치를 초기화하지 못했습니다.')
        sessions[attr] = session
    # Keep the original CPU sessions until every GPU session has loaded successfully.
    for attr, session in sessions.items(): setattr(engine.model, attr, session)
    return True
