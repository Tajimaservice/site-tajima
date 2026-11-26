"""Tabela de preços. Na primeira vez é copiada do catalogo.csv para o banco; depois você edita pelo painel
(ou pelo WhatsApp: "muda o preço da pintura interna para 26 reais o metro")."""
import csv
import logging

from . import config, db

log = logging.getLogger("assistente")

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalogo (
    codigo TEXT PRIMARY KEY,
    servico TEXT NOT NULL,
    unidade TEXT NOT NULL DEFAULT 'un',
    mao_de_obra REAL NOT NULL DEFAULT 0,
    material REAL NOT NULL DEFAULT 0,
    palavras_chave TEXT DEFAULT '',
    site INTEGER NOT NULL DEFAULT 0,          -- 1 = aparece na calculadora do site
    ativo INTEGER NOT NULL DEFAULT 1,
    ordem INTEGER DEFAULT 0
);
"""
# serviços que já começam aparecendo na calculadora do site (dá para mudar no painel)
SITE_PADRAO = {"P01", "P02", "P03", "P04", "P05", "P06", "D01", "D02", "E01", "E02", "H04", "H05", "H06", "H07", "R04", "A06"}


def _num(txt):
    txt = (txt or "0").strip().replace(".", "").replace(",", ".") if "," in (txt or "") else (txt or "0").strip()
    return float(txt or 0)


def iniciar():
    with db.conectar() as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM catalogo").fetchone()[0]:
            return
        if not config.CATALOGO_CSV.exists():
            return
        with open(config.CATALOGO_CSV, encoding="utf-8") as f:
            for k, row in enumerate(csv.DictReader(f, delimiter=";")):
                cod = (row.get("codigo") or "").strip().upper()
                if not cod:
                    continue
                con.execute("INSERT OR IGNORE INTO catalogo (codigo, servico, unidade, mao_de_obra, material, palavras_chave, site, ordem) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (cod, row["servico"].strip(), row["unidade"].strip(), _num(row["mao_de_obra"]), _num(row["material"]),
                             (row.get("palavras_chave") or "").strip(), 1 if cod in SITE_PADRAO else 0, k))
        log.info("tabela de preços copiada do %s para o banco", config.CATALOGO_CSV.name)


def _item(r) -> dict:
    d = dict(r)
    d["preco"] = round(d["mao_de_obra"] + d["material"], 2)
    return d


def listar(inativos=False) -> list[dict]:
    with db.conectar() as con:
        rows = con.execute("SELECT * FROM catalogo" + ("" if inativos else " WHERE ativo = 1") + " ORDER BY ordem, codigo").fetchall()
    return [_item(r) for r in rows]


def carregar() -> dict:
    return {i["codigo"]: i for i in listar()}


def publicos() -> list[dict]:
    return [{"codigo": i["codigo"], "servico": i["servico"], "unidade": i["unidade"], "preco": i["preco"]}
            for i in listar() if i["site"]]


def texto_para_ia():
    """Lista compacta enviada à IA para ela escolher os códigos certos."""
    return "\n".join(f"{i['codigo']} | {i['servico']} | {i['unidade']} | R$ {i['preco']:.2f} (mão de obra {i['mao_de_obra']:.2f} + "
                     f"material {i['material']:.2f}) | {i['palavras_chave']}" for i in listar())


def item(codigo):
    return carregar().get((codigo or "").strip().upper())


def novo_codigo(prefixo="X") -> str:
    prefixo = (prefixo or "X").strip().upper()[:1] or "X"
    usados = {i["codigo"] for i in listar(True)}
    n = 1
    while f"{prefixo}{n:02d}" in usados:
        n += 1
    return f"{prefixo}{n:02d}"


def salvar_tabela(itens: list[dict]) -> int:
    """Grava a tabela inteira vinda do painel. Itens que sumiram da lista ficam inativos (orçamentos antigos não quebram)."""
    if not any(" ".join(str(i.get("servico") or "").split()) for i in itens):
        raise ValueError("a tabela não pode ficar vazia")
    vistos = set()
    with db.conectar() as con:
        for k, it in enumerate(itens):
            servico = " ".join(str(it.get("servico") or "").split())[:200]
            if not servico:
                continue
            cod = str(it.get("codigo") or "").strip().upper()[:8]
            if not cod or cod in vistos:
                cod = novo_codigo(servico[:1])
                while cod in vistos:
                    cod = cod[0] + f"{int(cod[1:]) + 1:02d}"
            vistos.add(cod)
            con.execute("""INSERT INTO catalogo (codigo, servico, unidade, mao_de_obra, material, palavras_chave, site, ativo, ordem)
                           VALUES (?,?,?,?,?,?,?,1,?)
                           ON CONFLICT(codigo) DO UPDATE SET servico=excluded.servico, unidade=excluded.unidade,
                             mao_de_obra=excluded.mao_de_obra, material=excluded.material, palavras_chave=excluded.palavras_chave,
                             site=excluded.site, ativo=1, ordem=excluded.ordem""",
                        (cod, servico, (str(it.get("unidade") or "un").strip() or "un")[:10],
                         max(0.0, round(float(it.get("mao_de_obra") or 0), 2)), max(0.0, round(float(it.get("material") or 0), 2)),
                         " ".join(str(it.get("palavras_chave") or "").split())[:300], 1 if it.get("site") else 0, k))
        marcas = ",".join("?" * len(vistos)) or "''"
        con.execute(f"UPDATE catalogo SET ativo = 0 WHERE codigo NOT IN ({marcas})", tuple(vistos))
    return len(vistos)


def alterar_preco(codigo, mao_de_obra=None, material=None, preco_total=None, site=None) -> dict | None:
    it = item(codigo)
    if not it:
        return None
    mo, mat = it["mao_de_obra"], it["material"]
    if material is not None:
        mat = float(material)
    if mao_de_obra is not None:
        mo = float(mao_de_obra)
    if preco_total is not None and mao_de_obra is None:
        mo = max(0.0, float(preco_total) - mat)        # mantém o material e ajusta a mão de obra
    with db.conectar() as con:
        con.execute("UPDATE catalogo SET mao_de_obra = ?, material = ?, site = COALESCE(?, site) WHERE codigo = ?",
                    (round(mo, 2), round(mat, 2), None if site is None else int(bool(site)), it["codigo"]))
    return item(codigo)
