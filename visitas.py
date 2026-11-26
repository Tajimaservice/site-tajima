"""Agenda de visitas técnicas: horários livres para o site, pedidos de clientes, confirmação pelo WhatsApp e bloqueios.

O site pergunta ao assistente quais horários estão livres e grava o pedido aqui. O dono recebe o aviso no WhatsApp
e responde "confirmar 12" ou "recusar 12" (ou fala por áudio: "confirma a visita da Ana", "bloqueia sexta de manhã").
"""
import json
import logging
from datetime import date, datetime, timedelta
from urllib.parse import quote

from . import config, db, whatsapp

log = logging.getLogger("assistente")

SCHEMA = """
CREATE TABLE IF NOT EXISTS visitas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    origem TEXT DEFAULT 'site',                    -- site | whatsapp
    nome TEXT NOT NULL,
    telefone TEXT,
    endereco TEXT,
    local TEXT,
    servico TEXT,
    detalhes TEXT,
    data TEXT NOT NULL,
    hora TEXT NOT NULL,
    situacao TEXT NOT NULL DEFAULT 'pendente',     -- pendente | confirmada | recusada | cancelada
    motivo TEXT,
    avisado INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bloqueios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,
    hora TEXT,                                     -- vazio = dia todo
    motivo TEXT
);
"""

PADRAO = {"semana": ["08:00", "10:00", "13:00", "15:00", "17:00"], "sabado": ["08:00", "10:00"], "domingo": [],
          "dias": 14, "duracao": 60}
DIA_CURTO = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
DIA_LONGO = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
OCUPA = ("pendente", "confirmada")


def iniciar():
    with db.conectar() as con:
        con.executescript(SCHEMA)


# ------------------------------------------------------------------ configuração dos horários
def cfg() -> dict:
    c = dict(PADRAO)
    try:
        c.update(json.loads(db.ajuste("agenda_cfg") or "{}"))
    except ValueError:
        pass
    return c


def salvar_cfg(**novos):
    c = cfg()
    c.update({k: v for k, v in novos.items() if v is not None})
    db.gravar_ajuste("agenda_cfg", json.dumps(c, ensure_ascii=False))
    return c


def hora_ok(h: str) -> str | None:
    """Aceita '8', '8h', '08:00', '8:30' e devolve 'HH:MM'."""
    h = (h or "").strip().lower().replace("h", ":").rstrip(":")
    partes = h.split(":")
    try:
        hh, mm = int(partes[0]), int(partes[1] or 0) if len(partes) > 1 else 0
    except ValueError:
        return None
    return f"{hh:02d}:{mm:02d}" if 0 <= hh < 24 and 0 <= mm < 60 else None


def horas_do_dia(d: date, c=None) -> list[str]:
    c = c or cfg()
    return list(c["sabado"] if d.weekday() == 5 else c["domingo"] if d.weekday() == 6 else c["semana"])


# ------------------------------------------------------------------ consultas
def _linhas(sql, *p):
    with db.conectar() as con:
        return [dict(r) for r in con.execute(sql, p).fetchall()]


def obter(vid: int):
    r = _linhas("SELECT * FROM visitas WHERE id = ?", vid)
    return r[0] if r else None


def listar(inicio: date, fim: date, situacoes=OCUPA):
    marcas = ",".join("?" * len(situacoes))
    return _linhas(f"SELECT * FROM visitas WHERE data BETWEEN ? AND ? AND situacao IN ({marcas}) ORDER BY data, hora",
                   inicio.isoformat(), fim.isoformat(), *situacoes)


def bloqueios(inicio: date, fim: date):
    return _linhas("SELECT * FROM bloqueios WHERE data BETWEEN ? AND ? ORDER BY data, hora",
                   inicio.isoformat(), fim.isoformat())


def livres(dias: int | None = None) -> list[dict]:
    """Dias e horários que o site pode oferecer (a partir de amanhã)."""
    c = cfg()
    dias = int(dias or c["dias"])
    inicio = config.hoje() + timedelta(days=1)
    fim = inicio + timedelta(days=dias + 14)            # olha mais à frente para pular domingos e bloqueios
    ocup = {(v["data"], v["hora"]) for v in listar(inicio, fim)}
    bls = bloqueios(inicio, fim)
    dia_todo = {b["data"] for b in bls if not b["hora"]}
    hora_bloq = {(b["data"], b["hora"]) for b in bls if b["hora"]}
    saida, d = [], inicio
    while len(saida) < dias and d <= fim:
        iso = d.isoformat()
        if iso not in dia_todo:
            horas = [h for h in horas_do_dia(d, c) if (iso, h) not in ocup and (iso, h) not in hora_bloq]
            if horas:
                saida.append({"data": iso, "horas": horas})
        d += timedelta(days=1)
    return saida


