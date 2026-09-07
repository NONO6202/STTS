"""Load pinned, pre-quantized INT8 safetensors without downloading FP weights.

Rin247's format stores symmetric signed weights and one F32 scale per tensor.
Linear weights remain INT8 in memory; a single layer is expanded for each matmul.
The upstream speech codec and unquantized tensors retain floating-point precision.
No remote Python code or runtime quantization is used.
"""
import json


def load(directory, device, dtype):
    import torch
    from torch import nn
    from accelerate import init_empty_weights
    from accelerate.utils import set_module_tensor_to_device
    from safetensors import safe_open
    from qwen_tts import Qwen3TTSModel, Qwen3TTSTokenizer
    from qwen_tts.core.models import Qwen3TTSConfig, Qwen3TTSForConditionalGeneration, Qwen3TTSProcessor

    class Int8Linear(nn.Module):
        def __init__(self, weight, scale, bias=None):
            super().__init__()
            if weight.dtype != torch.int8 or scale.numel() != 1 or not torch.isfinite(scale).all() or scale.item() <= 0:
                raise ValueError('지원하지 않는 INT8 가중치 형식입니다.')
            self.in_features, self.out_features = weight.shape[1], weight.shape[0]
            self.register_buffer('weight', weight.to(device))
            self.register_buffer('weight_scale', scale.to(device))
            self.register_buffer('bias', bias.to(device=device, dtype=dtype) if bias is not None else None)

        def forward(self, x):
            weight = self.weight.to(dtype=x.dtype) * self.weight_scale.to(dtype=x.dtype)
            return torch.nn.functional.linear(x, weight, self.bias)

    raw = json.loads((directory / 'config.json').read_text(encoding='utf-8'))
    quant = raw.pop('quantization_config')
    if quant.get('quant_method') != 'int8_weight_only':
        raise ValueError('다운로드 모델이 INT8 형식이 아닙니다.')
    config = Qwen3TTSConfig.from_dict(raw)
    config._attn_implementation = 'sdpa'
    with init_empty_weights():
        model = Qwen3TTSForConditionalGeneration(config)
    expected = set(model.state_dict())
    quantized = set(quant['layers_quantized'])
    with safe_open(str(directory / 'model.safetensors'), framework='pt', device='cpu') as weights:
        keys = set(weights.keys())
        if keys != expected | {name + '_scale' for name in quantized}:
            raise ValueError('INT8 모델의 가중치 목록이 엔진과 다릅니다.')
        replaced = set()
        for name in sorted(quantized):
            module_name = name.removesuffix('.weight')
            original = model.get_submodule(module_name)
            if not isinstance(original, nn.Linear):
                raise ValueError('INT8 모델에 지원하지 않는 레이어가 있습니다.')
            bias_name = module_name + '.bias'
            model.set_submodule(module_name, Int8Linear(weights.get_tensor(name), weights.get_tensor(name + '_scale'),
                                weights.get_tensor(bias_name) if bias_name in expected else None))
            replaced.update((name, bias_name))
        for name in sorted(expected - replaced):
            value = weights.get_tensor(name)
            set_module_tensor_to_device(model, name, device, value=value, dtype=dtype if value.is_floating_point() else value.dtype)
    # Rotary buffers are nonpersistent and initialized outside the meta parameters.
    model.to(device=device)
    model.eval()
    model.load_speech_tokenizer(Qwen3TTSTokenizer.from_pretrained(str(directory / 'speech_tokenizer'),
                               device_map=device, dtype=dtype, local_files_only=True, attn_implementation='sdpa'))
    defaults = json.loads((directory / 'generation_config.json').read_text(encoding='utf-8'))
    model.load_generate_config(defaults)
    processor = Qwen3TTSProcessor.from_pretrained(str(directory), local_files_only=True, fix_mistral_regex=True)
    return Qwen3TTSModel(model, processor, defaults)
