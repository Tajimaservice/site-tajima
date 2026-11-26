"""Comunicação com a WhatsApp Cloud API (Meta): baixar áudio, enviar texto e enviar documento."""
import hashlib
import hmac
import logging
from pathlib import Path

import httpx

from . import config, db

log = logging.getLogger("assistente")


def numero_alternativo(numero: str):
    """Números do Brasil: devolve a outra forma do celular (com ou sem o 9 depois do DDD)."""
    d = "".join(ch for ch in numero if ch.isdigit())
    if d.startswith("55") and len(d) == 12 and d[4] in "6789":
        return d[:4] + "9" + d[4:]
    if d.startswith("55") and len(d) == 13 and d[4] == "9":
        return d[:4] + d[5:]
    return None


def destino(para: str) -> str:
    """Número para onde enviar: usa a forma que a Meta aceitou entregar (aprendida pelos avisos de falha)."""
    return db.ajuste(f"destino:{para}") or para


def _ok(r, para):
    if r.is_error:
        raise RuntimeError(f"Meta recusou o envio para {para}: {r.status_code} {r.text[:600]}")
    try:
        log.info("mensagem enviada para %s (id %s)", para, r.json()["messages"][0]["id"])
    except Exception:
        pass


def _url(caminho):
    return f"https://graph.facebook.com/{config.GRAPH_VERSION}/{caminho}"


def _headers():
    return {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}


def assinatura_valida(corpo: bytes, assinatura: str) -> bool:
    """Confere o cabeçalho X-Hub-Signature-256 (só se APP_SECRET estiver configurado)."""
    if not config.APP_SECRET:
        return True
    if not assinatura or not assinatura.startswith("sha256="):
        return False
    esperado = hmac.new(config.APP_SECRET.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, assinatura.split("=", 1)[1])


def baixar_midia(media_id: str) -> tuple[bytes, str]:
    with httpx.Client(timeout=60) as c:
        info = c.get(_url(media_id), headers=_headers())
        info.raise_for_status()
        dados = info.json()
        arq = c.get(dados["url"], headers=_headers())
        arq.raise_for_status()
        return arq.content, dados.get("mime_type", "audio/ogg")


def enviar_texto(para: str, texto: str):
    # o WhatsApp aceita até 4096 caracteres por mensagem
    para = destino(para)
    with httpx.Client(timeout=30) as c:
        for i in range(0, max(len(texto), 1), 4000):
            r = c.post(_url(f"{config.PHONE_NUMBER_ID}/messages"), headers=_headers(), json={
                "messaging_product": "whatsapp", "to": para, "type": "text",
                "text": {"body": texto[i:i + 4000], "preview_url": False}})
            _ok(r, para)


def enviar_documento(para: str, arquivo: Path, legenda: str = "", mime: str = "application/pdf"):
    para = destino(para)
    with httpx.Client(timeout=60) as c:
        with open(arquivo, "rb") as f:
            up = c.post(_url(f"{config.PHONE_NUMBER_ID}/media"), headers=_headers(),
                        data={"messaging_product": "whatsapp", "type": mime},
                        files={"file": (arquivo.name, f, mime)})
        _ok(up, para)
        media_id = up.json()["id"]
        r = c.post(_url(f"{config.PHONE_NUMBER_ID}/messages"), headers=_headers(), json={
            "messaging_product": "whatsapp", "to": para, "type": "document",
            "document": {"id": media_id, "filename": arquivo.name, "caption": legenda[:1000]}})
        _ok(r, para)


def marcar_lida(msg_id: str):
    try:
        with httpx.Client(timeout=15) as c:
            r = c.post(_url(f"{config.PHONE_NUMBER_ID}/messages"), headers=_headers(),
                       json={"messaging_product": "whatsapp", "status": "read", "message_id": msg_id})
            if r.is_error:
                log.error("Meta recusou marcar como lida: %s %s", r.status_code, r.text[:400])
    except Exception:
        pass


def enviar_template(para: str, nome: str, parametros: list[str]):
    """Envia um modelo de mensagem aprovado na Meta (necessário para falar fora da janela de 24 h)."""
    para = destino(para)
    with httpx.Client(timeout=30) as c:
        r = c.post(_url(f"{config.PHONE_NUMBER_ID}/messages"), headers=_headers(), json={
            "messaging_product": "whatsapp", "to": para, "type": "template",
            "template": {"name": nome, "language": {"code": config.TEMPLATE_IDIOMA},
                         "components": [{"type": "body", "parameters": [
                             {"type": "text", "text": " ".join(str(p).split())[:900]} for p in parametros]}]}})
        _ok(r, para)