def esta_livre(data: str, hora: str, ignorar_id: int | None = None) -> bool:
    try:
        d = date.fromisoformat(data)
    except ValueError:
        return False
    if d <= config.hoje() or hora not in horas_do_dia(d):
        return False
    if any(not b["hora"] or b["hora"] == hora for b in bloqueios(d, d)):
        return False
    return not any(v["hora"] == hora and v["id"] != ignorar_id for v in listar(d, d))


# ------------------------------------------------------------------ alterações
class Ocupado(Exception):
    pass


def criar(nome, telefone, data, hora, servico="", endereco="", local="", detalhes="", origem="site",
          situacao="pendente", livre_obrigatorio=True) -> int:
    with db.conectar() as con:
        con.execute("BEGIN IMMEDIATE")           # evita dois clientes pegarem o mesmo horário ao mesmo tempo
        if livre_obrigatorio and not esta_livre(data, hora):
            raise Ocupado()
        cur = con.execute(
            "INSERT INTO visitas (criado_em, origem, nome, telefone, endereco, local, servico, detalhes, data, hora, situacao, avisado) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (db.agora(), origem, nome, telefone, endereco, local, servico, detalhes, data, hora, situacao,
             1 if origem == "whatsapp" else 0))
        return cur.lastrowid


def mudar(vid: int, situacao: str, motivo: str | None = None):
    with db.conectar() as con:
        con.execute("UPDATE visitas SET situacao = ?, motivo = COALESCE(?, motivo) WHERE id = ?", (situacao, motivo, vid))


def remarcar(vid: int, data: str, hora: str):
    if not esta_livre(data, hora, ignorar_id=vid):
        raise Ocupado()
    with db.conectar() as con:
        con.execute("UPDATE visitas SET data = ?, hora = ? WHERE id = ?", (data, hora, vid))


def _datas(inicio: str, fim: str | None):
    d0 = date.fromisoformat(inicio)
    d1 = date.fromisoformat(fim) if fim else d0
    while d0 <= d1:
        yield d0
        d0 += timedelta(days=1)


def bloquear(inicio: str, fim: str | None = None, horas=None, motivo="") -> int:
    horas = [h for h in (hora_ok(x) for x in horas or []) if h] or [None]
    n = 0
    with db.conectar() as con:
        for d in _datas(inicio, fim):
            for h in horas:
                con.execute("INSERT INTO bloqueios (data, hora, motivo) VALUES (?,?,?)", (d.isoformat(), h, motivo or ""))
                n += 1
    return n


def liberar(inicio: str, fim: str | None = None, horas=None) -> int:
    horas = [h for h in (hora_ok(x) for x in horas or []) if h]
    n = 0
    with db.conectar() as con:
        for d in _datas(inicio, fim):
            if horas:
                for h in horas:
                    n += con.execute("DELETE FROM bloqueios WHERE data = ? AND (hora = ? OR hora IS NULL)", (d.isoformat(), h)).rowcount
            else:
                n += con.execute("DELETE FROM bloqueios WHERE data = ?", (d.isoformat(),)).rowcount
    return n


# ------------------------------------------------------------------ textos e links
def quando(v) -> str:
    d = date.fromisoformat(v["data"])
    return f"{DIA_LONGO[d.weekday()]}, {d:%d/%m} às {v['hora']}"


def tel_wa(telefone: str) -> str:
    d = "".join(ch for ch in telefone or "" if ch.isdigit())
    return "55" + d if len(d) in (10, 11) else d


def link_cliente(v, texto: str) -> str:
    return f"https://wa.me/{tel_wa(v['telefone'])}?text={quote(texto)}"


