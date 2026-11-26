"""Gera o PDF do orçamento com o logo e os dados da empresa."""
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import config

NAVY = colors.HexColor(config.COR_PRINCIPAL)     # títulos e cabeçalho da tabela
BLUE = colors.HexColor(config.COR_DESTAQUE)      # linhas e detalhes
_c = colors.HexColor(config.COR_DESTAQUE)
LIGHT = colors.Color(0.82 + 0.18 * _c.red, 0.82 + 0.18 * _c.green, 0.82 + 0.18 * _c.blue)   # tom claro da cor de destaque
ZEBRA = colors.HexColor("#F2F5F9")


def brl(v):
    txt = "R$ " + f"{abs(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "−" + txt if (v or 0) < -0.004 else txt


def qtd(v):
    return (f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")).rstrip("0").rstrip(",")


def _estilos():
    base = dict(fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#111111"))
    return {
        "titulo": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=NAVY),
        "sub": ParagraphStyle("s", fontName="Helvetica", fontSize=9.5, leading=13, textColor=colors.HexColor("#444444")),
        "cel": ParagraphStyle("c", **base),
        "celb": ParagraphStyle("cb", **{**base, "fontName": "Helvetica-Bold"}),
        "celr": ParagraphStyle("cr", **base, alignment=TA_RIGHT),
        "head": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white),
        "headr": ParagraphStyle("hr", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white, alignment=TA_RIGHT),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=BLUE, spaceBefore=8, spaceAfter=3),
        "txt": ParagraphStyle("x", fontName="Helvetica", fontSize=9.5, leading=13, alignment=TA_LEFT),
    }


