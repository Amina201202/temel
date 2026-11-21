"""Izahi sesle oxuyur: Gemini TTS (az-AZ). Netice WAV kimi qaytarilir."""
import io
import os
import re
import wave

from google.genai import types

from .extract import get_client

TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
VOICE = os.getenv("GEMINI_TTS_VOICE", "Kore")
MAX_CHARS = 1500  # cox uzun metn hem gec, hem baha olur
ABBREV = {"ƏKOB": "ən kiçik ortaq bölünən", "ƏBOB": "ən böyük ortaq bölən",
          "əkob": "ən kiçik ortaq bölünən", "əbob": "ən böyük ortaq bölən"}


def speakable(text):
    """Riyazi isareleri sozle yaziriq ki, model duz oxusun: x² -> x kvadrat."""
    # qisaltmalari model duz oxuya bilmir, tam formasini yaziriq
    # ƏKOB-u -> bolunenI: tam forma "ə" ile bitir, sekilcini ahenge uygun ceviririk
    harmony = str.maketrans("aıuo", "əiiö")
    for short, full in ABBREV.items():
        text = re.sub(rf"\b{short}(?:-(\w+))?(?=\W|$)",
                      lambda m: full + (m.group(1).translate(harmony) if m.group(1) else ""), text)
    t = text.replace("²", " kvadrat").replace("³", " kub")
    t = t.replace("√", " kök altında ")
    t = re.sub(r"x₁", "x bir", t)
    t = re.sub(r"x₂", "x iki", t)
    # iki eded arasinda minus - cixma, tek minus - menfi
    # "x-in" kimi sekilciye toxunmuruq: yalniz riyazi minus (−) ve ya bosluqlu "-"
    t = re.sub(r"(?<=[\w)])\s*−\s*(?=[\w(])", " çıx ", t)
    t = re.sub(r"(?<=[\w)])\s+-\s+(?=[\w(])", " çıx ", t)
    t = re.sub(r"(?<![\w)])\s*[−-](?=\d)", " mənfi ", t)
    t = re.sub(r"\s*\+\s*", " üstəgəl ", t)
    t = re.sub(r"\s*[·×*]\s*", " vur ", t)
    t = re.sub(r"(?<=\d)\s*/\s*(?=\d)", " bölü ", t)
    t = re.sub(r"\s*=\s*", " bərabərdir ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:MAX_CHARS]


def explanation_text(exp):
    parts = [exp.get("headline"), exp.get("why"), "Qayda.", exp.get("rule"),
             "Nümunə.", exp.get("example"), exp.get("tip")]
    return speakable(" ".join(p for p in parts if p))


def pcm_to_wav(pcm, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16 bit
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def synthesize(text):
    resp = get_client().models.generate_content(
        model=TTS_MODEL,
        contents=f"Mehriban və sakit müəllim səsi ilə, Azərbaycan dilində oxu: {text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE))),
        ),
    )
    part = resp.candidates[0].content.parts[0].inline_data
    # mime: audio/L16;codec=pcm;rate=24000
    m = re.search(r"rate=(\d+)", part.mime_type or "")
    return pcm_to_wav(part.data, int(m.group(1)) if m else 24000)