def link_gcal(v) -> str:
    ini = datetime.fromisoformat(f"{v['data']}T{v['hora']}")
    fim = ini + timedelta(minutes=int(cfg()["duracao"]))
    det = f"Cliente: {v['nome']}\nWhatsApp: {v['telefone'] or '-'}\nServiço: {v['servico'] or '-'}"
    if v.get("detalhes"):
        det += f"\nDetalhes: {v['detalhes']}"
    url = ("https://calendar.google.com/calendar/render?action=TEMPLATE"
           f"&text={quote('Visita técnica – ' + v['nome'])}&dates={ini:%Y%m%dT%H%M%S}/{fim:%Y%m%dT%H%M%S}"
           f"&ctz={quote(str(config.FUSO))}&details={quote(det)}")
    return url + (f"&location={quote(v['endereco'])}" if v.get("endereco") else "")


def _primeiro_nome(v):
    return (v["nome"] or "").split(" ")[0] or "tudo bem"


def texto_novo(v) -> str:
    linhas = [f"📅 *Novo pedido de visita* (nº {v['id']})",
              f"👤 {v['nome']} – {v['telefone'] or 'sem telefone'}",
              f"🛠️ {v['servico'] or 'serviço não informado'}" + (f" · {v['local']}" if v.get("local") else ""),
              f"🗓️ {quando(v)}"]
    if v.get("endereco"):
        linhas.append(f"📍 {v['endereco']}")
    if v.get("detalhes"):
        linhas.append(f"📝 {v['detalhes']}")
    linhas += ["", f"O horário fica reservado até você responder: *confirmar {v['id']}* ou *recusar {v['id']}*."]
    return "\n".join(linhas)


def texto_confirmada(v) -> str:
    msg = (f"Olá, {_primeiro_nome(v)}! Aqui é o Marcelo, da {config.NOME_ASSISTENTE}. "
           f"Sua visita técnica está confirmada para {quando(v)}"
           + (f", no endereço {v['endereco']}" if v.get("endereco") else "") + ". Até lá!")
    t = f"✅ Visita nº {v['id']} confirmada: {v['nome']}, {quando(v)}."
    if v.get("telefone"):
        t += f"\n\n📲 Avise o cliente (toque e envie):\n{link_cliente(v, msg)}"
    return t + f"\n\n🗓️ Colocar na sua Google Agenda:\n{link_gcal(v)}"


def texto_recusada(v, motivo="", nova=None) -> str:
    sugestao = ""
    if nova:
        sugestao = " Posso te atender em " + ", ".join(f"{_fmt_dia(x['data'])} às {x['horas'][0]}" for x in nova[:3]) + "?"
    msg = (f"Olá, {_primeiro_nome(v)}! Aqui é o Marcelo, da {config.NOME_ASSISTENTE}. "
           f"Infelizmente não vou conseguir fazer a visita em {quando(v)}.{sugestao}")
    t = f"❌ Pedido nº {v['id']} recusado ({v['nome']}, {quando(v)}). O horário voltou a ficar livre no site."
    if v.get("telefone"):
        t += f"\n\n📲 Avise o cliente (toque, ajuste se quiser e envie):\n{link_cliente(v, msg)}"
    return t


def _fmt_dia(iso):
    d = date.fromisoformat(iso)
    return f"{DIA_CURTO[d.weekday()]} {d:%d/%m}"


def texto_agenda(inicio: date, fim: date) -> str:
    vs = listar(inicio, fim)
    bls = bloqueios(inicio, fim)
    if not vs and not bls:
        return f"🗓️ Nenhuma visita entre {inicio:%d/%m} e {fim:%d/%m}. Todos os horários padrão estão livres no site."
    linhas = [f"🗓️ *Agenda de {inicio:%d/%m} a {fim:%d/%m}*"]
    d = inicio
    while d <= fim:
        iso = d.isoformat()
        do_dia = [v for v in vs if v["data"] == iso]
        bl = [b for b in bls if b["data"] == iso]
        if do_dia or bl:
            linhas.append(f"\n*{DIA_LONGO[d.weekday()].capitalize()} {d:%d/%m}*")
            for v in do_dia:
                marca = "✅" if v["situacao"] == "confirmada" else "⏳ aguardando você"
                linhas.append(f"{v['hora']} – {v['nome']} · {v['servico'] or '-'} (nº {v['id']}) {marca}")
            for b in bl:
                linhas.append(f"🚫 {'dia todo' if not b['hora'] else b['hora']} bloqueado" + (f" – {b['motivo']}" if b["motivo"] else ""))
        d += timedelta(days=1)
    return "\n".join(linhas)


