"""Conteúdo do site (vitrine): serviços e fotos de trabalhos, controlados pelo WhatsApp e pelo painel.

Fotos chegam pelo WhatsApp com uma legenda ("antes – quarto com mofo", "depois", "galeria fachada").
Nada vai para o site sem o dono responder "sim". O site busca tudo em /api/site/conteudo.
"""
import base64
import io
import json
import logging
import re
import secrets
import unicodedata
from datetime import timedelta

from . import config, db

log = logging.getLogger("assistente")

PASTA = config.DATA_DIR / "site"
PASTA.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_servicos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    descricao TEXT DEFAULT '',
    icone TEXT DEFAULT 'ferramenta',
    ordem INTEGER DEFAULT 0,
    ativo INTEGER DEFAULT 1,
    rascunho_de TEXT                     -- usuário que pediu e ainda não confirmou (NULL = confirmado)
);
CREATE TABLE IF NOT EXISTS site_fotos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    usuario TEXT,
    tipo TEXT DEFAULT '',                -- par (antes e depois) | galeria | '' (ainda não disse)
    legenda TEXT DEFAULT '',
    foto TEXT,                           -- galeria: a foto; par: o ANTES
    foto2 TEXT,                          -- par: o DEPOIS
    publicado INTEGER DEFAULT 0
);
"""

# ícones que o site sabe desenhar
ICONES = {
    "rolo": ("pintura", "pintar", "tinta", "textura", "grafiato", "verniz", "massa"),
    "gota": ("mofo", "infiltra", "impermeab", "umidade", "vazamento", "goteira"),
    "chave": ("eletric", "hidraul", "tomada", "chuveiro", "reparo", "conserto", "manutenc", "encanamento", "disjuntor"),
    "casa": ("reforma", "telhado", "calha", "demoli", "alvenaria", "construc", "drywall", "forro", "gesso"),
    "cubo": ("3d", "projeto", "planta", "render"),
    "predio": ("predial", "condominio", "empresa", "comercial", "fachada", "avcb", "spda"),
    "piso": ("piso", "porcelanato", "azulejo", "revestimento", "rejunte", "laminado"),
}

PADRAO = [
    ("Pintura", "Paredes, tetos e portas, com correção de massa, lixamento e acabamento caprichado.", "rolo"),
    ("Mofo e infiltração", "Encontramos a causa, tratamos a parede e refazemos a pintura para o mofo não voltar.", "gota"),
    ("Reparos elétricos e hidráulicos", "Tomadas, disjuntores, chuveiros, vazamentos e consertos do dia a dia.", "chave"),
    ("Reformas", "Demolição e retirada de entulho, drywall, forro, pisos, portas e acabamentos.", "casa"),
    ("Projeto 3D", "Imagens realistas do ambiente para aprovar layout, materiais e cores antes da obra.", "cubo"),
    ("Manutenção predial (empresa/condomínio)", "Elétrica, SPDA, hidráulica, telhados, regularização para AVCB e manutenção preventiva.", "predio"),
]


def iniciar():
    with db.conectar() as con:
        con.executescript(SCHEMA)
        if not con.execute("SELECT COUNT(*) FROM site_servicos").fetchone()[0]:
            for k, (n, d, i) in enumerate(PADRAO):
                con.execute("INSERT INTO site_servicos (nome, descricao, icone, ordem) VALUES (?,?,?,?)", (n, d, i, k))


def _linhas(sql, *p):
    with db.conectar() as con:
        return [dict(r) for r in con.execute(sql, p).fetchall()]


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").lower()


def icone_para(texto: str) -> str:
    t = _sem_acento(texto)
    for ic, chaves in ICONES.items():
        if any(c in t for c in chaves):
            return ic
    return "ferramenta"


def url_site() -> str:
    if config.SITE_URL:
        return config.SITE_URL
    return config.SITE_ORIGENS[0] if config.SITE_ORIGENS else ""


# ------------------------------------------------------------------ fotos: arquivos
def salvar_imagem(conteudo: bytes) -> str:
    """Grava a foto reduzida (até 1600 px, JPEG) e devolve o nome do arquivo."""
    nome = secrets.token_hex(8) + ".jpg"
    try:
        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(conteudo))
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((1600, 1600))
        im.save(PASTA / nome, "JPEG", quality=82, optimize=True)
    except Exception as e:                       # sem Pillow ou formato estranho: guarda como veio
        log.warning("não consegui reduzir a foto (%s); guardando o original", e)
        (PASTA / nome).write_bytes(conteudo)
    return nome


def salvar_data_url(texto: str) -> str:
    """Foto enviada pelo painel (data:image/jpeg;base64,...)."""
    if not texto:
        raise ValueError("foto vazia")
    dados = texto.split(",", 1)[1] if texto.startswith("data:") else texto
    conteudo = base64.b64decode(dados)
    if len(conteudo) > 15 * 1024 * 1024:
        raise ValueError("foto grande demais")
    return salvar_imagem(conteudo)


def caminho(arquivo: str):
    if not re.fullmatch(r"[0-9a-f]{16}\.jpg", arquivo or ""):
        return None
    p = PASTA / arquivo
    return p if p.exists() else None


def _apagar_arquivos(*nomes):
    for n in nomes:
        p = caminho(n) if n else None
        if p:
            p.unlink(missing_ok=True)


# ------------------------------------------------------------------ consultas
def servicos(incluir_inativos=False):
    return _linhas("SELECT * FROM site_servicos WHERE rascunho_de IS NULL" + ("" if incluir_inativos else " AND ativo = 1")
                   + " ORDER BY ordem, id")


def conteudo_publico() -> dict:
    base = "/api/site/foto/"
    pub = _linhas("SELECT * FROM site_fotos WHERE publicado = 1 ORDER BY id DESC")
    return {
        "servicos": [{"nome": s["nome"], "descricao": s["descricao"], "icone": s["icone"]} for s in servicos()],
        "antes_depois": [{"id": f["id"], "legenda": f["legenda"], "antes": base + f["foto"], "depois": base + f["foto2"]}
                         for f in pub if f["tipo"] == "par" and f["foto"] and f["foto2"]],
        "galeria": [{"id": f["id"], "legenda": f["legenda"], "foto": base + f["foto"]} for f in pub if f["tipo"] == "galeria" and f["foto"]],
    }


def para_ia() -> str:
    s = "; ".join(f"serviço {x['id']}: {x['nome']}" for x in servicos()) or "nenhum"
    f = "; ".join(f"foto {x['id']} ({'antes e depois' if x['tipo'] == 'par' else 'galeria'}): {x['legenda'] or 'sem legenda'}"
                  for x in _linhas("SELECT * FROM site_fotos WHERE publicado = 1 ORDER BY id DESC LIMIT 40")) or "nenhuma"
    return f"Serviços no site: {s}.\nFotos no site: {f}."


def texto_lista() -> str:
    sv = servicos()
    pub = _linhas("SELECT * FROM site_fotos WHERE publicado = 1 ORDER BY id DESC")
    linhas = ["🌐 *Conteúdo do site*", "", "*Serviços:*"]
    linhas += [f"{k}. {s['nome']} (nº {s['id']})" for k, s in enumerate(sv, 1)] or ["nenhum"]
    linhas += ["", "*Fotos:*"]
    linhas += [f"nº {f['id']} – {'antes e depois' if f['tipo'] == 'par' else 'galeria'}: {f['legenda'] or 'sem legenda'}" for f in pub] or ["nenhuma ainda"]
    linhas += ["", "Para tirar: \"tira do site a foto 3\" ou \"tira o serviço Projeto 3D\"."]
    return "\n".join(linhas)


# ------------------------------------------------------------------ fotos pelo WhatsApp
_PALAVRA = re.compile(r"^\s*(antes|depois|galeria|site|obra|trabalho|portf[oó]lio)\b[\s:\-–—,.]*(.*)$", re.IGNORECASE | re.DOTALL)


def _classificar(legenda: str):
    m = _PALAVRA.match(legenda or "")
    if not m:
        return None, (legenda or "").strip()
    p = _sem_acento(m.group(1))
    tipo = "antes" if p == "antes" else "depois" if p == "depois" else "galeria"
    return tipo, m.group(2).strip()


def _limpar_velhos():
    """Rascunhos esquecidos (mais de 3 dias) são apagados."""
    limite = (config.agora() - timedelta(days=3)).isoformat(timespec="seconds")
    velhos = _linhas("SELECT * FROM site_fotos WHERE publicado = 0 AND usuario NOT LIKE 'oculta:%' AND usuario != 'painel' AND criado_em < ?", limite)
    for f in velhos:
        _apagar_arquivos(f["foto"], f["foto2"])
    with db.conectar() as con:
        con.executemany("DELETE FROM site_fotos WHERE id = ?", [(f["id"],) for f in velhos])


def _rascunhos(usuario):
    return _linhas("SELECT * FROM site_fotos WHERE usuario = ? AND publicado = 0 ORDER BY id", usuario)


def _encaixar(usuario, arquivo, tipo, legenda):
    """Coloca a foto no rascunho certo e devolve a pergunta para o dono."""
    with db.conectar() as con:
        if tipo in ("antes", "depois"):
            campo, outro = ("foto", "foto2") if tipo == "antes" else ("foto2", "foto")
            aberto = con.execute(f"SELECT * FROM site_fotos WHERE usuario = ? AND publicado = 0 AND tipo = 'par' AND {campo} IS NULL "
                                 f"AND {outro} IS NOT NULL ORDER BY id DESC LIMIT 1", (usuario,)).fetchone()
            if aberto:
                con.execute(f"UPDATE site_fotos SET {campo} = ?, legenda = CASE WHEN legenda = '' THEN ? ELSE legenda END WHERE id = ?",
                            (arquivo, legenda, aberto["id"]))
            else:
                con.execute(f"INSERT INTO site_fotos (criado_em, usuario, tipo, legenda, {campo}) VALUES (?,?,?,?,?)",
                            (db.agora(), usuario, "par", legenda, arquivo))
        else:
            con.execute("INSERT INTO site_fotos (criado_em, usuario, tipo, legenda, foto) VALUES (?,?,?,?,?)",
                        (db.agora(), usuario, tipo or "", legenda, arquivo))
    return _pergunta(usuario)


def _pergunta(usuario) -> str:
    rs = _rascunhos(usuario)
    sem_tipo = [r for r in rs if not r["tipo"]]
    if sem_tipo:
        return ("📷 Recebi a foto. O que faço com ela no site? Responda:\n"
                "• *antes* ou *depois* (para montar um antes e depois)\n"
                "• *galeria* (foto de trabalho feito)\n"
                "Pode mandar a legenda junto, ex.: _galeria pintura de fachada na Mooca_.\n"
                "Se não for para o site, responda *não*.")
    falta = [r for r in rs if r["tipo"] == "par" and not (r["foto"] and r["foto2"])]
    if falta:
        r = falta[-1]
        qual = "DEPOIS" if r["foto"] else "ANTES"
        return f"📷 Recebi a foto do *{'ANTES' if qual == 'DEPOIS' else 'DEPOIS'}*. Agora manda a foto do *{qual}* (escreva _{qual.lower()}_ na legenda)."
    prontos = [r for r in rs if r["tipo"] in ("par", "galeria")]
    if not prontos:
        return ""
    itens = "\n".join(f"• {'Antes e depois' if r['tipo'] == 'par' else 'Galeria'}: “{r['legenda'] or 'sem legenda'}”" for r in prontos)
    return f"🌐 Coloco no site?\n{itens}\n\nResponda *sim* para publicar ou *não* para descartar. Para mudar a legenda, responda _legenda: novo texto_."


def receber_foto(usuario: str, conteudo: bytes, legenda: str) -> list:
    _limpar_velhos()
    tipo, texto = _classificar(legenda)
    arquivo = salvar_imagem(conteudo)
    return [{"texto": _encaixar(usuario, arquivo, tipo, texto)}]


_SIM = re.compile(r"^\s*(sim|s|pode|pode publicar|publica|publicar|ok|isso|confirmo|confirma|manda|bora)\s*[!.]*\s*$", re.IGNORECASE)
_NAO = re.compile(r"^\s*(n[aã]o|nao quero|cancela|cancelar|descarta|descartar|deixa|esquece)\s*[!.]*\s*$", re.IGNORECASE)
_LEGENDA = re.compile(r"^\s*legenda\s*[:\-–]\s*(.+)$", re.IGNORECASE | re.DOTALL)


def tratar_resposta(usuario: str, texto: str):
    """Respostas rápidas enquanto há foto ou serviço esperando confirmação. Devolve None se não for o caso."""
    rs = _rascunhos(usuario)
    serv = _linhas("SELECT * FROM site_servicos WHERE rascunho_de = ?", usuario)
    if not rs and not serv:
        return None
    sem_tipo = [r for r in rs if not r["tipo"]]
    if sem_tipo:
        tipo, leg = _classificar(texto)
        if tipo:
            alvos = sem_tipo if tipo == "galeria" else sem_tipo[:1]
            for r in alvos:
                with db.conectar() as con:
                    con.execute("DELETE FROM site_fotos WHERE id = ?", (r["id"],))
                _encaixar(usuario, r["foto"], tipo, leg or r["legenda"])
            return [{"texto": _pergunta(usuario)}]
    m = _LEGENDA.match(texto)
    if m and rs:
        with db.conectar() as con:
            con.execute("UPDATE site_fotos SET legenda = ? WHERE usuario = ? AND publicado = 0", (m.group(1).strip()[:200], usuario))
        return [{"texto": _pergunta(usuario)}]
    if _SIM.match(texto):
        prontos = [r for r in rs if r["tipo"] == "galeria" or (r["tipo"] == "par" and r["foto"] and r["foto2"])]
        with db.conectar() as con:
            for r in prontos:
                con.execute("UPDATE site_fotos SET publicado = 1, usuario = NULL WHERE id = ?", (r["id"],))
            for s in serv:
                con.execute("UPDATE site_servicos SET rascunho_de = NULL, ativo = 1 WHERE id = ?", (s["id"],))
        partes = []
        if prontos:
            partes.append(f"{len(prontos)} foto(s)" if len(prontos) > 1 else ("o antes e depois" if prontos[0]["tipo"] == "par" else "a foto"))
        if serv:
            partes.append("o serviço " + ", ".join(f"“{s['nome']}”" for s in serv))
        if not partes:
            return [{"texto": _pergunta(usuario) or "Não há nada esperando para publicar."}]
        site = url_site()
        return [{"texto": f"✅ Publiquei {' e '.join(partes)} no site." + (f" Já aparece em {site}" if site else "")
                          + "\nPara ver ou tirar algo: \"mostra o conteúdo do site\"."}]
    if _NAO.match(texto):
        for r in rs:
            _apagar_arquivos(r["foto"], r["foto2"])
        with db.conectar() as con:
            con.execute("DELETE FROM site_fotos WHERE usuario = ? AND publicado = 0", (usuario,))
            con.execute("DELETE FROM site_servicos WHERE rascunho_de = ?", (usuario,))
        return [{"texto": "Ok, não coloquei no site."}]
    return None


# ------------------------------------------------------------------ comandos da IA
def executar(usuario: str, args: dict) -> list:
    acao = args.get("acao")
    if acao == "listar":
        return [{"texto": texto_lista()}]
    if acao == "remover_foto":
        f = _linhas("SELECT * FROM site_fotos WHERE id = ?", int(args.get("id") or 0))
        if not f:
            return [{"texto": "Não achei essa foto. Diga \"mostra o conteúdo do site\" para ver os números."}]
        _apagar_arquivos(f[0]["foto"], f[0]["foto2"])
        with db.conectar() as con:
            con.execute("DELETE FROM site_fotos WHERE id = ?", (f[0]["id"],))
        return [{"texto": f"🗑️ Tirei do site a foto nº {f[0]['id']} ({f[0]['legenda'] or 'sem legenda'})."}]
    if acao == "adicionar_servico":
        nome = " ".join(str(args.get("nome") or "").split())[:80]
        if not nome:
            return [{"texto": "Qual o nome do serviço?"}]
        desc = " ".join(str(args.get("descricao") or "").split())[:220]
        with db.conectar() as con:
            con.execute("DELETE FROM site_servicos WHERE rascunho_de = ?", (usuario,))
            ordem = con.execute("SELECT COALESCE(MAX(ordem), 0) + 1 FROM site_servicos").fetchone()[0]
            con.execute("INSERT INTO site_servicos (nome, descricao, icone, ordem, ativo, rascunho_de) VALUES (?,?,?,?,0,?)",
                        (nome, desc, icone_para(nome + " " + desc), ordem, usuario))
        return [{"texto": f"🌐 Vou colocar no site o serviço:\n\n*{nome}*\n{desc}\n\nPublico? Responda *sim* ou *não*. "
                          "Para mudar o texto, me diga como prefere."}]
    alvo = _achar_servico(args)
    if acao in ("editar_servico", "remover_servico") and not alvo:
        return [{"texto": "Não achei esse serviço no site. Diga \"mostra o conteúdo do site\" para ver a lista."}]
    if acao == "editar_servico":
        nome = " ".join(str(args.get("nome") or alvo["nome"]).split())[:80]
        desc = " ".join(str(args.get("descricao") or alvo["descricao"]).split())[:220]
        with db.conectar() as con:
            con.execute("UPDATE site_servicos SET nome = ?, descricao = ?, icone = ? WHERE id = ?",
                        (nome, desc, icone_para(nome + " " + desc), alvo["id"]))
        return [{"texto": f"✏️ Atualizado no site:\n*{nome}*\n{desc}"}]
    if acao == "remover_servico":
        with db.conectar() as con:
            con.execute("DELETE FROM site_servicos WHERE id = ?", (alvo["id"],))
        return [{"texto": f"🗑️ Tirei do site o serviço “{alvo['nome']}”."}]
    return [{"texto": "Não entendi o que mudar no site. Exemplos: \"mostra o conteúdo do site\", \"tira a foto 3\", "
                      "\"acrescenta o serviço de impermeabilização\"."}]


def _achar_servico(args):
    if args.get("id"):
        r = _linhas("SELECT * FROM site_servicos WHERE id = ? AND rascunho_de IS NULL", int(args["id"]))
        if r:
            return r[0]
    nome = _sem_acento(args.get("nome_atual") or args.get("nome") or "")
    if not nome:
        return None
    for s in servicos(True):
        if nome in _sem_acento(s["nome"]) or _sem_acento(s["nome"]) in nome:
            return s
    return None


# ------------------------------------------------------------------ painel
def salvar_servicos(lista: list) -> list:
    validos = [s for s in lista if " ".join(str(s.get("nome") or "").split())]
    if not validos:
        raise ValueError("o site precisa de pelo menos um serviço")
    with db.conectar() as con:
        ids = []
        for k, s in enumerate(validos):
            nome = " ".join(str(s["nome"]).split())[:80]
            desc = " ".join(str(s.get("descricao") or "").split())[:220]
            ic = s.get("icone") if s.get("icone") in list(ICONES) + ["ferramenta"] else icone_para(nome + " " + desc)
            ativo = 1 if s.get("ativo", 1) else 0
            if s.get("id"):
                con.execute("UPDATE site_servicos SET nome=?, descricao=?, icone=?, ordem=?, ativo=?, rascunho_de=NULL WHERE id=?",
                            (nome, desc, ic, k, ativo, int(s["id"])))
                ids.append(int(s["id"]))
            else:
                ids.append(con.execute("INSERT INTO site_servicos (nome, descricao, icone, ordem, ativo) VALUES (?,?,?,?,?)",
                                       (nome, desc, ic, k, ativo)).lastrowid)
        marcas = ",".join("?" * len(ids))
        con.execute(f"DELETE FROM site_servicos WHERE rascunho_de IS NULL AND id NOT IN ({marcas})", ids)
    return servicos(True)


def foto_do_painel(tipo: str, legenda: str, foto: str, foto2: str = "") -> int:
    if tipo not in ("par", "galeria"):
        raise ValueError("tipo inválido")
    a = salvar_data_url(foto)
    b = salvar_data_url(foto2) if tipo == "par" else None
    with db.conectar() as con:
        return con.execute("INSERT INTO site_fotos (criado_em, usuario, tipo, legenda, foto, foto2, publicado) VALUES (?,?,?,?,?,?,1)",
                           (db.agora(), None, tipo, " ".join((legenda or "").split())[:200], a, b)).lastrowid


def alterar_foto(fid: int, legenda=None, publicado=None):
    with db.conectar() as con:
        if legenda is not None:
            con.execute("UPDATE site_fotos SET legenda = ? WHERE id = ?", (" ".join(str(legenda).split())[:200], fid))
        if publicado is not None:
            con.execute("UPDATE site_fotos SET publicado = ?, usuario = ? WHERE id = ?",
                        (1 if publicado else 0, None if publicado else f"oculta:{fid}", fid))


def apagar_foto(fid: int):
    f = _linhas("SELECT * FROM site_fotos WHERE id = ?", fid)
    if f:
        _apagar_arquivos(f[0]["foto"], f[0]["foto2"])
        with db.conectar() as con:
            con.execute("DELETE FROM site_fotos WHERE id = ?", (fid,))


def fotos_do_painel():
    return _linhas("SELECT * FROM site_fotos WHERE (publicado = 1 OR usuario LIKE 'oculta:%') "
                   "AND (tipo = 'galeria' OR (tipo = 'par' AND foto IS NOT NULL AND foto2 IS NOT NULL)) ORDER BY id DESC")


def json_painel() -> str:
    return json.dumps({"servicos": servicos(True), "fotos": fotos_do_painel()}, ensure_ascii=False)
