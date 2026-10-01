# Windows 모델

모델은 처음 사용할 때 다운로드합니다. 미리 양자화된 파일을 사용하며 사용자 PC에서 원본 모델을 양자화하지 않습니다.

| 기능 | 설정 | 모델 | 다운로드 |
| --- | --- | --- | ---: |
| TTS | 기본 | gTTS | 없음·온라인 서비스 |
| TTS | 낮음 | Supertonic 3 | 148 MB |
| TTS | 중간 | Qwen3-TTS 0.6B 일반 / 클론 | 1.97 / 1.99 GB |
| TTS | 높음 | Qwen3-TTS 1.7B 일반 / 클론 | 3.02 / 3.05 GB |
| STT | 낮음 | Whisper small | 252 MB |
| STT | 기본 | Whisper large-v3-turbo | 818 MB |
| STT | 높음 | Whisper large-v3 | 1.56 GB |

용량은 구성 파일을 포함하며 1 GB = 1,000,000,000바이트입니다.

- **Qwen:** Linear 가중치 INT8. 임베딩·음성 코덱은 원본 정밀도. 가중치를 INT8로 보관하고 연산할 레이어만 BF16 또는 FP32로 펼칩니다.
- **Supertonic:** vector estimator·vocoder INT8. text encoder·duration predictor FP32.
- **Whisper:** CTranslate2 INT8 배포본. GPU는 `int8_float16`, CPU는 `int8`로 실행합니다.

Qwen·Whisper는 CUDA, Supertonic은 DirectML을 사용합니다. 가속기를 사용할 수 없으면 CPU로 실행합니다.

파일별 배포 출처·커밋·크기·해시는 [models.json](../Windows/models.json)에 고정합니다. 외부 저장소의 Python 코드를 실행하지 않습니다.