def resumo_hoje() -> str:
    """Parte do lembrete da manhã: visitas de hoje e pedidos esperando resposta."""
    h = config.hoje()
    hoje = listar(h, h, ("confirmada",))
    pend = _linhas("SELECT * FROM visitas WHERE situacao = 'pendente' AND data >= ? ORDER BY data, hora", h.isoformat())
    partes = []
    if hoje:
        partes.append("🗓️ *Visitas de hoje:*\n" + "\n".join(
            f"{v['hora']} – {v['nome']} · {v['servico'] or '-'}" + (f" · {v['endereco']}" if v["endereco"] else "") for v in hoje))
    if pend:
        partes.append(f"⏳ *{len(pend)} pedido(s) de visita esperando sua resposta:*\n" + "\n".join(
            f"nº {v['id']} – {v['nome']}, {_fmt_dia(v['data'])} às {v['hora']}" for v in pend[:8])
            + "\nResponda *confirmar nº* ou *recusar nº*.")
    return "\n\n".join(partes)


def para_ia() -> str:
    h = config.hoje()
    vs = _linhas("SELECT * FROM visitas WHERE situacao IN ('pendente','confirmada') AND data >= ? ORDER BY data, hora LIMIT 40",
                 h.isoformat())
    bl = bloqueios(h, h + timedelta(days=60))
    c = cfg()
    t = (f"Horários padrão: seg a sex {', '.join(c['semana']) or 'nenhum'}; sábado {', '.join(c['sabado']) or 'nenhum'}; "
         f"domingo {', '.join(c['domingo']) or 'nenhum'}. O site mostra {c['dias']} dias à frente.\n")
    t += "\n".join(f"nº {v['id']} | {v['situacao']} | {v['data']} {v['hora']} | {v['nome']} | {v['telefone'] or '-'} | {v['servico'] or '-'}"
                   for v in vs) or "nenhuma visita marcada"
    if bl:
        t += "\nBloqueios: " + "; ".join(f"{b['data']} {b['hora'] or 'dia todo'}" for b in bl[:30])
    return t


# ------------------------------------------------------------------ aviso ao dono
def _numeros_dono():
    nums = {chave: n for chave, n in db.ajustes_com_prefixo("numero:").items() if config.autorizado(n)}
    if not nums:
        nums = {config.chave_numero(n): n for n in config.ALLOWED_NUMBERS}
    return nums


def numeros_na_janela() -> list[str]:
    """Números do dono que conversaram com o assistente nas últimas 23 h (podem receber mensagem livre)."""
    out = []
    for chave, numero in _numeros_dono().items():
        ultima = db.ajuste(f"ultima_msg:{chave}")
        if ultima and config.agora() - datetime.fromisoformat(ultima) < timedelta(hours=23):
            out.append(numero)
    return out


def avisar_dono(vid: int) -> bool:
    """Manda o pedido novo para o dono. Fora da janela de 24 h do WhatsApp, usa o modelo aprovado
    (TEMPLATE_VISITA); sem modelo, o aviso aparece na próxima conversa."""
    v = obter(vid)
    if not v:
        return False
    enviado = False
    for chave, numero in _numeros_dono().items():
        ultima = db.ajuste(f"ultima_msg:{chave}")
        na_janela = bool(ultima) and config.agora() - datetime.fromisoformat(ultima) < timedelta(hours=23)
        try:
            if na_janela:
                whatsapp.enviar_texto(numero, texto_novo(v))
                enviado = True
            elif config.TEMPLATE_VISITA:
                whatsapp.enviar_template(numero, config.TEMPLATE_VISITA, [f"{v['nome']}, {quando(v)} (nº {v['id']})"])
                enviado = True
        except Exception as e:
            log.warning("não consegui avisar %s do pedido de visita %s: %s", numero, vid, e)
    if enviado:
        with db.conectar() as con:
            con.execute("UPDATE visitas SET avisado = 1 WHERE id = ?", (vid,))
    else:
        log.info("pedido de visita %s fica para a próxima conversa do dono (fora da janela de 24 h)", vid)
    return enviado


def avisos_pendentes() -> str:
    """Pedidos do site que ainda não chegaram ao dono: aparecem na próxima conversa dele."""
    vs = _linhas("SELECT * FROM visitas WHERE avisado = 0 AND situacao = 'pendente' ORDER BY id")
    if not vs:
        return ""
    with db.conectar() as con:
        con.execute("UPDATE visitas SET avisado = 1 WHERE avisado = 0")
    return "\n\n".join(texto_novo(v) for v in vs)
