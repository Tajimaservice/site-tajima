"""Banco de dados SQLite: orçamentos, lançamentos, contas a pagar/receber, obras e histórico da conversa."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS orcamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    usuario TEXT,
    cliente TEXT,
    endereco TEXT,
    itens_json TEXT NOT NULL,
    desconto_pct REAL DEFAULT 0,
    observacoes TEXT,
    total REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS lancamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    usuario TEXT,
    data TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('despesa', 'receita')),
    valor REAL NOT NULL,
    categoria TEXT,
    obra TEXT,
    forma_pagamento TEXT,
    descricao TEXT,
    texto_original TEXT,
    excluido INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT,
    papel TEXT,
    conteudo TEXT,
    criado_em TEXT
);
CREATE TABLE IF NOT EXISTS mensagens_processadas (
    id TEXT PRIMARY KEY,
    criado_em TEXT
);
CREATE TABLE IF NOT EXISTS contas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    usuario TEXT,
    tipo TEXT NOT NULL CHECK (tipo IN ('pagar', 'receber')),
    descricao TEXT,
    valor REAL NOT NULL,
    vencimento TEXT NOT NULL,
    obra TEXT,
    categoria TEXT,
    situacao TEXT NOT NULL DEFAULT 'aberta',      -- aberta | quitada | cancelada
    quitada_em TEXT,
    lancamento_id INTEGER
);
CREATE TABLE IF NOT EXISTS obras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    nome TEXT NOT NULL UNIQUE COLLATE NOCASE,
    cliente TEXT,
    orcamento_id INTEGER,
    valor_contratado REAL DEFAULT 0,
    custo_previsto REAL DEFAULT 0,
    situacao TEXT NOT NULL DEFAULT 'andamento'    -- andamento | concluida
);
CREATE TABLE IF NOT EXISTS ajustes (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
"""


@contextmanager
def conectar():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def iniciar():
    with conectar() as con:
        con.executescript(SCHEMA)


def agora():
    return config.agora().isoformat(timespec="seconds")


# ------------------------------------------------------------------ mensagens repetidas
def ja_processada(msg_id: str) -> bool:
    """Marca a mensagem como processada; devolve True se ela já tinha chegado antes (o WhatsApp reenvia)."""
    with conectar() as con:
        try:
            con.execute("INSERT INTO mensagens_processadas (id, criado_em) VALUES (?, ?)", (msg_id, agora()))
            return False
        except sqlite3.IntegrityError:
            return True


# ------------------------------------------------------------------ histórico curto da conversa
def salvar_historico(usuario, papel, conteudo):
    with conectar() as con:
        con.execute("INSERT INTO historico (usuario, papel, conteudo, criado_em) VALUES (?, ?, ?, ?)",
                    (usuario, papel, conteudo, agora()))


def historico_recente(usuario, limite=8):
    with conectar() as con:
        rows = con.execute("SELECT papel, conteudo FROM historico WHERE usuario = ? ORDER BY id DESC LIMIT ?",
                           (usuario, limite)).fetchall()
    return [dict(r) for r in reversed(rows)]


# ------------------------------------------------------------------ orçamentos
def salvar_orcamento(usuario, cliente, endereco, itens, desconto_pct, observacoes, total, orc_id=None):
    with conectar() as con:
        if orc_id:
            con.execute("""UPDATE orcamentos SET cliente=?, endereco=?, itens_json=?, desconto_pct=?, observacoes=?, total=?
                           WHERE id=?""",
                        (cliente, endereco, json.dumps(itens, ensure_ascii=False), desconto_pct, observacoes, total, orc_id))
            return orc_id
        cur = con.execute("""INSERT INTO orcamentos (criado_em, usuario, cliente, endereco, itens_json, desconto_pct, observacoes, total)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                          (agora(), usuario, cliente, endereco, json.dumps(itens, ensure_ascii=False), desconto_pct, observacoes, total))
        return cur.lastrowid


def obter_orcamento(orc_id=None, usuario=None):
    with conectar() as con:
        if orc_id:
            r = con.execute("SELECT * FROM orcamentos WHERE id = ?", (orc_id,)).fetchone()
        else:
            r = con.execute("SELECT * FROM orcamentos WHERE usuario = ? ORDER BY id DESC LIMIT 1", (usuario,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["itens"] = json.loads(d.pop("itens_json"))
    return d


def listar_orcamentos(limite=10):
    with conectar() as con:
        rows = con.execute("SELECT id, criado_em, cliente, total FROM orcamentos ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ lançamentos financeiros
def inserir_lancamento(usuario, data, tipo, valor, categoria, obra, forma, descricao, texto_original):
    with conectar() as con:
        cur = con.execute("""INSERT INTO lancamentos (criado_em, usuario, data, tipo, valor, categoria, obra, forma_pagamento, descricao, texto_original)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                          (agora(), usuario, data, tipo, valor, categoria, obra, forma, descricao, texto_original))
        return cur.lastrowid


def excluir_ultimo_lancamento(usuario):
    with conectar() as con:
        r = con.execute("SELECT * FROM lancamentos WHERE usuario = ? AND excluido = 0 ORDER BY id DESC LIMIT 1", (usuario,)).fetchone()
        if not r:
            return None
        con.execute("UPDATE lancamentos SET excluido = 1 WHERE id = ?", (r["id"],))
        return dict(r)


