"""Controle financeiro: períodos, resumos em texto e relatório em Excel."""
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from . import config, db
from .orcamento_pdf import brl

CATEGORIAS = {"material": "material", "mao_de_obra": "mão de obra", "ferramentas": "ferramentas", "transporte": "transporte",
              "alimentacao": "alimentação", "aluguel_equipamento": "aluguel de equipamento", "impostos_taxas": "impostos e taxas",
              "pagamento_cliente": "pagamento de cliente", "outros": "outros"}


def rotulo_categoria(c):
    return CATEGORIAS.get(c or "", (c or "").replace("_", " "))


MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def periodo(nome: str, inicio: str = None, fim: str = None):
    """Converte 'hoje', 'semana', 'mes', 'mes_anterior', 'ano', 'tudo' ou datas em (inicio, fim, rótulo)."""
    hoje = config.hoje()
    nome = (nome or "mes").lower()
    if inicio or fim:
        i = inicio or "2000-01-01"; f = fim or hoje.isoformat()
        return i, f, f"de {date.fromisoformat(i):%d/%m/%Y} a {date.fromisoformat(f):%d/%m/%Y}"
    if nome == "hoje":
        return hoje.isoformat(), hoje.isoformat(), "hoje"
    if nome == "semana":
        i = hoje - timedelta(days=hoje.weekday())
        return i.isoformat(), hoje.isoformat(), "nesta semana"
    if nome == "mes_anterior":
        y, m = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
        return date(y, m, 1).isoformat(), date(y, m, monthrange(y, m)[1]).isoformat(), f"em {MESES[m - 1]}/{y}"
    if nome == "ano":
        return date(hoje.year, 1, 1).isoformat(), hoje.isoformat(), f"em {hoje.year}"
    if nome == "tudo":
        return "2000-01-01", "2999-12-31", "no total"
    return date(hoje.year, hoje.month, 1).isoformat(), date(hoje.year, hoje.month, monthrange(hoje.year, hoje.month)[1]).isoformat(), \
        f"em {MESES[hoje.month - 1]}/{hoje.year}"


def resumo(inicio, fim, rotulo, obra=None, detalhado=False):
    ls = db.lancamentos(inicio, fim, obra)
    if not ls:
        return f"Não há lançamentos {rotulo}" + (f" na obra {obra}." if obra else ".")
    ent = sum(l["valor"] for l in ls if l["tipo"] == "receita")
    sai = sum(l["valor"] for l in ls if l["tipo"] == "despesa")
    por_cat = defaultdict(float)
    por_obra = defaultdict(lambda: [0.0, 0.0])
    for l in ls:
        if l["tipo"] == "despesa":
            por_cat[l["categoria"] or "outros"] += l["valor"]
        por_obra[l["obra"] or "sem obra"][0 if l["tipo"] == "receita" else 1] += l["valor"]
    titulo = f"📊 Resumo {rotulo}" + (f" – obra {obra}" if obra else "")
    linhas = [titulo, f"Entradas: {brl(ent)}", f"Saídas: {brl(sai)}", f"*Saldo: {brl(ent - sai)}*"]
    if por_cat:
        linhas.append("")
        linhas.append("Gastos por categoria:")
        for c, v in sorted(por_cat.items(), key=lambda x: -x[1]):
            linhas.append(f"• {rotulo_categoria(c)}: {brl(v)}")
    if not obra and len(por_obra) > 1:
        linhas.append("")
        linhas.append("Por obra (entrou / saiu):")
        for o, (e, s) in sorted(por_obra.items(), key=lambda x: -(x[1][0] + x[1][1])):
            linhas.append(f"• {o}: {brl(e)} / {brl(s)}")
    if detalhado:
        linhas.append("")
        linhas.append("Últimos lançamentos:")
        for l in ls[-10:]:
            sinal = "+" if l["tipo"] == "receita" else "–"
            linhas.append(f"{date.fromisoformat(l['data']):%d/%m} {sinal}{brl(l['valor'])} {l['descricao'] or l['categoria'] or ''} ({l['obra'] or 'sem obra'})")
    return "\n".join(linhas)


