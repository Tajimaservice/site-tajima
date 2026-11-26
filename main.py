"""Servidor do assistente: recebe as mensagens do WhatsApp (webhook) e responde."""
import hmac
import logging
import time
import traceback
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import agenda, brain, catalogo, config, db, painel, stt, telas, visitas, vitrine, whatsapp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("assistente")

db.iniciar()
visitas.iniciar()
catalogo.iniciar()
vitrine.iniciar()


@asynccontextmanager
async def _ciclo(_app):
    agenda.iniciar()          # lembrete diário de contas
    yield


app = FastAPI(title=f"Assistente {config.NOME_ASSISTENTE}", lifespan=_ciclo)
app.add_middleware(CORSMiddleware, allow_origins=config.SITE_ORIGENS or ["*"], allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type"])
_chave_numero = config.chave_numero
autorizado = config.autorizado


@app.get("/")
def saude():
    return {"status": "ok", "servico": f"assistente {config.NOME_ASSISTENTE}"}


@app.get("/webhook")
def verificar(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == config.VERIFY_TOKEN:
        return Response(content=p.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receber(request: Request, tarefas: BackgroundTasks):
    corpo = await request.body()
    if not whatsapp.assinatura_valida(corpo, request.headers.get("X-Hub-Signature-256", "")):
        log.warning("assinatura inválida")
        return Response(status_code=401)
    dados = await request.json()
    for entrada in dados.get("entry", []):
        for mudanca in entrada.get("changes", []):
            valor = mudanca.get("value", {})
            for msg in valor.get("messages", []) or []:
                tarefas.add_task(tratar_mensagem, msg)
            for st in valor.get("statuses", []) or []:
                tratar_status(st)
    return {"ok": True}


def tratar_status(st: dict):
    """Avisos da Meta sobre as mensagens enviadas (enviada, entregue, lida ou falhou)."""
    para, situacao = st.get("recipient_id", ""), st.get("status", "")
    if situacao != "failed":
        log.info("status da mensagem para %s: %s", para, situacao)
        return
    erros = "; ".join(f"{e.get('code')} {e.get('title', '')} {(e.get('error_data') or {}).get('details', '')}".strip()
                      for e in st.get("errors", []) or [])
    log.error("A Meta NÃO entregou a mensagem para %s: %s", para, erros or st)
    # Brasil: se falhou com uma forma do número (com/sem o 9), as próximas respostas usam a outra
    alt = whatsapp.numero_alternativo(para)
    if alt:
        original = db.ajuste(f"origem:{para}") or para
        if db.ajuste(f"destino:{original}") != alt:
            db.gravar_ajuste(f"destino:{original}", alt)
            db.gravar_ajuste(f"origem:{alt}", original)
            log.warning("próximas respostas para %s vão para %s (formato do número com/sem o 9)", original, alt)          # responde rápido; o processamento continua em segundo plano


def _senha_ok(k: str) -> bool:
    return bool(k) and hmac.compare_digest(k, painel.senha_painel())


@app.get("/painel", response_class=HTMLResponse)
def ver_painel(k: str = "", p: str = "mes"):
    if not _senha_ok(k):
        return HTMLResponse("<h3>Link inválido. Peça o link do painel ao assistente no WhatsApp.</h3>", status_code=403)
    return HTMLResponse(painel.pagina(k, p), headers={"Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex",
                                                      "Cache-Control": "no-store"})


@app.get("/painel/logo")
def logo_painel(k: str = ""):
    if not _senha_ok(k) or not config.LOGO.exists():
        return Response(status_code=404)
    return FileResponse(config.LOGO)


_SEM_CACHE = {"Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex", "Cache-Control": "no-store"}


@app.get("/painel/orcamento", response_class=HTMLResponse)
def tela_orcamento(k: str = "", id: int | None = None):
    if not _senha_ok(k):
        return HTMLResponse("<h3>Link inválido.</h3>", status_code=403)
    return HTMLResponse(telas.pagina_orcamento(k, id), headers=_SEM_CACHE)


@app.post("/painel/api/orcamento")
async def salvar_orcamento_painel(request: Request, k: str = ""):
    if not _senha_ok(k):
        return JSONResponse({"erro": "link inválido"}, status_code=403)
    try:
        orc = brain.orcamento_do_painel(await request.json())
    except (ValueError, KeyError, TypeError) as e:
        return JSONResponse({"erro": str(e) or "dados inválidos"}, status_code=400)
    return {"id": orc["id"], "total": orc["total"], "pdf": f"/painel/orcamento/{orc['id']}/pdf?k={k}"}


@app.get("/painel/orcamento/{orc_id}/pdf")
def pdf_orcamento(orc_id: int, k: str = ""):
    orc = db.obter_orcamento(orc_id) if _senha_ok(k) else None
    if not orc:
        return Response(status_code=404)
    arq = brain._pdf(orc)
    return FileResponse(arq, media_type="application/pdf", filename=arq.name, headers=_SEM_CACHE)


@app.post("/painel/api/orcamento/{orc_id}/whatsapp")
def orcamento_no_whatsapp(orc_id: int, k: str = ""):
    orc = db.obter_orcamento(orc_id) if _senha_ok(k) else None
    if not orc:
        return JSONResponse({"mensagem": "Orçamento não encontrado."}, status_code=404)
    numeros = visitas.numeros_na_janela()
    if not numeros:
        return JSONResponse({"mensagem": f"O WhatsApp só deixa o assistente te mandar arquivo até 24 h depois da sua última mensagem. "
                                         f"Mande \"reenviar orçamento {orc_id}\" para o assistente, ou use Baixar PDF."}, status_code=409)
    arq = brain._pdf(orc)
    for n in numeros:
        whatsapp.enviar_documento(n, arq, f"Orçamento nº {orc_id:04d} – {orc['cliente'] or 'Cliente'}")
    return {"mensagem": "Enviado no seu WhatsApp. É só encaminhar para o cliente."}


@app.get("/painel/precos", response_class=HTMLResponse)
def tela_precos(k: str = ""):
    if not _senha_ok(k):
        return HTMLResponse("<h3>Link inválido.</h3>", status_code=403)
    return HTMLResponse(telas.pagina_precos(k), headers=_SEM_CACHE)


@app.post("/painel/api/precos")
async def salvar_precos(request: Request, k: str = ""):
    if not _senha_ok(k):
        return JSONResponse({"erro": "link inválido"}, status_code=403)
    try:
        d = await request.json()
        catalogo.salvar_tabela(list(d["itens"]))
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"erro": "dados inválidos"}, status_code=400)
    itens = [{c: i[c] for c in ("codigo", "servico", "unidade", "mao_de_obra", "material", "palavras_chave", "site")} for i in catalogo.listar()]
    return {"ok": True, "itens": itens}


@app.get("/api/catalogo/publico")
def catalogo_publico():
    """Serviços marcados "No site" na tabela de preços (calculadora de estimativa do site)."""
    return JSONResponse({"itens": catalogo.publicos()}, headers={"Cache-Control": "no-store"})


@app.get("/api/site/conteudo")
def site_conteudo():
    """Serviços e fotos publicados, para o site da empresa."""
    return JSONResponse(vitrine.conteudo_publico(), headers={"Cache-Control": "no-store"})


@app.get("/api/site/foto/{arquivo}")
def site_foto(arquivo: str):
    p = vitrine.caminho(arquivo)
    if not p:
        return Response(status_code=404)
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/painel/site", response_class=HTMLResponse)
def tela_site(k: str = ""):
    if not _senha_ok(k):
        return HTMLResponse("<h3>Link inválido.</h3>", status_code=403)
    return HTMLResponse(telas.pagina_site(k), headers=_SEM_CACHE)


@app.post("/painel/api/site/servicos")
async def salvar_servicos_site(request: Request, k: str = ""):
    if not _senha_ok(k):
        return JSONResponse({"erro": "link inválido"}, status_code=403)
    try:
        lista = vitrine.salvar_servicos(list((await request.json())["servicos"]))
    except (ValueError, KeyError, TypeError) as e:
        return JSONResponse({"erro": str(e) or "dados inválidos"}, status_code=400)
    return {"ok": True, "servicos": lista}


@app.post("/painel/api/site/foto")
async def enviar_foto_site(request: Request, k: str = ""):
    if not _senha_ok(k):
        return JSONResponse({"erro": "link inválido"}, status_code=403)
    try:
        d = await request.json()
        fid = vitrine.foto_do_painel(d.get("tipo"), d.get("legenda") or "", d.get("foto") or "", d.get("foto2") or "")
    except Exception as e:
        return JSONResponse({"erro": f"não consegui salvar a foto ({e})"}, status_code=400)
    return {"ok": True, "id": fid, "fotos": vitrine.fotos_do_painel()}


@app.post("/painel/api/site/foto/{fid}")
async def alterar_foto_site(fid: int, request: Request, k: str = ""):
    if not _senha_ok(k):
        return JSONResponse({"erro": "link inválido"}, status_code=403)
    d = await request.json()
    if d.get("apagar"):
        vitrine.apagar_foto(fid)
    else:
        vitrine.alterar_foto(fid, d.get("legenda"), d.get("publicado"))
    return {"ok": True, "fotos": vitrine.fotos_do_painel()}


@app.get("/tarefas/lembrete")
def lembrete_agora(k: str = ""):
    """Força o envio do lembrete de contas (para testar ou para um agendador externo)."""
    if not _senha_ok(k):
        return Response(status_code=403)
    return {"resultado": agenda.enviar_lembretes(forcar=True)}


# ------------------------------------------------------------------ agenda de visitas (usada pelo site)
_PEDIDOS_IP = defaultdict(deque)


def _limite_ok(ip: str, maximo=5, janela=600) -> bool:
    """No máximo 5 pedidos a cada 10 minutos por endereço (evita robôs lotando a agenda)."""
    agora_s, fila = time.time(), _PEDIDOS_IP[ip]
    while fila and agora_s - fila[0] > janela:
        fila.popleft()
    if len(fila) >= maximo:
        return False
    fila.append(agora_s)
    return True


def _txt(d: dict, campo: str, limite: int) -> str:
    return " ".join(str(d.get(campo) or "").split())[:limite]


@app.get("/api/agenda/livres")
def agenda_livres():
    c = visitas.cfg()
    return JSONResponse({"dias": visitas.livres(), "duracao": c["duracao"]}, headers={"Cache-Control": "no-store"})


@app.post("/api/agenda/reservar")
async def agenda_reservar(request: Request, tarefas: BackgroundTasks):
    try:
        d = await request.json()
        assert isinstance(d, dict)
    except Exception:
        return JSONResponse({"erro": "pedido inválido"}, status_code=400)
    if d.get("site"):                                   # campo escondido: só robô preenche
        return {"ok": True, "id": 0}
    nome, fone = _txt(d, "nome", 80), _txt(d, "telefone", 20)
    data, hora = _txt(d, "data", 10), visitas.hora_ok(_txt(d, "hora", 5)) or ""
    if len(nome) < 2 or len("".join(ch for ch in fone if ch.isdigit())) < 10:
        return JSONResponse({"erro": "Preencha nome e WhatsApp com DDD."}, status_code=400)
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
    if not _limite_ok(ip):
        return JSONResponse({"erro": "Muitos pedidos seguidos. Tente de novo em alguns minutos."}, status_code=429)
    try:
        vid = visitas.criar(nome, fone, data, hora, _txt(d, "servico", 80), _txt(d, "endereco", 160),
                            _txt(d, "local", 30), _txt(d, "detalhes", 500))
    except visitas.Ocupado:
        return JSONResponse({"erro": "ocupado", "dias": visitas.livres()}, status_code=409)
    log.info("novo pedido de visita pelo site: nº %s (%s %s)", vid, data, hora)
    tarefas.add_task(visitas.avisar_dono, vid)
    return {"ok": True, "id": vid}


def responder(para: str, eco: str, respostas: list):
    """Envia a resposta usando o MENOR número de mensagens (o WhatsApp cobra por mensagem enviada
    depois das 1.000 grátis do mês): junta os textos numa mensagem só e, se houver um arquivo,
    coloca o texto como legenda dele."""
    textos = ([eco] if eco else []) + [r["texto"] for r in respostas if "texto" in r]
    arquivos = [r for r in respostas if "arquivo" in r]
    texto = "\n\n".join(t for t in textos if t)
    if len(arquivos) == 1 and len(texto) <= 1000:
        a = arquivos[0]
        whatsapp.enviar_documento(para, a["arquivo"], texto or a.get("legenda", ""), a.get("mime", "application/pdf"))
        return
    if texto:
        whatsapp.enviar_texto(para, texto)
    for a in arquivos:
        whatsapp.enviar_documento(para, a["arquivo"], a.get("legenda", ""), a.get("mime", "application/pdf"))


def tratar_mensagem(msg: dict):
    remetente = msg.get("from", "")
    msg_id = msg.get("id", "")
    if db.ja_processada(msg_id):
        return
    if not autorizado(remetente):
        log.info("mensagem ignorada de número não autorizado: %s", remetente)
        return
    whatsapp.marcar_lida(msg_id)
    chave = _chave_numero(remetente)
    db.gravar_ajuste(f"numero:{chave}", remetente)          # para o lembrete diário
    db.gravar_ajuste(f"ultima_msg:{chave}", db.agora())     # janela de 24 h do WhatsApp
    try:
        tipo = msg.get("type")
        eco = ""
        if tipo == "audio":
            audio, mime = whatsapp.baixar_midia(msg["audio"]["id"])
            texto = stt.transcrever(audio, mime)
            if not texto:
                whatsapp.enviar_texto(remetente, "Não consegui entender o áudio. Pode mandar de novo?")
                return
            eco = f"🎤 _{texto}_"
        elif tipo == "text":
            texto = msg["text"]["body"]
        elif tipo in ("image", "document") and str(msg.get(tipo, {}).get("mime_type", "image/")).startswith("image/"):
            # foto para o site: "antes ...", "depois ...", "galeria ..." na legenda
            conteudo, _mime = whatsapp.baixar_midia(msg[tipo]["id"])
            legenda = msg[tipo].get("caption", "")
            respostas = vitrine.receber_foto(chave, conteudo, legenda)
            db.salvar_historico(chave, "user", f"[enviou uma foto] {legenda}".strip())
            db.salvar_historico(chave, "assistant", respostas[0]["texto"][:600])
            responder(remetente, "", respostas)
            return
        else:
            whatsapp.enviar_texto(remetente, "Por enquanto eu entendo áudios, mensagens de texto e fotos (para o site). 🙂")
            return
        responder(remetente, eco, brain.processar(chave, texto))
    except Exception:
        log.error("erro ao processar mensagem:\n%s", traceback.format_exc())
        try:
            whatsapp.enviar_texto(remetente, "⚠️ Tive um problema para processar essa mensagem. Tente de novo em instantes.")
        except Exception:
            pass
