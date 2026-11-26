"""Painel financeiro no navegador (abre no celular pelo link que o assistente manda)."""
import json
import secrets
from datetime import date
from html import escape

from datetime import timedelta

from . import config, db, financeiro, telas, visitas
from .orcamento_pdf import brl

PERIODOS = [("mes", "Este mês"), ("mes_anterior", "Mês anterior"), ("ano", "Este ano"), ("tudo", "Tudo")]
CATEGORIAS = {"material": "Material", "mao_de_obra": "Mão de obra", "ferramentas": "Ferramentas", "transporte": "Transporte",
              "alimentacao": "Alimentação", "aluguel_equipamento": "Aluguel de equipamento", "impostos_taxas": "Impostos e taxas",
              "pagamento_cliente": "Pagamento de cliente", "outros": "Outros"}
STATUS = {"ok": ("good", "✓", "Dentro do previsto"), "atencao": ("warning", "!", "Atenção"),
          "estourado": ("critical", "✕", "Acima do previsto"), "sem_previsto": ("muted", "–", "Sem custo previsto")}


def senha_painel() -> str:
    if config.PAINEL_SENHA:
        return config.PAINEL_SENHA
    s = db.ajuste("painel_senha")
    if not s:
        s = secrets.token_urlsafe(18)
        db.gravar_ajuste("painel_senha", s)
    return s


def _e(x):
    return escape(str(x or ""))


def _kpi(rotulo, valor, nota="", classe=""):
    return (f'<div class="kpi {classe}"><div class="kpi-l">{rotulo}</div><div class="kpi-v">{valor}</div>'
            f'<div class="kpi-n">{nota}</div></div>')


def _obra(o):
    cls, icone, rot = STATUS[o["status"]]
    pct = o["pct_gasto"]
    barra = ""
    if pct is not None:
        largura = min(pct, 100)
        barra = (f'<div class="meter" role="img" aria-label="Gasto {pct:.0f}% do previsto">'
                 f'<div class="meter-fill s-{cls}" style="width:{largura:.1f}%"></div></div>'
                 f'<div class="meter-cap"><span>Gasto {brl(o["gasto"])} de {brl(o["previsto"])}</span><b>{pct:.0f}%</b></div>')
    lucro_prev = brl(o["lucro_previsto"]) + f' <small>({o["margem_prevista"]:.0f}%)</small>' if o["lucro_previsto"] is not None else "—"
    concluida = ' <span class="tag">concluída</span>' if o["situacao"] == "concluida" else ""
    return f'''<article class="obra">
  <header><h3>{_e(o["nome"])}{concluida}</h3>
    <span class="status s-{cls}"><i>{icone}</i>{rot}</span></header>
  {barra}
  <dl>
    <div><dt>Contratado</dt><dd>{brl(o["contratado"]) if o["contratado"] else "—"}</dd></div>
    <div><dt>Recebido</dt><dd>{brl(o["recebido"])}</dd></div>
    <div><dt>Gasto</dt><dd>{brl(o["gasto"])}</dd></div>
    <div><dt>Falta receber</dt><dd>{brl(o["falta_receber"]) if o["contratado"] else "—"}</dd></div>
    <div><dt>Lucro até agora</dt><dd class="{"neg" if o["lucro_atual"] < 0 else ""}">{brl(o["lucro_atual"])}</dd></div>
    <div><dt>Lucro previsto</dt><dd>{lucro_prev}</dd></div>
  </dl>
</article>'''


def _conta(c, vencida=False):
    tipo = "Pagar" if c["tipo"] == "pagar" else "Receber"
    return (f'<li class="{"venc" if vencida else ""}"><span class="ct-tipo t-{c["tipo"]}">{tipo}</span>'
            f'<span class="ct-desc">{_e(c["descricao"] or CATEGORIAS.get(c["categoria"], ""))}'
            f'<small>#{c["id"]}{" · " + _e(c["obra"]) if c["obra"] else ""} · {_e(c["quando"])}</small></span>'
            f'<span class="ct-v">{brl(c["valor"])}</span></li>')


