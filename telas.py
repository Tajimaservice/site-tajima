"""Telas do painel para montar orçamentos e editar a tabela de preços (abrem no celular ou no computador)."""
import json
from html import escape

from . import catalogo, config, db, vitrine
from .orcamento_pdf import brl

MENU = [("financeiro", "/painel", "Financeiro"), ("orcamento", "/painel/orcamento", "Novo orçamento"),
        ("precos", "/painel/precos", "Tabela de preços"), ("site", "/painel/site", "Site")]

CSS_MENU = """
.menu{display:flex;gap:6px;flex-wrap:wrap;margin-left:auto}
.menu a{color:#fff;text-decoration:none;font-size:14px;font-weight:600;padding:8px 12px;border-radius:999px;border:1px solid rgba(255,255,255,.35)}
.menu a.on{background:#fff;color:var(--brand)}
@media(max-width:640px){.top{flex-wrap:wrap}.menu{margin-left:0;width:100%}}
"""


def menu(k: str, ativo: str) -> str:
    return '<nav class="menu" aria-label="Telas">' + "".join(
        f'<a href="{url}?k={escape(k)}" class="{"on" if nome == ativo else ""}">{rot}</a>' for nome, url, rot in MENU) + "</nav>"


def _js(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def _base(k: str, ativo: str, titulo: str, corpo: str, script: str) -> str:
    logo = f'<img src="/painel/logo?k={escape(k)}" alt="" class="logo">' if config.LOGO.exists() else ""
    return f'''<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{escape(titulo)} – {escape(config.NOME_ASSISTENTE)}</title>
<style>
:root{{color-scheme:light;--brand:{config.COR_PRINCIPAL};--acc:{config.COR_DESTAQUE};--bg:#f3f3f1;--card:#fcfcfb;--line:#e3e2de;
--ink:#0b0b0b;--soft:#52514e;--muted:#7a7974;--ok:#0b7a32;--bad:#b02a2a}}
@media (prefers-color-scheme:dark){{:root:where(:not([data-theme="light"])){{color-scheme:dark;--bg:#111110;--card:#1a1a19;--line:#2e2e2b;
--ink:#f0efec;--soft:#c3c2b7;--muted:#8f8e86;--ok:#4cc94c;--bad:#f07272}}}}
*{{box-sizing:border-box;min-width:0}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
.top{{background:var(--brand);color:#fff;padding:12px 16px;display:flex;gap:12px;align-items:center}}
.logo{{width:44px;height:44px;object-fit:contain;background:#fff;border-radius:10px;padding:3px}}
.top h1{{font-size:17px;margin:0}}.top p{{margin:0;opacity:.8;font-size:12.5px}}
{CSS_MENU}
main{{max-width:1100px;margin:0 auto;padding:16px 16px 120px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-top:14px}}
h2{{font-size:16px;margin:0 0 12px}}
label{{font-size:13px;font-weight:600;color:var(--soft);display:block;margin-bottom:4px}}
input,select,textarea{{font:inherit;font-size:16px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:9px;padding:9px 10px;width:100%;min-height:42px}}
textarea{{min-height:70px;resize:vertical}}
input:focus-visible,select:focus-visible,textarea:focus-visible,button:focus-visible,a:focus-visible{{outline:2px solid var(--acc);outline-offset:1px}}
.g2{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}}
@media(max-width:640px){{.g2{{grid-template-columns:minmax(0,1fr)}}}}
button,.btn{{font:inherit;font-weight:650;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);min-height:42px;padding:0 14px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px}}
.pri{{background:var(--brand);border-color:var(--brand);color:#fff}}
.acc{{background:#1fa855;border-color:#1fa855;color:#fff}}
.x{{min-height:36px;width:36px;padding:0;color:var(--muted)}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.vazio{{color:var(--muted)}}
.barra{{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px;z-index:5}}
.barra .in{{max-width:1100px;margin:0 auto;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
@media(max-width:640px){{.barra button,.barra .btn{{min-height:38px;padding:0 10px;font-size:14px}}main{{padding-bottom:190px}}.msg{{width:100%}}}}
.msg{{font-size:14px}}.msg.ok{{color:var(--ok)}}.msg.bad{{color:var(--bad)}}
small.dica{{display:block;color:var(--muted);font-size:12.5px;margin-top:6px}}
{corpo[0]}
</style></head><body>
<div class="top">{logo}<div><h1>{escape(titulo)}</h1><p>{escape(config.NOME_ASSISTENTE)}</p></div>{menu(k, ativo)}</div>
<main>{corpo[1]}</main>
<script>
{{
const K = {_js(k)};
const brl = v => (Math.round((+v||0)*100)/100).toLocaleString("pt-BR", {{style:"currency", currency:"BRL"}});
const num = v => {{ const t = String(v ?? "").trim(); if (!t) return 0; const n = Number(t.includes(",") ? t.replace(/\\./g,"").replace(",",".") : t); return isFinite(n) ? n : 0; }};
const dec = v => typeof v === "number" ? v.toFixed(2).replace(".", ",") : esc(v);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]));
{script}
}}
</script></body></html>'''


# ------------------------------------------------------------------ novo orçamento
def pagina_orcamento(k: str, orc_id: int | None = None) -> str:
    cat = [{"codigo": i["codigo"], "servico": i["servico"], "unidade": i["unidade"], "preco": i["preco"]} for i in catalogo.listar()]
    orc = db.obter_orcamento(orc_id) if orc_id else None
    inicial = {"id": orc["id"], "cliente": orc["cliente"], "endereco": orc["endereco"], "itens": orc["itens"],
               "desconto_pct": orc["desconto_pct"] or 0, "observacoes": orc["observacoes"] or ""} if orc else None
    ultimos = db.listar_orcamentos(12)
    css = """
.add{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;margin-bottom:12px}
.itens{width:100%;border-collapse:collapse}
.itens th{font-size:12.5px;color:var(--soft);font-weight:600;text-align:left;padding:6px 4px;border-bottom:1px solid var(--line)}
.itens td{padding:6px 4px;border-bottom:1px solid var(--line);vertical-align:middle}
.itens input{min-height:38px;padding:6px 8px}
.itens .q{width:84px}.itens .u{width:64px}.itens .p{width:112px}
.cod{font-size:12px;color:var(--muted)}
@media(max-width:700px){.itens thead{display:none}.itens tr{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,.8fr) minmax(0,1fr) auto;gap:6px;padding:10px 0;border-bottom:1px solid var(--line)}
.itens td{border:0;padding:0}.itens td.d{grid-column:1/-1}.itens .q,.itens .u,.itens .p{width:100%}.itens td.sub{grid-column:1/-1;order:9;font-weight:650}}
.tot{display:grid;grid-template-columns:auto auto;gap:4px 16px;justify-content:end;margin-top:12px}
.tot b{font-size:20px}
.lista{list-style:none;margin:0;padding:0}
.lista li{display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line);flex-wrap:wrap}
.lista .nm{flex:1;min-width:160px}.lista small{display:block;color:var(--muted)}
"""
    corpo = f"""
<section>
  <h2 id="tit">Novo orçamento</h2>
  <div class="g2">
    <div><label for="cliente">Cliente</label><input id="cliente" placeholder="Nome do cliente"></div>
    <div><label for="endereco">Endereço da obra</label><input id="endereco" placeholder="Rua, número, bairro"></div>
  </div>
</section>
<section>
  <h2>Serviços</h2>
  <div class="add">
    <div><label for="busca">Adicionar da tabela de preços</label>
      <input id="busca" list="catlist" placeholder="Digite: pintura, tomada, forro, P01…" autocomplete="off">
      <datalist id="catlist"></datalist></div>
    <button type="button" id="avulso" style="align-self:end">+ Item avulso</button>
  </div>
  <table class="itens"><thead><tr><th>Descrição</th><th>Qtd.</th><th>Unid.</th><th>Preço unit.</th><th class="num">Subtotal</th><th></th></tr></thead>
  <tbody id="linhas"></tbody></table>
  <p class="vazio" id="semItens">Nenhum serviço ainda. Digite acima para buscar na sua tabela.</p>
  <div class="g2" style="margin-top:14px">
    <div><label for="desc">Desconto (%)</label><input id="desc" inputmode="decimal" placeholder="0"></div>
    <div><label for="obs">Observações (aparecem no PDF)</label><textarea id="obs" placeholder="Ex.: material incluso; prazo de 10 dias úteis"></textarea></div>
  </div>
  <div class="tot"><span>Subtotal</span><span class="num" id="tSub">R$ 0,00</span><span>Desconto</span><span class="num" id="tDesc">R$ 0,00</span>
    <b>Total</b><b class="num" id="tTot">R$ 0,00</b></div>
</section>
<section>
  <h2>Últimos orçamentos</h2>
  <ul class="lista">{"".join(
      f'<li><span class="nm">nº {o["id"]:04d} – {escape(o["cliente"] or "Cliente")}<small>{o["criado_em"][8:10]}/{o["criado_em"][5:7]}/{o["criado_em"][:4]}</small></span>'
      f'<span class="num">{brl(o["total"])}</span>'
      f'<a class="btn" href="/painel/orcamento/{o["id"]}/pdf?k={escape(k)}" target="_blank">PDF</a>'
      f'<a class="btn" href="/painel/orcamento?k={escape(k)}&id={o["id"]}">Editar</a></li>' for o in ultimos) or '<li class="vazio">Nenhum orçamento ainda.</li>'}</ul>
</section>
<div class="barra"><div class="in">
  <button class="pri" id="gerar">Salvar e gerar PDF</button>
  <a class="btn" id="baixar" target="_blank" hidden>Baixar PDF</a>
  <button class="acc" id="zap" hidden>Enviar no meu WhatsApp</button>
  <button id="novo" hidden>Novo orçamento</button>
  <span class="msg" id="msg"></span>
</div></div>"""
    script = f"""
const CAT = {_js(cat)};
const INI = {_js(inicial)};
const $ = s => document.querySelector(s);
let itens = [], orcId = null;
$("#catlist").innerHTML = CAT.map(c => `<option value="${{esc(c.codigo)}} – ${{esc(c.servico)}}">${{brl(c.preco)}} / ${{esc(c.unidade)}}</option>`).join("");
function render(){{
  $("#linhas").innerHTML = itens.map((it, i) => `<tr>
    <td class="d"><input data-i="${{i}}" data-f="descricao" value="${{esc(it.descricao)}}" aria-label="Descrição">${{it.codigo ? `<span class="cod">${{esc(it.codigo)}}</span>` : ""}}</td>
    <td><input class="q" data-i="${{i}}" data-f="quantidade" inputmode="decimal" value="${{esc(String(it.quantidade).replace(".", ","))}}" aria-label="Quantidade"></td>
    <td><input class="u" data-i="${{i}}" data-f="unidade" value="${{esc(it.unidade)}}" aria-label="Unidade"></td>
    <td><input class="p" data-i="${{i}}" data-f="preco_unitario" inputmode="decimal" value="${{dec(it.preco_unitario)}}" aria-label="Preço unitário"></td>
    <td class="num sub" id="s${{i}}">${{brl(num(it.quantidade) * num(it.preco_unitario))}}</td>
    <td><button class="x" data-del="${{i}}" aria-label="Remover">✕</button></td></tr>`).join("");
  $("#semItens").hidden = itens.length > 0;
  totais();
}}
function totais(){{
  const sub = itens.reduce((s, it) => s + Math.round(num(it.quantidade) * num(it.preco_unitario) * 100) / 100, 0);
  const d = Math.round(sub * Math.min(100, Math.max(0, num($("#desc").value))) ) / 100;
  $("#tSub").textContent = brl(sub); $("#tDesc").textContent = "− " + brl(d); $("#tTot").textContent = brl(sub - d);
}}
function sujo(){{ $("#msg").textContent = ""; $("#zap").hidden = true; $("#baixar").hidden = true; }}
$("#busca").addEventListener("change", e => {{
  const cod = e.target.value.split(" – ")[0].trim().toUpperCase();
  const c = CAT.find(x => x.codigo === cod) || CAT.find(x => x.servico.toLowerCase() === e.target.value.trim().toLowerCase());
  if (!c) return;
  itens.push({{codigo: c.codigo, descricao: c.servico, unidade: c.unidade, quantidade: 1, preco_unitario: c.preco}});
  e.target.value = ""; render(); sujo();
  const q = document.querySelectorAll(".itens .q"); q[q.length - 1].focus(); q[q.length - 1].select();
}});
$("#avulso").addEventListener("click", () => {{
  itens.push({{codigo: "", descricao: "", unidade: "un", quantidade: 1, preco_unitario: 0}}); render(); sujo();
  const d = document.querySelectorAll('.itens [data-f="descricao"]'); d[d.length - 1].focus();
}});
$("#linhas").addEventListener("input", e => {{
  const i = e.target.dataset.i, f = e.target.dataset.f; if (i === undefined) return;
  itens[i][f] = e.target.value;
  if (f === "quantidade" || f === "preco_unitario") $("#s" + i).textContent = brl(num(itens[i].quantidade) * num(itens[i].preco_unitario));
  totais(); sujo();
}});
$("#linhas").addEventListener("click", e => {{ const b = e.target.closest("[data-del]"); if (b) {{ itens.splice(+b.dataset.del, 1); render(); sujo(); }} }});
["#desc", "#cliente", "#endereco", "#obs"].forEach(s => $(s).addEventListener("input", () => {{ totais(); sujo(); }}));
function carregar(o){{
  orcId = o ? o.id : null;
  $("#tit").textContent = o ? `Editando orçamento nº ${{String(o.id).padStart(4, "0")}}` : "Novo orçamento";
  $("#cliente").value = o ? o.cliente || "" : ""; $("#endereco").value = o ? o.endereco || "" : "";
  $("#desc").value = o && o.desconto_pct ? String(o.desconto_pct).replace(".", ",") : ""; $("#obs").value = o ? o.observacoes || "" : "";
  itens = o ? o.itens.map(i => ({{...i}})) : []; render(); sujo();
}}
$("#gerar").addEventListener("click", async () => {{
  const validos = itens.filter(i => String(i.descricao).trim() && num(i.quantidade) > 0);
  if (!validos.length) {{ $("#msg").className = "msg bad"; $("#msg").textContent = "Adicione pelo menos um serviço com quantidade."; return; }}
  $("#gerar").disabled = true; $("#msg").className = "msg"; $("#msg").textContent = "Gerando…";
  try {{
    const r = await fetch(`/painel/api/orcamento?k=${{encodeURIComponent(K)}}`, {{method: "POST", headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{id: orcId, cliente: $("#cliente").value, endereco: $("#endereco").value, desconto_pct: num($("#desc").value),
        observacoes: $("#obs").value, itens: validos.map(i => ({{...i, quantidade: num(i.quantidade), preco_unitario: num(i.preco_unitario)}}))}})}});
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || "erro");
    orcId = j.id;
    $("#tit").textContent = `Editando orçamento nº ${{String(j.id).padStart(4, "0")}}`;
    $("#msg").className = "msg ok"; $("#msg").textContent = `Orçamento nº ${{String(j.id).padStart(4, "0")}} salvo: ${{brl(j.total)}}`;
    $("#baixar").href = j.pdf; $("#baixar").hidden = false; $("#zap").hidden = false; $("#novo").hidden = false;
    history.replaceState(null, "", `?k=${{encodeURIComponent(K)}}&id=${{j.id}}`);
  }} catch (e) {{ $("#msg").className = "msg bad"; $("#msg").textContent = "Não consegui salvar: " + e.message; }}
  $("#gerar").disabled = false;
}});
$("#zap").addEventListener("click", async () => {{
  $("#msg").className = "msg"; $("#msg").textContent = "Enviando…";
  const r = await fetch(`/painel/api/orcamento/${{orcId}}/whatsapp?k=${{encodeURIComponent(K)}}`, {{method: "POST"}});
  const j = await r.json().catch(() => ({{}}));
  $("#msg").className = "msg " + (r.ok ? "ok" : "bad"); $("#msg").textContent = j.mensagem || "Não consegui enviar.";
}});
$("#novo").addEventListener("click", () => {{ history.replaceState(null, "", `?k=${{encodeURIComponent(K)}}`); carregar(null); }});
carregar(INI);
"""
    return _base(k, "orcamento", "Orçamentos", (css, corpo), script)


# ------------------------------------------------------------------ tabela de preços
def pagina_precos(k: str) -> str:
    itens = [{c: i[c] for c in ("codigo", "servico", "unidade", "mao_de_obra", "material", "palavras_chave", "site")} for i in catalogo.listar()]
    css = """
.ferr{display:flex;gap:8px;flex-wrap:wrap;align-items:end;margin-bottom:12px}
.ferr>div{flex:1;min-width:200px}
.tab{width:100%;border-collapse:collapse}
.tab th{font-size:12.5px;color:var(--soft);font-weight:600;text-align:left;padding:6px 4px;border-bottom:1px solid var(--line);white-space:nowrap}
.tab td{padding:6px 4px;border-bottom:1px solid var(--line);vertical-align:top}
.tab input{min-height:38px;padding:6px 8px}
.tab .c{width:64px}.tab .u{width:64px}.tab .v{width:100px}
.tab .kw{margin-top:4px;font-size:13px;min-height:32px;color:var(--soft)}
.tab td.pr{padding-top:14px;font-weight:650}
.chk{display:flex;align-items:center;justify-content:center;min-height:38px}
.chk input{width:22px;height:22px;min-height:0}
@media(max-width:760px){.tab thead{display:none}.tab tr{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px 8px;padding:12px 0;border-bottom:1px solid var(--line)}
.tab td{border:0;padding:0}.tab td.s{grid-column:1/-1;order:-1}.tab .c,.tab .u,.tab .v{width:100%}
.tab td[data-l]::before{content:attr(data-l);display:block;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tab td.pr{padding-top:0;text-align:left}.chk{justify-content:flex-start}}
"""
    corpo = """
<section>
  <h2>Sua tabela de preços</h2>
  <p style="margin:0 0 12px;color:var(--soft)">O preço é <b>mão de obra + material</b>. É ele que o assistente usa nos orçamentos por áudio e nesta tela.
  Marque <b>No site</b> para o serviço aparecer na calculadora de estimativa do site.</p>
  <div class="ferr">
    <div><label for="filtro">Buscar</label><input id="filtro" placeholder="pintura, P01, forro…"></div>
    <button id="novo">+ Adicionar serviço</button>
    <button id="reaj">Reajustar todos (%)</button>
  </div>
  <table class="tab"><thead><tr><th>Cód.</th><th>Serviço e palavras-chave</th><th>Unid.</th><th>Mão de obra</th><th>Material</th><th class="num">Preço</th><th>No site</th><th></th></tr></thead>
  <tbody id="linhas"></tbody></table>
  <small class="dica">Palavras-chave ajudam o assistente a achar o serviço quando você fala por áudio. Remover um serviço não altera orçamentos já feitos.</small>
</section>
<div class="barra"><div class="in">
  <button class="pri" id="salvar">Salvar alterações</button>
  <span class="msg" id="msg">Nenhuma alteração.</span>
</div></div>"""
    script = f"""
let itens = {_js(itens)};
const $ = s => document.querySelector(s);
let mudou = false;
function marcar(){{ mudou = true; $("#msg").className = "msg"; $("#msg").textContent = "Há alterações não salvas."; }}
function render(){{
  const f = $("#filtro").value.trim().toLowerCase();
  $("#linhas").innerHTML = itens.map((it, i) => {{
    if (f && !(it.codigo + " " + it.servico + " " + it.palavras_chave).toLowerCase().includes(f)) return "";
    return `<tr>
    <td data-l="Código"><input class="c" data-i="${{i}}" data-f="codigo" value="${{esc(it.codigo)}}" aria-label="Código" placeholder="novo"></td>
    <td class="s"><input data-i="${{i}}" data-f="servico" value="${{esc(it.servico)}}" aria-label="Serviço" placeholder="Descrição do serviço">
      <input class="kw" data-i="${{i}}" data-f="palavras_chave" value="${{esc(it.palavras_chave)}}" aria-label="Palavras-chave" placeholder="palavras-chave"></td>
    <td data-l="Unid."><input class="u" data-i="${{i}}" data-f="unidade" value="${{esc(it.unidade)}}" aria-label="Unidade"></td>
    <td data-l="Mão de obra"><input class="v" data-i="${{i}}" data-f="mao_de_obra" inputmode="decimal" value="${{dec(it.mao_de_obra)}}" aria-label="Mão de obra"></td>
    <td data-l="Material"><input class="v" data-i="${{i}}" data-f="material" inputmode="decimal" value="${{dec(it.material)}}" aria-label="Material"></td>
    <td class="num pr" data-l="Preço" id="p${{i}}">${{brl(num(it.mao_de_obra) + num(it.material))}}</td>
    <td data-l="No site"><label class="chk"><input type="checkbox" data-i="${{i}}" data-f="site" ${{it.site ? "checked" : ""}} aria-label="Mostrar no site"></label></td>
    <td><button class="x" data-del="${{i}}" aria-label="Remover">✕</button></td></tr>`;
  }}).join("");
}}
$("#linhas").addEventListener("input", e => {{
  const i = e.target.dataset.i, f = e.target.dataset.f; if (i === undefined) return;
  itens[i][f] = e.target.type === "checkbox" ? (e.target.checked ? 1 : 0) : e.target.value;
  if (f === "mao_de_obra" || f === "material") $("#p" + i).textContent = brl(num(itens[i].mao_de_obra) + num(itens[i].material));
  marcar();
}});
$("#linhas").addEventListener("click", e => {{ const b = e.target.closest("[data-del]"); if (b) {{ itens.splice(+b.dataset.del, 1); render(); marcar(); }} }});
$("#filtro").addEventListener("input", render);
$("#novo").addEventListener("click", () => {{
  $("#filtro").value = ""; itens.push({{codigo: "", servico: "", unidade: "m²", mao_de_obra: 0, material: 0, palavras_chave: "", site: 0}});
  render(); marcar(); const s = document.querySelectorAll('[data-f="servico"]'); s[s.length - 1].focus();
}});
$("#reaj").addEventListener("click", () => {{
  const box = document.createElement("div");
  box.innerHTML = `<div style="display:flex;gap:8px;align-items:end;margin-bottom:12px"><div style="flex:1"><label for="pct">Reajuste em % (use negativo para baixar)</label><input id="pct" inputmode="decimal" placeholder="Ex.: 10"></div><button class="pri" id="apl">Aplicar</button></div>`;
  if (!$("#pct")) $(".ferr").after(box);
  $("#apl").onclick = () => {{ const p = num($("#pct").value); if (!p) return;
    itens.forEach(it => {{ it.mao_de_obra = Math.round(num(it.mao_de_obra) * (1 + p / 100) * 100) / 100; it.material = Math.round(num(it.material) * (1 + p / 100) * 100) / 100; }});
    box.remove(); render(); marcar(); $("#msg").textContent = `Reajuste de ${{p}}% aplicado. Confira e salve.`; }};
  $("#pct").focus();
}});
$("#salvar").addEventListener("click", async () => {{
  const sem = itens.filter(i => !String(i.servico).trim()).length;
  $("#salvar").disabled = true; $("#msg").className = "msg"; $("#msg").textContent = "Salvando…";
  try {{
    const r = await fetch(`/painel/api/precos?k=${{encodeURIComponent(K)}}`, {{method: "POST", headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{itens: itens.map(i => ({{...i, mao_de_obra: num(i.mao_de_obra), material: num(i.material)}}))}})}});
    const j = await r.json();
    if (!r.ok) throw new Error(j.erro || "erro");
    itens = j.itens; render(); mudou = false;
    $("#msg").className = "msg ok"; $("#msg").textContent = `Tabela salva: ${{j.itens.length}} serviços.` + (sem ? ` ${{sem}} linha(s) sem descrição foram ignoradas.` : "");
  }} catch (e) {{ $("#msg").className = "msg bad"; $("#msg").textContent = "Não consegui salvar: " + e.message; }}
  $("#salvar").disabled = false;
}});
window.addEventListener("beforeunload", e => {{ if (mudou) {{ e.preventDefault(); e.returnValue = ""; }} }});
render();
"""
    return _base(k, "precos", "Tabela de preços", (css, corpo), script)


# ------------------------------------------------------------------ conteúdo do site
ICONES_SVG = {
    "rolo": '<path d="M5 4h12v5H5zM17 6.5h2v5h-8v3" /><path d="M10 14.5h2v6h-2z"/>',
    "gota": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    "chave": '<path d="M14.5 5.5a4 4 0 0 0-5 5L4 16l4 4 5.5-5.5a4 4 0 0 0 5-5l-2.5 2.5-3-1-1-3z"/>',
    "casa": '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "cubo": '<path d="M12 3 20 7.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5 12 12l8-4.5M12 12v9"/>',
    "predio": '<path d="M5 21V4h9v17M14 9h5v12M3 21h18"/><path d="M8 8h3M8 12h3M8 16h3"/>',
    "piso": '<path d="M4 4h16v16H4zM4 12h16M12 4v16"/>',
    "ferramenta": '<path d="M4 20l7-7M14 4l6 6-4 4-6-6zM9 9l6 6"/>',
}


def pagina_site(k: str) -> str:
    css = """
.sv{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:10px;align-items:start;padding:12px 0;border-bottom:1px solid var(--line)}
.sv .ic{width:44px;height:44px;border-radius:10px;background:var(--brand);color:#fff;display:grid;place-items:center}
.sv .ic svg{width:24px;height:24px}
.sv input{margin-bottom:6px}.sv textarea{min-height:56px}
.sv .acoes{display:flex;flex-direction:column;gap:6px}
.sv.off{opacity:.5}
.sw{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--soft);white-space:nowrap}
.sw input{width:20px;height:20px;min-height:0}
.fotos{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.ft{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--bg)}
.ft .im{display:grid;grid-template-columns:repeat(var(--n),minmax(0,1fr));gap:2px;background:var(--line)}
.ft img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block}
.ft .cx{padding:8px;display:flex;flex-direction:column;gap:6px}
.ft .tag{font-size:12px;font-weight:700;color:var(--soft)}
.ft .ln{display:flex;gap:6px;justify-content:space-between;align-items:center}
.ft.off img{filter:grayscale(1) opacity(.5)}
.novo{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;align-items:end}
.dica2{background:var(--bg);border:1px dashed var(--line);border-radius:12px;padding:12px;font-size:14px;color:var(--soft);margin-bottom:12px}
"""
    corpo = """
<section>
  <h2>Como funciona</h2>
  <div class="dica2">📷 Pelo WhatsApp, mande a foto para o assistente com a legenda <b>antes</b>, <b>depois</b> ou <b>galeria</b>
  (ex.: <i>galeria pintura de fachada na Mooca</i>) e responda <b>sim</b> para publicar.
  🎤 Também dá para falar: <i>"acrescenta no site o serviço de impermeabilização"</i>, <i>"tira a foto 3 do site"</i>.
  Aqui você vê tudo e muda com um clique.</div>
</section>
<section>
  <h2>Serviços do site <small style="font-weight:400;color:var(--muted)">(os cards de "O que fazemos")</small></h2>
  <div id="servs"></div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px"><button id="addS">+ Adicionar serviço</button></div>
</section>
<section>
  <h2>Fotos no site</h2>
  <div class="novo" style="margin-bottom:14px">
    <div><label for="nTipo">Enviar foto pelo painel</label><select id="nTipo"><option value="galeria">Galeria (uma ou várias fotos)</option><option value="par">Antes e depois (duas fotos)</option></select></div>
    <div><label for="nF1" id="lF1">Fotos</label><input type="file" id="nF1" accept="image/*" multiple></div>
    <div id="bF2" hidden><label for="nF2">Foto do depois</label><input type="file" id="nF2" accept="image/*"></div>
    <div><label for="nLeg">Legenda</label><input id="nLeg" placeholder="Ex.: Pintura de sala na Vila Mariana"></div>
    <div><button class="pri" id="nEnv">Publicar no site</button></div>
  </div>
  <div class="fotos" id="fotos"></div>
  <p class="vazio" id="semF">Nenhuma foto ainda. Enquanto isso, o site mostra o antes e depois que já estava nele.</p>
</section>
<div class="barra"><div class="in">
  <button class="pri" id="salvar">Salvar serviços</button>
  <span class="msg" id="msg">Fotos são salvas na hora. Serviços: clique em salvar.</span>
</div></div>"""
    script = f"""
let D = {_js(json.loads(vitrine.json_painel()))};
const ICON = {_js(ICONES_SVG)};
const $ = s => document.querySelector(s);
const foto = a => `/api/site/foto/${{encodeURIComponent(a)}}`;
function rServ(){{
  $("#servs").innerHTML = D.servicos.map((s, i) => `<div class="sv ${{s.ativo ? "" : "off"}}">
    <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${{ICON[s.icone] || ICON.ferramenta}}</svg></div>
    <div><input data-i="${{i}}" data-f="nome" value="${{esc(s.nome)}}" aria-label="Nome do serviço">
      <textarea data-i="${{i}}" data-f="descricao" aria-label="Descrição">${{esc(s.descricao)}}</textarea></div>
    <div class="acoes"><label class="sw"><input type="checkbox" data-i="${{i}}" data-f="ativo" ${{s.ativo ? "checked" : ""}}> No site</label>
      <button class="x" data-up="${{i}}" aria-label="Subir">↑</button><button class="x" data-del="${{i}}" aria-label="Remover">✕</button></div></div>`).join("");
}}
function rFotos(){{
  $("#semF").hidden = D.fotos.length > 0;
  $("#fotos").innerHTML = D.fotos.map(f => `<div class="ft ${{f.publicado ? "" : "off"}}">
    <div class="im" style="--n:${{f.tipo === "par" ? 2 : 1}}">${{f.tipo === "par" ? `<img src="${{foto(f.foto)}}" alt="Antes"><img src="${{foto(f.foto2)}}" alt="Depois">` : `<img src="${{foto(f.foto)}}" alt="">`}}</div>
    <div class="cx"><span class="tag">nº ${{f.id}} · ${{f.tipo === "par" ? "Antes e depois" : "Galeria"}}</span>
      <input data-leg="${{f.id}}" value="${{esc(f.legenda)}}" placeholder="Legenda" aria-label="Legenda">
      <div class="ln"><label class="sw"><input type="checkbox" data-pub="${{f.id}}" ${{f.publicado ? "checked" : ""}}> No site</label>
      <button class="x" data-apagar="${{f.id}}" aria-label="Apagar foto">🗑</button></div></div></div>`).join("");
}}
function aviso(t, cl){{ $("#msg").className = "msg " + (cl || ""); $("#msg").textContent = t; }}
$("#servs").addEventListener("input", e => {{ const i = e.target.dataset.i, f = e.target.dataset.f; if (i === undefined) return;
  D.servicos[i][f] = e.target.type === "checkbox" ? (e.target.checked ? 1 : 0) : e.target.value; aviso("Há alterações não salvas nos serviços."); }});
$("#servs").addEventListener("click", e => {{
  const d = e.target.closest("[data-del]"), u = e.target.closest("[data-up]");
  if (d) {{ D.servicos.splice(+d.dataset.del, 1); rServ(); aviso("Há alterações não salvas nos serviços."); }}
  if (u && +u.dataset.up > 0) {{ const i = +u.dataset.up; [D.servicos[i-1], D.servicos[i]] = [D.servicos[i], D.servicos[i-1]]; rServ(); aviso("Há alterações não salvas nos serviços."); }}
}});
$("#addS").addEventListener("click", () => {{ D.servicos.push({{nome: "", descricao: "", icone: "", ativo: 1}}); rServ();
  const n = document.querySelectorAll('#servs [data-f="nome"]'); n[n.length - 1].focus(); }});
$("#salvar").addEventListener("click", async () => {{
  aviso("Salvando…");
  const r = await fetch(`/painel/api/site/servicos?k=${{encodeURIComponent(K)}}`, {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify({{servicos: D.servicos}})}});
  const j = await r.json().catch(() => ({{}}));
  if (!r.ok) return aviso("Não consegui salvar: " + (j.erro || r.status), "bad");
  D.servicos = j.servicos; rServ(); aviso("Serviços salvos. O site já mostra a versão nova.", "ok");
}});
async function mudarFoto(id, corpo){{
  const r = await fetch(`/painel/api/site/foto/${{id}}?k=${{encodeURIComponent(K)}}`, {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify(corpo)}});
  const j = await r.json().catch(() => ({{}}));
  if (r.ok) {{ D.fotos = j.fotos; rFotos(); aviso("Foto atualizada.", "ok"); }} else aviso("Não consegui alterar a foto.", "bad");
}}
$("#fotos").addEventListener("change", e => {{
  if (e.target.dataset.pub) mudarFoto(e.target.dataset.pub, {{publicado: e.target.checked}});
  if (e.target.dataset.leg) mudarFoto(e.target.dataset.leg, {{legenda: e.target.value}});
}});
$("#fotos").addEventListener("click", e => {{ const b = e.target.closest("[data-apagar]");
  if (b && confirmar(b)) mudarFoto(b.dataset.apagar, {{apagar: true}}); }});
function confirmar(b){{ if (b.dataset.ok) return true; b.dataset.ok = 1; b.textContent = "Apagar?"; b.style.width = "auto"; b.style.padding = "0 8px";
  setTimeout(() => {{ delete b.dataset.ok; b.textContent = "🗑"; b.style.width = ""; b.style.padding = ""; }}, 3000); return false; }}
$("#nTipo").addEventListener("change", () => {{ const par = $("#nTipo").value === "par";
  $("#bF2").hidden = !par; $("#lF1").textContent = par ? "Foto do antes" : "Fotos"; $("#nF1").multiple = !par; }});
function reduzir(arq){{ return new Promise((ok, erro) => {{ const img = new Image(); const u = URL.createObjectURL(arq);
  img.onload = () => {{ const m = 1600, f = Math.min(1, m / Math.max(img.width, img.height)); const c = document.createElement("canvas");
    c.width = Math.round(img.width * f); c.height = Math.round(img.height * f); c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    URL.revokeObjectURL(u); ok(c.toDataURL("image/jpeg", .85)); }};
  img.onerror = () => erro(new Error("imagem inválida")); img.src = u; }}); }}
$("#nEnv").addEventListener("click", async () => {{
  const tipo = $("#nTipo").value, a = [...$("#nF1").files], b = $("#nF2").files[0];
  if (!a.length || (tipo === "par" && !b)) return aviso(tipo === "par" ? "Escolha a foto do antes e a do depois." : "Escolha uma ou mais fotos.", "bad");
  $("#nEnv").disabled = true;
  try {{
    const lotes = tipo === "par" ? [[a[0], b]] : a.map(x => [x]);
    for (let i = 0; i < lotes.length; i++) {{
      aviso(`Enviando ${{i + 1}} de ${{lotes.length}}…`);
      const f1 = await reduzir(lotes[i][0]), f2 = lotes[i][1] ? await reduzir(lotes[i][1]) : "";
      const r = await fetch(`/painel/api/site/foto?k=${{encodeURIComponent(K)}}`, {{method: "POST", headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{tipo, legenda: $("#nLeg").value, foto: f1, foto2: f2}})}});
      const j = await r.json(); if (!r.ok) throw new Error(j.erro || r.status); D.fotos = j.fotos;
    }}
    rFotos(); $("#nF1").value = ""; $("#nF2").value = ""; $("#nLeg").value = ""; aviso("Publicado no site.", "ok");
  }} catch (e) {{ aviso("Não consegui enviar: " + e.message, "bad"); }}
  $("#nEnv").disabled = false;
}});
rServ(); rFotos();
"""
    return _base(k, "site", "Site", (css, corpo), script)
