"""Transcrição de áudio (fala → texto) usando um serviço compatível com a API da OpenAI (Groq, OpenAI...)."""
import httpx

from . import config


def transcrever(audio: bytes, mime: str = "audio/ogg") -> str:
    ext = "ogg" if "ogg" in mime else ("mp4" if "mp4" in mime else ("mpeg" if "mpeg" in mime else "ogg"))
    with httpx.Client(timeout=120) as c:
        r = c.post(f"{config.STT_BASE_URL.rstrip('/')}/audio/transcriptions",
                   headers={"Authorization": f"Bearer {config.STT_API_KEY}"},
                   data={"model": config.STT_MODEL, "language": "pt", "response_format": "json",
                         "prompt": "Orçamento de obra e controle financeiro: pintura, piso, porcelanato, tomada, "
                                   "metro quadrado, reais, Pix, material, mão de obra."},
                   files={"file": (f"audio.{ext}", audio, mime.split(";")[0])})
        r.raise_for_status()
        return r.json().get("text", "").strip()
