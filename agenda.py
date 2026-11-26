"""Tarefas automáticas: resumo diário de contas a vencer, enviado no WhatsApp."""
import logging
import threading
import time
from datetime import datetime, timedelta

from . import config, db, financeiro, visitas, whatsapp

log = logging.getLogger("assistente")


def enviar_lembretes(forcar=False):
    """Manda o lembrete do dia para cada número que já conversou com o assistente."""
    hoje = config.hoje().isoformat()
    if not forcar and db.ajuste("lembrete_diario") == hoje:
        return "já enviado hoje"
    db.gravar_ajuste("lembrete_diario", hoje)
    texto, curto = financeiro.lembrete()
    agenda_hoje = visitas.resumo_hoje()
    if agenda_hoje:
        texto = "\n\n".join(t for t in (agenda_hoje, texto) if t)
        curto = curto or "visitas e pedidos de visita para hoje"
    if not texto:
        return "nada para lembrar"
    enviados = []
    for chave, numero in db.ajustes_com_prefixo("numero:").items():
        if not config.autorizado(numero):
            continue
        ultima = db.ajuste(f"ultima_msg:{chave}")
        # o WhatsApp só permite mensagem livre até 24 h depois da última mensagem da pessoa
        na_janela = bool(ultima) and config.agora() - datetime.fromisoformat(ultima) < timedelta(hours=23)
        try:
            if na_janela:
                whatsapp.enviar_texto(numero, texto)
                db.gravar_ajuste(f"lembrete_conversa:{chave}", hoje)
                enviados.append(numero)
            elif config.TEMPLATE_LEMBRETE:
                whatsapp.enviar_template(numero, config.TEMPLATE_LEMBRETE, [config.hoje().strftime("%d/%m"), curto])
                enviados.append(numero + " (modelo)")
            else:
                log.info("lembrete de %s fica para a próxima conversa (fora da janela de 24 h e sem modelo)", numero)
        except Exception as e:
            log.warning("não consegui enviar o lembrete para %s: %s", numero, e)
    return "enviado para: " + (", ".join(enviados) or "ninguém (aparece na próxima conversa)")


def _loop():
    while True:
        try:
            h = config.agora().hour
            if 0 <= config.HORA_LEMBRETE <= h < max(config.HORA_LEMBRETE + 4, 21):
                r = enviar_lembretes()
                if r != "já enviado hoje":
                    log.info("lembrete diário: %s", r)
        except Exception:
            log.exception("erro no lembrete diário")
        time.sleep(60)


def iniciar():
    if config.HORA_LEMBRETE >= 0:
        threading.Thread(target=_loop, daemon=True, name="lembretes").start()