def relatorio_excel(inicio, fim, rotulo, destino: Path, obra=None) -> Path:
    ls = db.lancamentos(inicio, fim, obra)
    wb = Workbook()
    ws = wb.active; ws.title = "Lançamentos"
    navy = PatternFill("solid", fgColor="0A1F5C")
    cab = ["Data", "Tipo", "Valor (R$)", "Categoria", "Obra / cliente", "Forma de pagamento", "Descrição"]
    ws.append([f"{config.NOME_ASSISTENTE} – lançamentos {rotulo}" + (f" – obra {obra}" if obra else "")])
    ws["A1"].font = Font(bold=True, size=13, color="0A1F5C")
    ws.append([])
    ws.append(cab)
    for c in ws[3]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = navy; c.alignment = Alignment(horizontal="center")
    for l in ls:
        ws.append([date.fromisoformat(l["data"]), l["tipo"], l["valor"] if l["tipo"] == "receita" else -l["valor"],
                   rotulo_categoria(l["categoria"]), l["obra"], l["forma_pagamento"], l["descricao"]])
    for row in ws.iter_rows(min_row=4, min_col=1, max_col=3):
        row[0].number_format = "DD/MM/YYYY"
        row[2].number_format = '[$-416]"R$ "#,##0.00;[Red]-"R$ "#,##0.00'
    for col, w in zip("ABCDEFG", [12, 10, 15, 16, 24, 18, 40]):
        ws.column_dimensions[col].width = w
    n = ws.max_row
    ws.append([])
    ws.append(["", "Saldo", f"=SUM(C4:C{n})"])
    ws.cell(ws.max_row, 3).number_format = '[$-416]"R$ "#,##0.00;[Red]-"R$ "#,##0.00'
    ws.cell(ws.max_row, 2).font = Font(bold=True); ws.cell(ws.max_row, 3).font = Font(bold=True)
    # resumo por obra
    r = wb.create_sheet("Resumo por obra")
    r.append(["Obra / cliente", "Entradas (R$)", "Saídas (R$)", "Saldo (R$)"])
    for c in r[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = navy
    por = defaultdict(lambda: [0.0, 0.0])
    for l in ls:
        por[l["obra"] or "sem obra"][0 if l["tipo"] == "receita" else 1] += l["valor"]
    for o, (e, s) in sorted(por.items()):
        r.append([o, e, s, e - s])
    for row in r.iter_rows(min_row=2, min_col=2, max_col=4):
        for c in row:
            c.number_format = '[$-416]"R$ "#,##0.00;[Red]-"R$ "#,##0.00'
    for col, w in zip("ABCD", [28, 16, 16, 16]):
        r.column_dimensions[col].width = w
    moeda = '[$-416]"R$ "#,##0.00;[Red]-"R$ "#,##0.00'
    # lucro por obra (todo o período da obra, não só o do relatório)
    ob = wb.create_sheet("Lucro por obra")
    ob.append(["Obra", "Situação", "Contratado", "Recebido", "Falta receber", "Gasto", "Custo previsto", "% do previsto",
               "Lucro até agora", "Lucro previsto"])
    for c in ob[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = navy; c.alignment = Alignment(wrap_text=True, horizontal="center")
    for nome in db.obras_conhecidas():
        if obra and obra.lower() not in nome.lower():
            continue
        o = situacao_obra(nome)
        ob.append([o["nome"], STATUS_TXT[o["status"]] if o["situacao"] != "concluida" else "concluída",
                   o["contratado"] or None, o["recebido"], o["falta_receber"] or None, o["gasto"], o["previsto"] or None,
                   (o["pct_gasto"] / 100) if o["pct_gasto"] is not None else None, o["lucro_atual"], o["lucro_previsto"]])
    for row in ob.iter_rows(min_row=2):
        for k, c in enumerate(row):
            c.number_format = "0%" if k == 7 else moeda if k >= 2 else "General"
    for col, w in zip("ABCDEFGHIJ", [24, 22, 14, 14, 14, 14, 14, 11, 15, 15]):
        ob.column_dimensions[col].width = w
    # contas em aberto
    ct = wb.create_sheet("Contas em aberto")
    ct.append(["Nº", "Tipo", "Vencimento", "Valor", "Descrição", "Obra"])
    for c in ct[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = navy
    for c in db.contas_abertas(obra=obra):
        ct.append([c["id"], "a pagar" if c["tipo"] == "pagar" else "a receber", date.fromisoformat(c["vencimento"]),
                   c["valor"], c["descricao"], c["obra"]])
    for row in ct.iter_rows(min_row=2):
        row[2].number_format = "DD/MM/YYYY"; row[3].number_format = moeda
    for col, w in zip("ABCDEF", [6, 11, 12, 14, 36, 22]):
        ct.column_dimensions[col].width = w
    wb.save(destino)
    return destino


# ================================================================== obras: lucro e alerta de estouro
def situacao_obra(nome):
    """Números de uma obra: contratado, recebido, gasto, previsto, lucro atual e previsto."""
    reg = db.obter_obra(nome) or {}
    nome = reg.get("nome") or nome
    ls = db.lancamentos("2000-01-01", "2999-12-31", nome)
    recebido = sum(l["valor"] for l in ls if l["tipo"] == "receita")
    gasto = sum(l["valor"] for l in ls if l["tipo"] == "despesa")
    contas = db.contas_abertas(obra=nome)
    a_receber = sum(c["valor"] for c in contas if c["tipo"] == "receber")
    a_pagar = sum(c["valor"] for c in contas if c["tipo"] == "pagar")
    contratado = float(reg.get("valor_contratado") or 0)
    previsto = float(reg.get("custo_previsto") or 0)
    pct = gasto / previsto * 100 if previsto else None
    if pct is None:
        status = "sem_previsto"
    elif pct > 100:
        status = "estourado"
    elif pct >= config.ALERTA_PCT:
        status = "atencao"
    else:
        status = "ok"
    custo_final = max(previsto, gasto + a_pagar) if previsto else gasto + a_pagar
    return {
        "nome": nome, "cliente": reg.get("cliente"), "orcamento_id": reg.get("orcamento_id"),
        "situacao": reg.get("situacao") or "andamento", "registrada": bool(reg),
        "contratado": contratado, "recebido": recebido, "falta_receber": max(contratado - recebido, 0),
        "a_receber_agendado": a_receber, "a_pagar_agendado": a_pagar,
        "gasto": gasto, "previsto": previsto, "pct_gasto": pct, "status": status,
        "lucro_atual": recebido - gasto,
        "lucro_previsto": (contratado - custo_final) if contratado else None,
        "margem_prevista": ((contratado - custo_final) / contratado * 100) if contratado else None,
    }


STATUS_TXT = {"ok": "✅ dentro do previsto", "atencao": "⚠️ atenção", "estourado": "🚨 ESTOURADO", "sem_previsto": "custo previsto não definido"}


def texto_obra(s):
    linhas = [f"🏗️ *Obra {s['nome']}*" + (" (concluída)" if s["situacao"] == "concluida" else "")]
    if s["contratado"]:
        linhas.append(f"Contratado: {brl(s['contratado'])}" + (f" (orçamento nº {s['orcamento_id']:04d})" if s["orcamento_id"] else ""))
    linhas.append(f"Recebido: {brl(s['recebido'])}" + (f" • falta receber {brl(s['falta_receber'])}" if s["contratado"] else ""))
    if s["previsto"]:
        linhas.append(f"Gasto: {brl(s['gasto'])} de {brl(s['previsto'])} previstos ({s['pct_gasto']:.0f}%) – {STATUS_TXT[s['status']]}")
    else:
        linhas.append(f"Gasto: {brl(s['gasto'])}")
    if s["a_pagar_agendado"]:
        linhas.append(f"Contas a pagar agendadas: {brl(s['a_pagar_agendado'])}")
    linhas.append(f"*Lucro até agora: {brl(s['lucro_atual'])}*")
    if s["lucro_previsto"] is not None:
        linhas.append(f"Lucro previsto no fim: {brl(s['lucro_previsto'])} ({s['margem_prevista']:.0f}% do contratado)")
    if not s["registrada"] or not s["previsto"]:
        linhas.append("Dica: diga \"o custo previsto da obra " + s["nome"] + " é X\" para eu avisar se o gasto passar do previsto.")
    return "\n".join(linhas)


def texto_obras():
    obras = [situacao_obra(n) for n in db.obras_conhecidas()]
    obras = [o for o in obras if o["situacao"] != "concluida"]
    if not obras:
        return "Ainda não há obras. Quando aprovar um orçamento, diga \"o orçamento 3 foi aprovado\"."
    linhas = ["🏗️ *Obras em andamento*"]
    for o in sorted(obras, key=lambda x: -(x["contratado"] or x["gasto"])):
        partes = [f"recebido {brl(o['recebido'])}", f"gasto {brl(o['gasto'])}"]
        if o["previsto"]:
            partes[-1] += f" ({o['pct_gasto']:.0f}% do previsto)"
        partes.append(f"lucro {brl(o['lucro_atual'])}")
        icone = {"estourado": "🚨 ", "atencao": "⚠️ "}.get(o["status"], "")
        linhas.append(f"• {icone}{o['nome']}: " + ", ".join(partes))
    return "\n".join(linhas)


def alerta_obra(nome):
    """Linha de alerta quando o gasto da obra passou do limite (usada logo após lançar um gasto)."""
    if not nome:
        return ""
    s = situacao_obra(nome)
    if s["status"] == "estourado":
        return (f"\n🚨 *Atenção: a obra {s['nome']} passou do custo previsto!* Gasto {brl(s['gasto'])} de "
                f"{brl(s['previsto'])} ({s['pct_gasto']:.0f}%). Lucro previsto agora: {brl(s['lucro_previsto'] or 0)}.")
    if s["status"] == "atencao":
        return (f"\n⚠️ A obra {s['nome']} já usou {s['pct_gasto']:.0f}% do custo previsto "
                f"({brl(s['gasto'])} de {brl(s['previsto'])}).")
    return ""


# ================================================================== contas a pagar / receber
def _dia(d):
    d = date.fromisoformat(d)
    dif = (d - config.hoje()).days
    rel = "hoje" if dif == 0 else "amanhã" if dif == 1 else f"venceu há {-dif} dia(s)" if dif < 0 else f"em {dif} dias"
    return f"{d:%d/%m} ({rel})"


def linha_conta(c):
    icone = "🔴 Pagar" if c["tipo"] == "pagar" else "🟢 Receber"
    return (f"#{c['id']} {icone} {brl(c['valor'])} – {c['descricao'] or rotulo_categoria(c['categoria'])}"
            f"{' – obra ' + c['obra'] if c['obra'] else ''} – {_dia(c['vencimento'])}")


def texto_contas(filtro="proximas", dias=30, tipo=None):
    hoje = config.hoje()
    if filtro == "vencidas":
        cs = [c for c in db.contas_abertas(ate=(hoje - timedelta(days=1)).isoformat(), tipo=tipo)]
        titulo = "⏰ *Contas vencidas*"
    elif filtro == "todas":
        cs = db.contas_abertas(tipo=tipo)
        titulo = "📋 *Todas as contas em aberto*"
    else:
        cs = db.contas_abertas(ate=(hoje + timedelta(days=dias)).isoformat(), tipo=tipo)
        titulo = f"📅 *Contas até {(hoje + timedelta(days=dias)):%d/%m}* (inclui vencidas)"
    if not cs:
        return "Nenhuma conta em aberto nesse período. 👍"
    pagar = sum(c["valor"] for c in cs if c["tipo"] == "pagar")
    receber = sum(c["valor"] for c in cs if c["tipo"] == "receber")
    linhas = [titulo] + [linha_conta(c) for c in cs[:40]]
    if len(cs) > 40:
        linhas.append(f"… e mais {len(cs) - 40}.")
    linhas.append(f"Total a pagar: {brl(pagar)} • a receber: {brl(receber)}")
    linhas.append("Quando pagar/receber, diga \"paguei a conta 12\" ou \"recebi a parcela da Maria\".")
    return "\n".join(linhas)


def lembrete():
    """Resumo das contas vencidas, de hoje e dos próximos 3 dias + obras estouradas.
    Devolve (texto completo, linha curta para modelo da Meta) ou (None, None) se não houver nada."""
    hoje = config.hoje()
    cs = db.contas_abertas(ate=(hoje + timedelta(days=3)).isoformat())
    estouradas = [s for s in (situacao_obra(n) for n in db.obras_conhecidas())
                  if s["status"] == "estourado" and s["situacao"] != "concluida"]
    if not cs and not estouradas:
        return None, None
    venc = [c for c in cs if c["vencimento"] < hoje.isoformat()]
    hj = [c for c in cs if c["vencimento"] == hoje.isoformat()]
    prox = [c for c in cs if c["vencimento"] > hoje.isoformat()]
    linhas = [f"📌 *Lembrete – {hoje:%d/%m}*"]
    for rot, grupo in (("Vencidas", venc), ("Vencem hoje", hj), ("Próximos 3 dias", prox)):
        if grupo:
            linhas.append(f"\n*{rot}:*")
            linhas += [linha_conta(c) for c in grupo]
    if estouradas:
        linhas.append("\n*Obras acima do custo previsto:*")
        linhas += [f"🚨 {s['nome']}: gasto {brl(s['gasto'])} de {brl(s['previsto'])} ({s['pct_gasto']:.0f}%)" for s in estouradas]
    linhas.append("\nDiga \"paguei a conta N\" quando quitar.")
    partes = []
    if venc:
        partes.append(f"{len(venc)} vencida(s) ({brl(sum(c['valor'] for c in venc))})")
    if hj:
        partes.append(f"{len(hj)} vence(m) hoje ({brl(sum(c['valor'] for c in hj))})")
    if prox:
        partes.append(f"{len(prox)} nos próximos 3 dias")
    if estouradas:
        partes.append(f"{len(estouradas)} obra(s) acima do previsto")
    return "\n".join(linhas), "; ".join(partes)


# ================================================================== dados para o painel
def dados_painel(nome_periodo="mes"):
    i, f, rot = periodo(nome_periodo)
    hoje = config.hoje()
    ls = db.lancamentos(i, f)
    ent = sum(l["valor"] for l in ls if l["tipo"] == "receita")
    sai = sum(l["valor"] for l in ls if l["tipo"] == "despesa")
    por_cat = defaultdict(float)
    for l in ls:
        if l["tipo"] == "despesa":
            por_cat[(l["categoria"] or "outros").replace("_", " ")] += l["valor"]
    # últimos 6 meses
    meses = []
    y, m = hoje.year, hoje.month
    for _ in range(6):
        meses.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    meses.reverse()
    serie = []
    for y, m in meses:
        lm = db.lancamentos(date(y, m, 1).isoformat(), date(y, m, monthrange(y, m)[1]).isoformat())
        serie.append({"rotulo": f"{MESES[m - 1][:3]}/{str(y)[2:]}",
                      "entradas": sum(l["valor"] for l in lm if l["tipo"] == "receita"),
                      "saidas": sum(l["valor"] for l in lm if l["tipo"] == "despesa")})
    abertas = db.contas_abertas()
    vencidas = [c for c in abertas if c["vencimento"] < hoje.isoformat()]
    proximas = [c for c in abertas if c["vencimento"] >= hoje.isoformat()]
    obras = [situacao_obra(n) for n in db.obras_conhecidas()]
    obras.sort(key=lambda o: (o["situacao"] == "concluida", -(o["contratado"] or o["gasto"])))
    for c in abertas:
        c["quando"] = _dia(c["vencimento"])
    return {
        "periodo": nome_periodo, "rotulo": rot, "entradas": ent, "saidas": sai, "saldo": ent - sai,
        "categorias": sorted(por_cat.items(), key=lambda x: -x[1]),
        "meses": serie,
        "a_receber": sum(c["valor"] for c in abertas if c["tipo"] == "receber"),
        "a_pagar": sum(c["valor"] for c in abertas if c["tipo"] == "pagar"),
        "vencidas": vencidas, "proximas": proximas[:15],
        "obras": obras,
        "ultimos": list(reversed(ls))[:12],
    }