def lancamentos(inicio, fim, obra=None):
    q = "SELECT * FROM lancamentos WHERE excluido = 0 AND data >= ? AND data <= ?"
    args = [inicio, fim]
    if obra:
        q += " AND lower(obra) LIKE ?"
        args.append(f"%{obra.lower()}%")
    q += " ORDER BY data, id"
    with conectar() as con:
        return [dict(r) for r in con.execute(q, args).fetchall()]


def obras_conhecidas():
    with conectar() as con:
        rows = con.execute("""SELECT nome AS obra FROM obras UNION
                              SELECT DISTINCT obra FROM lancamentos WHERE obra IS NOT NULL AND obra != '' AND excluido = 0""").fetchall()
    return sorted({r["obra"] for r in rows}, key=str.lower)


# ------------------------------------------------------------------ ajustes (pequenos valores guardados)
def ajuste(chave, padrao=None):
    with conectar() as con:
        r = con.execute("SELECT valor FROM ajustes WHERE chave = ?", (chave,)).fetchone()
    return r["valor"] if r else padrao


def gravar_ajuste(chave, valor):
    with conectar() as con:
        con.execute("INSERT INTO ajustes (chave, valor) VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                    (chave, str(valor)))


def ajustes_com_prefixo(prefixo):
    with conectar() as con:
        rows = con.execute("SELECT chave, valor FROM ajustes WHERE chave LIKE ?", (prefixo + "%",)).fetchall()
    return {r["chave"][len(prefixo):]: r["valor"] for r in rows}


# ------------------------------------------------------------------ contas a pagar / receber
def inserir_conta(usuario, tipo, valor, vencimento, descricao=None, obra=None, categoria=None):
    with conectar() as con:
        cur = con.execute("""INSERT INTO contas (criado_em, usuario, tipo, descricao, valor, vencimento, obra, categoria)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                          (agora(), usuario, tipo, descricao, valor, vencimento, obra, categoria))
        return cur.lastrowid


def obter_conta(conta_id):
    with conectar() as con:
        r = con.execute("SELECT * FROM contas WHERE id = ?", (conta_id,)).fetchone()
    return dict(r) if r else None


def contas_abertas(ate=None, tipo=None, obra=None):
    q = "SELECT * FROM contas WHERE situacao = 'aberta'"
    args = []
    if ate:
        q += " AND vencimento <= ?"; args.append(ate)
    if tipo:
        q += " AND tipo = ?"; args.append(tipo)
    if obra:
        q += " AND lower(obra) LIKE ?"; args.append(f"%{obra.lower()}%")
    q += " ORDER BY vencimento, id"
    with conectar() as con:
        return [dict(r) for r in con.execute(q, args).fetchall()]


def marcar_conta(conta_id, situacao, lancamento_id=None):
    with conectar() as con:
        con.execute("UPDATE contas SET situacao = ?, quitada_em = ?, lancamento_id = ? WHERE id = ?",
                    (situacao, agora() if situacao == "quitada" else None, lancamento_id, conta_id))


def reabrir_conta_do_lancamento(lancamento_id):
    """Se o lançamento desfeito tinha quitado uma conta, a conta volta a ficar em aberto."""
    with conectar() as con:
        r = con.execute("SELECT id FROM contas WHERE lancamento_id = ?", (lancamento_id,)).fetchone()
        if r:
            con.execute("UPDATE contas SET situacao = 'aberta', quitada_em = NULL, lancamento_id = NULL WHERE id = ?", (r["id"],))
            return r["id"]
    return None


# ------------------------------------------------------------------ obras
def salvar_obra(nome, **campos):
    """Cria a obra (se não existir) e atualiza só os campos informados."""
    campos = {k: v for k, v in campos.items() if v is not None}
    with conectar() as con:
        r = con.execute("SELECT id FROM obras WHERE nome = ?", (nome,)).fetchone()
        if not r:
            con.execute("INSERT INTO obras (criado_em, nome) VALUES (?, ?)", (agora(), nome))
        for k, v in campos.items():
            if k in ("cliente", "orcamento_id", "valor_contratado", "custo_previsto", "situacao"):
                con.execute(f"UPDATE obras SET {k} = ? WHERE nome = ?", (v, nome))
        return dict(con.execute("SELECT * FROM obras WHERE nome = ?", (nome,)).fetchone())


def obter_obra(nome):
    """Procura a obra pelo nome exato ou por parte do nome."""
    if not nome:
        return None
    with conectar() as con:
        r = con.execute("SELECT * FROM obras WHERE nome = ?", (nome,)).fetchone()
        if not r:
            r = con.execute("SELECT * FROM obras WHERE lower(nome) LIKE ? ORDER BY id DESC", (f"%{nome.lower()}%",)).fetchone()
        if not r:
            r = con.execute("SELECT * FROM obras WHERE ? LIKE '%' || lower(nome) || '%' ORDER BY length(nome) DESC",
                            (nome.lower(),)).fetchone()
    return dict(r) if r else None


def listar_obras(situacao=None):
    q = "SELECT * FROM obras" + (" WHERE situacao = ?" if situacao else "") + " ORDER BY id DESC"
    with conectar() as con:
        return [dict(r) for r in con.execute(q, (situacao,) if situacao else ()).fetchall()]
