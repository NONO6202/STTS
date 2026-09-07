"""One request per process; input text never appears in argv or diagnostic output."""
import json
import sys
from pathlib import Path
from gtts import gTTS
from gtts.lang import tts_langs


def main():
    if "--self-check" in sys.argv:
        print(json.dumps({"ready": True, "provider": "gTTS", "version": "2.5.4"}))
        return 0
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError("request too large")
        request = json.loads(raw)
        text = request["text"].strip()
        lang = request.get("language", "ko")
        if not text or len(text) > 500 or lang not in tts_langs():
            raise ValueError("invalid request")
        output = Path(request["output"])
        # All callers pass a unique path in the app's private temporary directory.
        with output.open("xb") as handle:
            gTTS(text=text, lang=lang, lang_check=False, timeout=(5, 10)).write_to_fp(handle)
        print(json.dumps({"ok": True}))
        return 0
    except Exception:
        # Never echo text, HTTP payloads, paths, or remote error bodies.
        print(json.dumps({"ok": False, "error": "음성 생성에 실패했습니다. 인터넷 연결을 확인하고 다시 시도하세요."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