def pagina(k: str, periodo: str = "mes") -> str:
    if periodo not in dict(PERIODOS):
        periodo = "mes"
    d = financeiro.dados_painel(periodo)
    abas = "".join(f'<a href="?k={_e(k)}&p={p}" class="{"on" if p == periodo else ""}">{r}</a>' for p, r in PERIODOS)
    kpis = "".join([
        _kpi("Entradas", brl(d["entradas"]), d["rotulo"]),
        _kpi("Saídas", brl(d["saidas"]), d["rotulo"]),
        _kpi("Saldo", brl(d["saldo"]), d["rotulo"], "neg" if d["saldo"] < 0 else "pos"),
        _kpi("A receber", brl(d["a_receber"]), "contas em aberto"),
        _kpi("A pagar", brl(d["a_pagar"]), "contas em aberto"),
        _kpi("Vencidas", str(len(d["vencidas"])),
             brl(sum(c["valor"] for c in d["vencidas"])) if d["vencidas"] else "nenhuma 👍",
             "alerta" if d["vencidas"] else ""),
    ])
    obras_and = [o for o in d["obras"] if o["situacao"] != "concluida"]
    obras_html = "".join(_obra(o) for o in obras_and) or '<p class="vazio">Nenhuma obra em andamento. Diga no WhatsApp: "o orçamento 3 foi aprovado".</p>'
    estouradas = [o for o in obras_and if o["status"] == "estourado"]
    alerta_obras = ""
    if estouradas:
        alerta_obras = ('<div class="banner"><span class="status s-critical"><i>✕</i>Alerta</span> '
                        + ", ".join(_e(o["nome"]) for o in estouradas)
                        + (" passou" if len(estouradas) == 1 else " passaram") + " do custo previsto.</div>")
    contas_html = ""
    if d["vencidas"]:
        contas_html += '<h3 class="sub">Vencidas</h3><ul class="contas">' + "".join(_conta(c, True) for c in d["vencidas"]) + "</ul>"
    contas_html += ('<h3 class="sub">Próximas</h3><ul class="contas">' + "".join(_conta(c) for c in d["proximas"]) + "</ul>"
                    if d["proximas"] else '<p class="vazio">Nenhuma conta agendada.</p>')
    h0 = config.hoje()
    vs = visitas.listar(h0, h0 + timedelta(days=30))
    bls = visitas.bloqueios(h0, h0 + timedelta(days=30))
    itens_ag = [(v["data"], v["hora"], f'<li><span class="ct-tipo {"t-receber" if v["situacao"] == "confirmada" else "t-pend"}">'
                 f'{"Confirmada" if v["situacao"] == "confirmada" else "Aguardando"}</span><span class="ct-desc">{_e(v["nome"])} · {_e(v["servico"] or "-")}'
                 f'<small>nº {v["id"]} · {_e(v["telefone"] or "")}{" · " + _e(v["endereco"]) if v["endereco"] else ""}</small></span>'
                 f'<span class="ct-v">{date.fromisoformat(v["data"]):%d/%m} {v["hora"]}</span></li>') for v in vs]
    itens_ag += [(b["data"], b["hora"] or "", f'<li><span class="ct-tipo">Bloqueado</span><span class="ct-desc">{_e(b["motivo"] or "Sem visitas")}'
                 f'<small>{"dia todo" if not b["hora"] else b["hora"]}</small></span><span class="ct-v">{date.fromisoformat(b["data"]):%d/%m}</span></li>')
                 for b in bls]
    agenda_html = ('<ul class="contas">' + "".join(x[2] for x in sorted(itens_ag)) + "</ul>") if itens_ag else \
        '<p class="vazio">Nenhuma visita nos próximos 30 dias. Os pedidos do site aparecem aqui.</p>'
    ultimos = "".join(
        f'<tr><td>{date.fromisoformat(l["data"]):%d/%m}</td><td>{_e(l["descricao"] or CATEGORIAS.get(l["categoria"], l["categoria"]))}'
        f'<small>{_e(l["obra"] or "")}</small></td>'
        f'<td class="num {"in" if l["tipo"] == "receita" else "out"}">{"+" if l["tipo"] == "receita" else "−"}{brl(l["valor"])}</td></tr>'
        for l in d["ultimos"]) or '<tr><td colspan="3" class="vazio">Sem lançamentos no período.</td></tr>'
    tabela_meses = "".join(f'<tr><td>{m["rotulo"]}</td><td class="num">{brl(m["entradas"])}</td><td class="num">{brl(m["saidas"])}</td></tr>'
                           for m in d["meses"])
    cats = [(CATEGORIAS.get(c.replace(" ", "_"), c.capitalize()), v) for c, v in d["categorias"]]
    tabela_cats = "".join(f'<tr><td>{_e(c)}</td><td class="num">{brl(v)}</td></tr>' for c, v in cats) or \
        '<tr><td colspan="2" class="vazio">Sem gastos no período.</td></tr>'
    dados_js = json.dumps({"meses": d["meses"], "cats": cats}, ensure_ascii=False).replace("</", "<\\/")
    logo = f'<img src="/painel/logo?k={_e(k)}" alt="" class="logo">' if config.LOGO.exists() else ""
    atualizado = config.agora().strftime("%d/%m/%Y %H:%M")

    return f'''<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Painel – {_e(config.NOME_ASSISTENTE)}</title>
<style>
:root {{
  color-scheme: light;
  --brand: {config.COR_PRINCIPAL};
  --bg: #f3f3f1; --surface-1: #fcfcfb; --border: #e3e2de;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #7a7974;
  --grid: #ebeae6;
  --series-1: #2a78d6; --series-2: #eb6834;
  --good: #0ca30c; --warning: #fab219; --critical: #d03b3b;
  --good-text: #006300; --critical-text: #b02a2a; --warning-text: #8a5a00;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
    --bg: #111110; --surface-1: #1a1a19; --border: #2e2e2b;
    --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #8f8e86;
    --grid: #2a2a27;
    --series-1: #3987e5; --series-2: #d95926;
    --good-text: #4cc94c; --critical-text: #f07272; --warning-text: #fab219;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text-primary);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
.top {{ background: var(--brand); color: #fff; padding: 14px 16px 12px; display: flex; gap: 12px; align-items: center; }}
.logo {{ width: 44px; height: 44px; object-fit: contain; background: #fff; border-radius: 10px; padding: 3px; }}
.top h1 {{ font-size: 17px; margin: 0; }} .top p {{ margin: 0; opacity: .8; font-size: 12.5px; }}
main {{ max-width: 1040px; margin: 0 auto; padding: 14px 16px 40px; }}
.abas {{ display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; margin-bottom: 14px; }}
.abas a {{ flex: none; text-decoration: none; color: var(--text-secondary); background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 999px; padding: 6px 14px; font-size: 14px; }}
.abas a.on {{ background: var(--text-primary); color: var(--surface-1); border-color: var(--text-primary); }}
.kpis {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
@media (min-width: 720px) {{ .kpis {{ grid-template-columns: repeat(6, 1fr); }} }}
.kpi {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 12px; min-width: 0; }}
.kpi-l {{ font-size: 12.5px; color: var(--text-secondary); }}
.kpi-v {{ font-size: 20px; font-weight: 650; margin: 2px 0; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
.kpi-n {{ font-size: 11.5px; color: var(--text-muted); }}
.kpi.neg .kpi-v, .neg {{ color: var(--critical-text); }}
.kpi.alerta {{ border-color: var(--critical); }}
.kpi.alerta .kpi-v {{ color: var(--critical-text); }}
section {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 14px; padding: 14px; margin-top: 14px; }}
section h2 {{ font-size: 16px; margin: 0 0 10px; }}
.grid2 {{ display: grid; gap: 14px; }}
@media (min-width: 860px) {{ .grid2 {{ grid-template-columns: 1fr 1fr; }} .grid2 section {{ margin-top: 0; }} .grid2 {{ margin-top: 14px; }} }}
.chart {{ position: relative; height: 240px; }}
details {{ margin-top: 8px; font-size: 13px; color: var(--text-secondary); }}
table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
td, th {{ padding: 7px 4px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
th {{ color: var(--text-secondary); font-weight: 500; }}
td small, .ct-desc small {{ display: block; color: var(--text-muted); font-size: 12px; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.num.in {{ color: var(--good-text); }}
.obras {{ display: grid; gap: 12px; }}
@media (min-width: 720px) {{ .obras {{ grid-template-columns: 1fr 1fr; }} }}
.obra {{ border: 1px solid var(--border); border-radius: 12px; padding: 12px; }}
.obra header {{ display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; flex-wrap: wrap; }}
.obra h3 {{ margin: 0; font-size: 15.5px; }}
.status {{ display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; font-weight: 600; white-space: nowrap; }}
.status i {{ font-style: normal; width: 17px; height: 17px; border-radius: 50%; display: inline-grid; place-items: center;
  font-size: 11px; color: #fff; }}
.s-good i, .meter-fill.s-good {{ background: var(--good); }} .status.s-good {{ color: var(--good-text); }}
.s-warning i, .meter-fill.s-warning {{ background: var(--warning); }} .status.s-warning {{ color: var(--warning-text); }}
.s-warning i {{ color: #3a2a00; }}
.s-critical i, .meter-fill.s-critical {{ background: var(--critical); }} .status.s-critical {{ color: var(--critical-text); }}
.s-muted i {{ background: var(--text-muted); }} .status.s-muted {{ color: var(--text-muted); }}
.meter {{ height: 10px; background: var(--grid); border-radius: 5px; margin: 12px 0 4px; overflow: hidden; }}
.meter-fill {{ height: 100%; border-radius: 5px; }}
.meter-cap {{ display: flex; justify-content: space-between; font-size: 12.5px; color: var(--text-secondary); }}
dl {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px 12px; margin: 12px 0 0; }}
dt {{ font-size: 12px; color: var(--text-secondary); }} dd {{ margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; }}
dd small {{ font-weight: 400; color: var(--text-muted); }}
.tag {{ font-size: 11px; font-weight: 500; border: 1px solid var(--border); border-radius: 6px; padding: 1px 6px; color: var(--text-secondary); }}
.banner {{ border: 1px solid var(--critical); border-radius: 10px; padding: 10px 12px; margin-bottom: 12px; font-size: 14px; }}
.sub {{ font-size: 13px; color: var(--text-secondary); margin: 6px 0; font-weight: 600; }}
.contas {{ list-style: none; margin: 0 0 8px; padding: 0; }}
.contas li {{ display: flex; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--border); }}
.contas li.venc .ct-desc small {{ color: var(--critical-text); }}
.ct-tipo {{ flex: none; font-size: 11.5px; font-weight: 600; border-radius: 6px; padding: 2px 7px; border: 1px solid var(--border); }}
.ct-desc {{ flex: 1; min-width: 0; font-size: 14px; overflow-wrap: anywhere; }}
.t-pend {{ color: var(--warning-text); border-color: var(--warning); }}
.ct-v {{ flex: none; font-weight: 600; font-variant-numeric: tabular-nums; }}
.vazio {{ color: var(--text-muted); font-size: 14px; }}
{telas.CSS_MENU}
footer {{ text-align: center; color: var(--text-muted); font-size: 12px; margin-top: 18px; }}
</style></head>
<body>
<div class="top">{logo}<div><h1>Painel financeiro</h1><p>{_e(config.NOME_ASSISTENTE)} · atualizado {atualizado}</p></div>{telas.menu(k, "financeiro")}</div>
<main>
  <nav class="abas">{abas}</nav>
  <div class="kpis">{kpis}</div>

  <div class="grid2">
    <section>
      <h2>Entradas e saídas por mês</h2>
      <div class="chart"><canvas id="gMeses" role="img" aria-label="Entradas e saídas dos últimos 6 meses"></canvas></div>
      <details><summary>Ver em tabela</summary><table><tr><th>Mês</th><th class="num">Entradas</th><th class="num">Saídas</th></tr>{tabela_meses}</table></details>
    </section>
    <section>
      <h2>Gastos por categoria <small style="font-weight:400;color:var(--text-muted)">· {d["rotulo"]}</small></h2>
      <div class="chart"><canvas id="gCats" role="img" aria-label="Gastos por categoria"></canvas></div>
      <details><summary>Ver em tabela</summary><table>{tabela_cats}</table></details>
    </section>
  </div>

  <section>
    <h2>Agenda de visitas · próximos 30 dias</h2>
    {agenda_html}
  </section>

  <section>
    <h2>Obras em andamento</h2>
    {alerta_obras}
    <div class="obras">{obras_html}</div>
  </section>

  <div class="grid2">
    <section><h2>Contas a pagar e receber</h2>{contas_html}</section>
    <section><h2>Últimos lançamentos</h2><table>{ultimos}</table></section>
  </div>
  <footer>Os dados vêm do que você manda no WhatsApp. Não compartilhe este link.</footer>
</main>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"></script>
<script>
const D = {dados_js};
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const brl = v => v.toLocaleString("pt-BR", {{style: "currency", currency: "BRL"}});
const curto = v => v >= 1000 ? "R$ " + (v / 1000).toLocaleString("pt-BR", {{maximumFractionDigits: 1}}) + " mil" : "R$ " + v.toLocaleString("pt-BR");
function desenhar() {{
  if (!window.Chart) {{   // sem internet para o gráfico: mostra as tabelas
    document.querySelectorAll(".chart").forEach(c => c.remove());
    document.querySelectorAll("details").forEach(d => d.open = true);
    return;
  }}
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = css("--text-secondary");
  const grid = {{color: css("--grid"), drawTicks: false}};
  const tip = {{backgroundColor: css("--surface-1"), titleColor: css("--text-primary"), bodyColor: css("--text-primary"),
               borderColor: css("--border"), borderWidth: 1, padding: 10,
               callbacks: {{label: c => " " + (c.dataset.label ? c.dataset.label + ": " : "") + brl(c.raw)}}}};
  new Chart(document.getElementById("gMeses"), {{
    type: "bar",
    data: {{labels: D.meses.map(m => m.rotulo), datasets: [
      {{label: "Entradas", data: D.meses.map(m => m.entradas), backgroundColor: css("--series-1"), borderRadius: 4, maxBarThickness: 22}},
      {{label: "Saídas", data: D.meses.map(m => m.saidas), backgroundColor: css("--series-2"), borderRadius: 4, maxBarThickness: 22}}]}},
    options: {{maintainAspectRatio: false, interaction: {{mode: "index", intersect: false}},
      datasets: {{bar: {{categoryPercentage: .7, barPercentage: .9}}}},
      plugins: {{legend: {{position: "top", align: "start", labels: {{boxWidth: 12, boxHeight: 12, useBorderRadius: true, borderRadius: 3}}}}, tooltip: tip}},
      scales: {{x: {{grid: {{display: false}}, border: {{display: false}}, ticks: {{maxRotation: 0, autoSkip: false, font: {{size: 11}}}}}},
               y: {{grid, border: {{display: false}}, ticks: {{callback: curto, maxTicksLimit: 5, padding: 6}}}}}}}}
  }});
  if (D.cats.length) {{
    new Chart(document.getElementById("gCats"), {{
      type: "bar",
      data: {{labels: D.cats.map(c => c[0]), datasets: [{{data: D.cats.map(c => c[1]), backgroundColor: css("--series-1"),
              borderRadius: 4, maxBarThickness: 20}}]}},
      options: {{indexAxis: "y", maintainAspectRatio: false,
        plugins: {{legend: {{display: false}}, tooltip: tip}},
        scales: {{x: {{grid, border: {{display: false}}, ticks: {{callback: v => v >= 1000 ? (v / 1000).toLocaleString("pt-BR") + " mil" : v, maxTicksLimit: 4, maxRotation: 0, font: {{size: 11}}}}}},
                 y: {{grid: {{display: false}}, border: {{display: false}}}}}}}}
    }});
  }} else {{
    document.getElementById("gCats").parentElement.innerHTML = '<p class="vazio">Sem gastos no período.</p>';
  }}
}}
desenhar();
</script>
</body></html>'''