def _rodape(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(BLUE); canvas.setLineWidth(1.2)
    canvas.line(18 * mm, 16 * mm, w - 18 * mm, 16 * mm)
    canvas.setFont("Helvetica-Bold", 8.5); canvas.setFillColor(NAVY)
    canvas.drawCentredString(w / 2, 11.5 * mm, config.EMPRESA)
    canvas.setFont("Helvetica", 8); canvas.setFillColor(colors.HexColor("#444444"))
    partes = [f"CNPJ {config.CNPJ}" if config.CNPJ else "", f"WhatsApp {config.TELEFONE}" if config.TELEFONE else "",
              config.EMAIL, f"Instagram {config.INSTAGRAM}" if config.INSTAGRAM else ""]
    canvas.drawCentredString(w / 2, 7.5 * mm, "  |  ".join(p for p in partes if p))
    canvas.drawRightString(w - 18 * mm, 7.5 * mm, f"Página {doc.page}")
    canvas.restoreState()


def _sup(t):
    """A fonte padrão do PDF não desenha os caracteres ² e ³: escreve como expoente."""
    return (t or "").replace("²", "<super>2</super>").replace("³", "<super>3</super>")


def gerar(orc: dict, destino: Path) -> Path:
    """orc: {id, cliente, endereco, itens:[{codigo, descricao, unidade, quantidade, preco_unitario}], desconto_pct, observacoes, total}"""
    E = _estilos()
    doc = SimpleDocTemplate(str(destino), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=14 * mm, bottomMargin=22 * mm, title=f"Orçamento {orc['id']:04d}",
                            author=config.EMPRESA)
    hoje = config.hoje()
    story = []
    # cabeçalho: logo + título
    if Path(config.LOGO).exists():
        from PIL import Image as PILImage
        lw, lh = PILImage.open(config.LOGO).size
        logo = Image(str(config.LOGO), width=34 * mm, height=34 * mm * lh / lw)
    else:
        logo = Spacer(1, 1)
    cab = Table([[logo, [Paragraph(f"ORÇAMENTO Nº {orc['id']:04d}", E["titulo"]),
                         Paragraph(f"Data: {hoje:%d/%m/%Y}  •  Validade: {(hoje + timedelta(days=config.VALIDADE_DIAS)):%d/%m/%Y}", E["sub"])]]],
                colWidths=[42 * mm, None])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [cab, Spacer(1, 4 * mm)]
    # cliente
    cli = [[Paragraph("Cliente", E["celb"]), Paragraph(orc.get("cliente") or "–", E["cel"])]]
    if orc.get("endereco"):
        cli.append([Paragraph("Endereço da obra", E["celb"]), Paragraph(orc["endereco"], E["cel"])])
    tcli = Table(cli, colWidths=[38 * mm, None])
    tcli.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), ZEBRA), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8C4D6")),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [tcli, Spacer(1, 5 * mm)]
    # itens
    linhas = [[Paragraph("Item", E["head"]), Paragraph("Serviço", E["head"]), Paragraph("Quant.", E["headr"]),
               Paragraph("Un.", E["head"]), Paragraph("Valor unit.", E["headr"]), Paragraph("Total", E["headr"])]]
    subtotal = 0.0
    for k, it in enumerate(orc["itens"], 1):
        tot = round(it["quantidade"] * it["preco_unitario"], 2)
        subtotal += tot
        desc = _sup(it["descricao"]) + (f"<br/><font size=7.5 color='#555555'>{_sup(it['observacao'])}</font>" if it.get("observacao") else "")
        linhas.append([Paragraph(str(k), E["cel"]), Paragraph(desc, E["cel"]), Paragraph(qtd(it["quantidade"]), E["celr"]),
                       Paragraph(_sup(it.get("unidade")), E["cel"]), Paragraph(brl(it["preco_unitario"]), E["celr"]),
                       Paragraph(brl(tot), E["celr"])])
    subtotal = round(subtotal, 2)
    desc_pct = float(orc.get("desconto_pct") or 0)
    desconto = round(subtotal * desc_pct / 100, 2)
    total = round(subtotal - desconto, 2)
    n_itens = len(linhas)
    if desconto:
        linhas.append(["", Paragraph("Subtotal", E["celb"]), "", "", "", Paragraph(brl(subtotal), E["celr"])])
        linhas.append(["", Paragraph(f"Desconto ({qtd(desc_pct)}%)", E["celb"]), "", "", "", Paragraph("– " + brl(desconto), E["celr"])])
    linhas.append(["", Paragraph("<b>VALOR TOTAL</b>", E["cel"]), "", "", "", Paragraph(f"<b>{brl(total)}</b>", E["celr"])])
    t = Table(linhas, colWidths=[11 * mm, None, 17 * mm, 11 * mm, 26 * mm, 28 * mm], repeatRows=1)
    st = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8C4D6")),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (0, len(linhas) - 1), (-1, len(linhas) - 1), LIGHT),
          ("SPAN", (1, len(linhas) - 1), (4, len(linhas) - 1))]
    for r in range(2, n_itens, 2):
        st.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
    for r in range(n_itens, len(linhas) - 1):
        st.append(("SPAN", (1, r), (4, r)))
    t.setStyle(TableStyle(st))
    story += [t, Spacer(1, 5 * mm)]
    story.append(Paragraph("Condições", E["h2"]))
    cond = [f"Forma de pagamento: {config.CONDICOES_PAGAMENTO}",
            f"Orçamento válido por {config.VALIDADE_DIAS} dias. Valores de mão de obra e material incluídos, salvo indicação.",
            "Quantidades estimadas, sujeitas à conferência das medidas na obra."]
    if orc.get("observacoes"):
        cond.insert(0, f"Observações: {orc['observacoes']}")
    for c in cond:
        story.append(Paragraph("• " + _sup(c), E["txt"]))
    story += [Spacer(1, 6 * mm),
              Paragraph(f"<b>{config.EMPRESA}</b><br/>WhatsApp {config.TELEFONE}", E["txt"])]
    doc.build(story, onFirstPage=_rodape, onLaterPages=_rodape)
    return destino
