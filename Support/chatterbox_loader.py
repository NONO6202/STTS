"""Preset-only loader for mlx-audio 0.5.1 Chatterbox; never fetch a voice-cloning encoder.

Uses the component loading/conditioning interface from mlx-audio (MIT).
The published preset conditionals supply the voice; no reference recording is needed.
"""
import json
import hashlib
import os
import tempfile
import mlx.core as mx
import mlx.nn as nn
from mlx.utils import tree_flatten
from mlx_audio.utils import apply_quantization
from mlx_audio.tts.models.chatterbox.chatterbox import Model, Conditionals, T3Cond
from mlx_audio.tts.models.chatterbox.config import ModelConfig


def load(directory):
    config = json.loads((directory / 'config.json').read_text())
    model = Model(ModelConfig.from_dict(config))
    # Only used when encoding a reference voice. Preset generation does not call it.
    model._s3_tokenizer = None
    cached = directory / 'model.stts-8bit.safetensors'
    checksum = directory / 'model.stts-8bit.sha256'
    use_cache = False
    if cached.is_file() and checksum.is_file():
        with cached.open('rb') as f:
            use_cache = hashlib.file_digest(f, 'sha256').hexdigest() == checksum.read_text().strip()
    if use_cache:
        config['quantization'] = {'bits': 8, 'group_size': 64, 'mode': 'affine'}
        weights = mx.load(str(cached))
    else:
        weights = model.sanitize(mx.load(str(directory / 'model.safetensors')))
    apply_quantization(model, config, weights, None)
    model.load_weights(list(weights.items()), strict=True)
    if config.get('quantization', {}).get('bits') != 8:
        nn.quantize(model, group_size=64, bits=8, class_predicate=lambda path, module:
            hasattr(module, 'to_quantized') and module.weight.shape[-1] % 64 == 0)
        # Convert once during the first load; later speech jobs load the smaller weights.
        mx.eval(model.parameters())
        fd, temporary = tempfile.mkstemp(prefix='.quantized-', suffix='.safetensors', dir=directory)
        os.close(fd)
        try:
            mx.save_safetensors(temporary, dict(tree_flatten(model.parameters())))
            with open(temporary, 'rb') as f:
                digest = hashlib.file_digest(f, 'sha256').hexdigest()
            os.replace(temporary, cached)
            checksum.write_text(digest + '\n')
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    model.eval()
    model._init_text_tokenizers(directory)
    conds = mx.load(str(directory / 'conds.safetensors'))
    gen = {key.removeprefix('gen.'): value for key, value in conds.items() if key.startswith('gen.')}
    if 'prompt_feat_len' not in gen:
        gen['prompt_feat_len'] = mx.array([gen['prompt_feat'].shape[1]])
    model._conds = Conditionals(T3Cond(speaker_emb=conds['t3.speaker_emb'],
        cond_prompt_speech_tokens=conds['t3.cond_prompt_speech_tokens'],
        emotion_adv=conds['t3.emotion_adv']), gen)
    mx.eval(model.parameters())
    return model
