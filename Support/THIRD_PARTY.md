# Third-party components

STTS source is licensed under the repository's MIT LICENSE. Third-party components and model weights retain their own licenses. macOS packages include notices in `Contents/Resources/Licenses`; Windows packages include a `Licenses` folder and `VB-CABLE-NOTICE.txt`.

| Component | Version / revision | License / source |
|---|---|---|
| whisper.cpp | 1.9.0 | MIT, https://github.com/ggml-org/whisper.cpp |
| ggml | 0.15.1 | MIT, https://github.com/ggml-org/ggml |
| LLVM OpenMP | Homebrew 22.1.8 | Apache-2.0 with LLVM exceptions; included LICENSE.TXT |
| Whisper base/small/large-v3-turbo MLX 8bit | Revisions in Support/mlx_models.json | MIT upstream Whisper; MLX conversion via mlx-community |
| Qwen3-TTS Base / CustomVoice 0.6B / 1.7B | Original BF16 weights and speech codec, revisions in Support/mlx_models.json; MLX runtime | Apache-2.0; Qwen3-TTS Apache license included |
| Supertonic 3 | Original ONNX weights, revision 3cadd1ee6394adea1bd021217a0e650ede09a323; supertonic 1.3.1 | Runtime MIT; model Open RAIL-M, included Supertonic3-Open-RAIL-M.txt; https://huggingface.co/Supertone/supertonic-3 |
| Qwen3-ASR 0.6B / 1.7B MLX 8bit | Revisions in Support/mlx_models.json | Apache-2.0, https://github.com/QwenLM/Qwen3-ASR; license included |
| Chatterbox Multilingual V3 | Revision 03565773edd72e949572557597af8063bb49a18a | MIT upstream and MLX model card; included MIT license. STTS quantizes supported layers to MLX 8-bit on first use and caches the result locally. |
| Chatterbox preset conditionals | From mlx-community/chatterbox-8bit revision 9617d61b596a03d1bed766a28c341680e993a1b9 | Conversion card Apache-2.0, upstream Chatterbox MIT; source and hash pinned per file. No reference-voice encoder is loaded. |
| VoxCPM2 MLX 8bit | Revision d52725898a0675703f7f9ddc5a4d1a3cdbb99032 | Apache-2.0 upstream and conversion card; included license |
| Nemotron 3.5 ASR MLX 8bit | Revision 7279359e4481b5e9e185a318bd618e429c6d86cd | Pinned conversion identifies NVIDIA Open Model License; included agreement and required NOTICE. Current original model card identifies OpenMDW-1.1 separately. |
| MLX / MLX Metal | 0.32.2 | MIT, https://github.com/ml-explore/mlx |
| MLX Audio | 0.5.1 | MIT, https://github.com/Blaizzy/mlx-audio |
| Transformers / Tokenizers / Hugging Face Hub | Python runtime metadata | Apache-2.0; included package licenses |
| Silero VAD v6.2.0 | GGML repo 9ffd54a1e1ee413ddf265af9913beaf518d1639b | MIT, https://github.com/snakers4/silero-vad |
| FluidAudio | 0.15.6 (Package.resolved) | Apache-2.0, https://github.com/FluidInference/FluidAudio |
| LS-EEND DIHARD3 CoreML 500ms | 28ce1b1f8ef186729df63b3886fbaae7bc10c4a1 | MIT model card, https://huggingface.co/FluidInference/ls-eend-coreml |
| fastcluster wrapper | transitive FluidAudio source | BSD-2-Clause; upstream copyright included |
| NeMo text processing Rust artifact | v0.3.0, transitive FluidAudio target | Apache-2.0; https://github.com/FluidInference/text-processing-rs |
| gTTS | 2.5.4 | MIT, https://github.com/pndurette/gTTS |
| CPython and Python runtime packages | bundled by PyInstaller | Included package license files; Python PSF license and individual requests/urllib3/certifi/click dependencies apply |
| PyInstaller bootloader | 6.22.2 | GPL with bootloader distribution exception; see included COPYING.txt |
| Qt / PySide6 (Windows UI) | 6.10.2 | LGPL-3.0; shipped as replaceable shared libraries, with upstream license notices included. https://doc.qt.io/qtforpython-6/licenses.html |
| PyTorch CUDA runtime (Windows) | PyTorch / torchaudio 2.10.0, CUDA 12.8 wheels | PyTorch BSD-style license; bundled NVIDIA libraries retain their own terms and notices. https://pytorch.org/get-started/previous-versions/ |
| ONNX Runtime DirectML (Windows) | 1.24.3 | ONNX Runtime MIT; Microsoft DirectML binaries retain their included license. https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html |
| VB-CABLE (Windows only) | Driver Pack 45; SHA-256 pinned in Windows/build.ps1 | VB-Audio donationware, not MIT. The build downloads the original archive; the installer includes vendor files and Windows/VB-CABLE-NOTICE.txt. https://vb-audio.com/Services/licensing.htm |

MLX model files and LS-EEND model files are downloaded separately and checked against pinned hashes. The selected Qwen3-TTS Base and CustomVoice models use original BF16 weights and an unquantized speech codec; Supertonic 3 uses original ONNX weights. Legacy MLX quantized models use 8-bit linear/embedding layers with some floating point tensors. The LS-EEND variant is FP32, not quantized. Its model card lists English. Underlying dataset terms remain separate from the model license. No dataset or voice-cloning samples are bundled.


The macOS virtual microphone uses Apple's system CoreAudio APIs and STTS-authored routing code. No BlackHole code, binary, installer or third-party audio driver is bundled on macOS. Windows bundles VB-CABLE under its separate distribution terms and preserves the vendor identity and donation information.

gTTS's library license does not grant a separate commercial service agreement, offline operation, guaranteed availability, or an SLA for the Google endpoint it calls.

Apple system frameworks are dynamically linked from macOS. No Discord code, token, bot, self-bot, or client modification is included.
