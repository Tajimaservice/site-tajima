"""O 'cérebro' do assistente: entende o pedido com a IA (Claude) e executa a ação certa."""
import json
import logging
import re
from datetime import date, timedelta

from . import catalogo, config, db, financeiro, visitas, vitrine
from .orcamento_pdf import brl, gerar, qtd

log = logging.getLogger("assistente")

FERRAMENTAS = [
    {
        "name": "criar_orcamento",
        "description": "Cria um orçamento NOVO para um cliente e gera o PDF. Use os códigos da tabela de preços sempre que o serviço existir nela.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cliente": {"type": "string", "description": "Nome do cliente (se não for dito, use 'Cliente')"},
                "endereco": {"type": "string", "description": "Endereço da obra, se for dito"},
                "itens": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "codigo": {"type": "string", "description": "Código da tabela (ex.: P01). Deixe vazio para item fora da tabela"},
                        "descricao": {"type": "string", "description": "Descrição do serviço (obrigatória se não houver código)"},
                        "quantidade": {"type": "number"},
                        "unidade": {"type": "string", "description": "m², m, un, vb... (para item fora da tabela)"},
                        "preco_unitario": {"type": "number", "description": "Só se o usuário DISSER o preço; senão use o da tabela"},
                        "observacao": {"type": "string"},
                    },
                    "required": ["quantidade"]}},
                "desconto_pct": {"type": "number", "description": "Desconto em % sobre o total, se pedido"},
                "observacoes": {"type": "string"},
            },
            "required": ["itens"],
        },
    },
    {
        "name": "alterar_orcamento",
        "description": "Altera um orçamento já feito (o último, se o número não for dito): adicionar/remover itens, mudar quantidade, preço, cliente, endereço ou desconto. Gera o PDF de novo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "numero": {"type": "integer", "description": "Número do orçamento; omita para o último"},
                "cliente": {"type": "string"}, "endereco": {"type": "string"},
                "adicionar_itens": {"type": "array", "items": {"type": "object", "properties": {
                    "codigo": {"type": "string"}, "descricao": {"type": "string"}, "quantidade": {"type": "number"},
                    "unidade": {"type": "string"}, "preco_unitario": {"type": "number"}, "observacao": {"type": "string"}},
                    "required": ["quantidade"]}},
                "remover_itens": {"type": "array", "items": {"type": "integer"}, "description": "Números dos itens (1, 2, 3...) a remover"},
                "alterar_itens": {"type": "array", "items": {"type": "object", "properties": {
                    "item": {"type": "integer"}, "quantidade": {"type": "number"}, "preco_unitario": {"type": "number"}},
                    "required": ["item"]}},
                "desconto_pct": {"type": "number"},
                "observacoes": {"type": "string"},
            },
        },
    },
    {
        "name": "reenviar_orcamento",
        "description": "Reenvia o PDF de um orçamento já feito (o último, se o número não for dito).",
        "input_schema": {"type": "object", "properties": {"numero": {"type": "integer"}}},
    },
    {
        "name": "listar_orcamentos",
        "description": "Lista os últimos orçamentos feitos.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "registrar_lancamentos",
        "description": "Registra um ou mais gastos (despesa) ou recebimentos (receita) no controle financeiro.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lancamentos": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "tipo": {"type": "string", "enum": ["despesa", "receita"]},
                        "valor": {"type": "number", "description": "Valor em reais"},
                        "categoria": {"type": "string", "enum": ["material", "mao_de_obra", "ferramentas", "transporte",
                                                                 "alimentacao", "aluguel_equipamento", "impostos_taxas",
                                                                 "pagamento_cliente", "outros"]},
                        "obra": {"type": "string", "description": "Obra ou cliente relacionado (ex.: 'João Silva')"},
                        "forma_pagamento": {"type": "string", "description": "Pix, dinheiro, cartão, boleto..."},
                        "descricao": {"type": "string"},
                        "data": {"type": "string", "description": "AAAA-MM-DD; omita para hoje"},
                    },
                    "required": ["tipo", "valor", "categoria"]}},
            },
            "required": ["lancamentos"],
        },
    },
    {
        "name": "desfazer_ultimo_lancamento",
        "description": "Apaga o último lançamento financeiro registrado (quando o usuário diz que errou, cancela, desfaz).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "consultar_financeiro",
        "description": "Responde quanto entrou, saiu, saldo, gastos por categoria/obra num período.",
        "input_schema": {
            "type": "object",
            "properties": {
                "periodo": {"type": "string", "enum": ["hoje", "semana", "mes", "mes_anterior", "ano", "tudo"]},
                "inicio": {"type": "string", "description": "AAAA-MM-DD (período personalizado)"},
                "fim": {"type": "string", "description": "AAAA-MM-DD"},
                "obra": {"type": "string"},
                "detalhado": {"type": "boolean", "description": "true para listar os lançamentos"},
            },
        },
    },
    {
        "name": "enviar_relatorio_excel",
        "description": "Envia uma planilha Excel com os lançamentos do período (e resumo por obra).",
        "input_schema": {
            "type": "object",
            "properties": {
                "periodo": {"type": "string", "enum": ["hoje", "semana", "mes", "mes_anterior", "ano", "tudo"]},
                "inicio": {"type": "string"}, "fim": {"type": "string"}, "obra": {"type": "string"},
            },
        },
    },
    {
        "name": "aprovar_orcamento",
        "description": "O cliente APROVOU/fechou um orçamento: cria a obra com o valor contratado e o custo previsto, e (se ele disser a forma de pagamento) agenda as parcelas a receber.",
        "input_schema": {
            "type": "object",
            "properties": {
                "numero": {"type": "integer", "description": "Número do orçamento; omita para o último"},
                "obra": {"type": "string", "description": "Nome da obra; omita para usar o nome do cliente"},
                "custo_previsto": {"type": "number", "description": "Só se ele disser quanto vai gastar na obra"},
                "parcelas": {"type": "array", "description": "Parcelas a receber, se ele disser (ex.: 40% de entrada hoje e 3 parcelas mensais). Calcule as datas.",
                             "items": {"type": "object", "properties": {
                                 "percentual": {"type": "number"}, "valor": {"type": "number"},
                                 "vencimento": {"type": "string", "description": "AAAA-MM-DD"},
                                 "descricao": {"type": "string"}}, "required": ["vencimento"]}},
            },
        },
    },
    {
        "name": "definir_obra",
        "description": "Cria ou ajusta uma obra: valor contratado, custo previsto (orçamento de gastos), cliente, ou marca como concluída.",
        "input_schema": {
            "type": "object",
            "properties": {
                "obra": {"type": "string"}, "cliente": {"type": "string"},
                "valor_contratado": {"type": "number"}, "custo_previsto": {"type": "number"},
                "situacao": {"type": "string", "enum": ["andamento", "concluida"]},
            },
            "required": ["obra"],
        },
    },
    {
        "name": "consultar_obras",
        "description": "Mostra o lucro e a situação de uma obra (contratado, recebido, gasto x previsto, lucro) ou de todas em andamento.",
        "input_schema": {"type": "object", "properties": {"obra": {"type": "string", "description": "Omita para todas"}}},
    },
    {
        "name": "agendar_contas",
        "description": "Agenda contas FUTURAS a pagar (boleto, fornecedor, parcela de material, aluguel) ou a receber (parcela de cliente), com vencimento. Não é para o que já foi pago/recebido.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contas": {"type": "array", "items": {"type": "object", "properties": {
                    "tipo": {"type": "string", "enum": ["pagar", "receber"]},
                    "valor": {"type": "number"},
                    "vencimento": {"type": "string", "description": "AAAA-MM-DD"},
                    "descricao": {"type": "string"},
                    "obra": {"type": "string"},
                    "categoria": {"type": "string", "enum": ["material", "mao_de_obra", "ferramentas", "transporte", "alimentacao",
                                                             "aluguel_equipamento", "impostos_taxas", "pagamento_cliente", "outros"]},
                }, "required": ["tipo", "valor", "vencimento"]}},
            },
            "required": ["contas"],
        },
    },
    {
        "name": "quitar_contas",
        "description": "Dá baixa em contas da lista de CONTAS EM ABERTO (pagou ou recebeu). Registra o lançamento automaticamente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contas": {"type": "array", "items": {"type": "object", "properties": {
                    "id": {"type": "integer", "description": "Nº da conta (#)"},
                    "valor": {"type": "number", "description": "Só se pagou/recebeu valor diferente (parcial)"},
                    "forma_pagamento": {"type": "string"},
                    "data": {"type": "string", "description": "AAAA-MM-DD; omita para hoje"},
                }, "required": ["id"]}},
            },
            "required": ["contas"],
        },
    },
    {
        "name": "listar_contas",
        "description": "Lista contas a pagar/receber em aberto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filtro": {"type": "string", "enum": ["proximas", "vencidas", "todas"]},
                "dias": {"type": "integer", "description": "Para 'proximas': quantos dias à frente (padrão 30)"},
                "tipo": {"type": "string", "enum": ["pagar", "receber"]},
            },
        },
    },
    {
        "name": "cancelar_conta",
        "description": "Cancela uma conta agendada que não vai mais existir (ou que foi agendada errado).",
        "input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    },
    {
        "name": "link_painel",
        "description": "Envia o link do painel financeiro (gráficos no navegador do celular).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "agenda_visitas",
        "description": "Mostra a agenda de visitas técnicas (pedidos do site e visitas marcadas) e os bloqueios.",
        "input_schema": {"type": "object", "properties": {
            "data_inicio": {"type": "string", "description": "AAAA-MM-DD; omita para hoje"},
            "data_fim": {"type": "string", "description": "AAAA-MM-DD; omita para 7 dias depois do início"}}},
    },
    {
        "name": "responder_visita",
        "description": "Confirma, recusa, cancela ou remarca uma visita da lista VISITAS (use o nº).",
        "input_schema": {"type": "object", "properties": {
            "id": {"type": "integer"},
            "acao": {"type": "string", "enum": ["confirmar", "recusar", "cancelar", "remarcar"]},
            "data": {"type": "string", "description": "Nova data AAAA-MM-DD (só para remarcar)"},
            "hora": {"type": "string", "description": "Novo horário HH:MM (só para remarcar)"},
            "motivo": {"type": "string"}}, "required": ["id", "acao"]},
    },
    {
        "name": "agendar_visita",
        "description": "Marca uma visita técnica que o dono combinou por fora (cliente ligou ou mandou mensagem). Já entra confirmada e ocupa o horário no site.",
        "input_schema": {"type": "object", "properties": {
            "nome": {"type": "string"}, "telefone": {"type": "string"},
            "data": {"type": "string", "description": "AAAA-MM-DD"}, "hora": {"type": "string", "description": "HH:MM"},
            "servico": {"type": "string"}, "endereco": {"type": "string"}, "detalhes": {"type": "string"}},
            "required": ["nome", "data", "hora"]},
    },
    {
        "name": "ajustar_agenda",
        "description": "Bloqueia ou libera dias/horários no site (folga, feriado, dia de obra cheia). Sem horas = dia todo.",
        "input_schema": {"type": "object", "properties": {
            "acao": {"type": "string", "enum": ["bloquear", "liberar"]},
            "data_inicio": {"type": "string", "description": "AAAA-MM-DD"},
            "data_fim": {"type": "string", "description": "AAAA-MM-DD, para um período; omita para um dia só"},
            "horas": {"type": "array", "items": {"type": "string"}, "description": "HH:MM; 'de manhã' = horários padrão antes do meio-dia"},
            "motivo": {"type": "string"}}, "required": ["acao", "data_inicio"]},
    },
    {
        "name": "definir_horarios",
        "description": "Muda os horários padrão de visita que aparecem no site (dias úteis, sábado, domingo) ou quantos dias à frente o cliente pode marcar.",
        "input_schema": {"type": "object", "properties": {
            "semana": {"type": "array", "items": {"type": "string"}, "description": "HH:MM de segunda a sexta"},
            "sabado": {"type": "array", "items": {"type": "string"}},
            "domingo": {"type": "array", "items": {"type": "string"}},
            "dias_a_frente": {"type": "integer"}}},
    },
    {
        "name": "alterar_preco",
        "description": "Muda o preço de um serviço da TABELA DE PREÇOS (vale para os próximos orçamentos e para o site). Use o código da tabela.",
        "input_schema": {"type": "object", "properties": {
            "codigo": {"type": "string"},
            "preco_total": {"type": "number", "description": "Novo preço final por unidade (mantém o material e ajusta a mão de obra)"},
            "mao_de_obra": {"type": "number"}, "material": {"type": "number"},
            "mostrar_no_site": {"type": "boolean"}}, "required": ["codigo"]},
    },
    {
        "name": "conteudo_site",
        "description": "Mostra ou muda o conteúdo do SITE da empresa: lista, tira fotos, acrescenta/edita/tira serviços. "
                       "Fotos novas chegam como foto no WhatsApp, não por esta ferramenta.",
        "input_schema": {"type": "object", "properties": {
            "acao": {"type": "string", "enum": ["listar", "remover_foto", "adicionar_servico", "editar_servico", "remover_servico"]},
            "id": {"type": "integer", "description": "nº da foto ou do serviço (lista SITE)"},
            "nome_atual": {"type": "string", "description": "nome do serviço que já está no site (para editar/tirar)"},
            "nome": {"type": "string", "description": "nome do serviço (novo, ou o novo nome ao editar)"},
            "descricao": {"type": "string", "description": "1 frase curta e vendedora, até 160 caracteres, sem preço"}},
            "required": ["acao"]},
    },
    {
        "name": "responder",
        "description": "Responde em texto: dúvidas, ajuda, ou para PERGUNTAR algo que falta (ex.: valor de um gasto não dito). Não use para criar orçamento ou registrar gasto.",
        "input_schema": {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"]},
    },
]


def _contas_para_ia():
    cs = db.contas_abertas()
    if not cs:
        return "nenhuma"
    return "\n".join(f"#{c['id']} | {c['tipo']} | {c['valor']:.2f} | vence {c['vencimento']} | {c['descricao'] or ''} | obra {c['obra'] or '-'}"
                     for c in cs[:60])


def _obras_para_ia():
    obs = db.listar_obras("andamento")
    if not obs:
        return "nenhuma"
    return "\n".join(f"{o['nome']} | cliente {o['cliente'] or '-'} | contratado {o['valor_contratado'] or 0:.2f} | "
                     f"custo previsto {o['custo_previsto'] or 0:.2f} | orçamento {o['orcamento_id'] or '-'}" for o in obs[:40])


def _sistema():
    obras = ", ".join(db.obras_conhecidas()) or "nenhuma ainda"
    return f"""Você é o assistente de orçamentos e controle financeiro da {config.EMPRESA}, empresa de {config.RAMO}.
O dono fala com você por áudio no WhatsApp (o texto vem de uma transcrição automática, pode ter pequenos erros: interprete com bom senso).
Hoje é {config.hoje():%d/%m/%Y} ({config.hoje().isoformat()}).

Regras:
- Sempre escolha UMA ferramenta. Para orçamento use criar_orcamento (ou alterar_orcamento se ele estiver corrigindo/complementando o último).
- Para gastos e recebimentos use registrar_lancamentos. "Gastei", "paguei", "comprei" = despesa. "Recebi", "o cliente pagou", "entrou" = receita (categoria pagamento_cliente).
- Mão de obra paga a ajudante/pedreiro/pintor = categoria mao_de_obra. Tinta, cimento, piso, fio = material.
- Use os nomes de obra já conhecidos quando combinarem: {obras}.
- Se faltar o VALOR de um gasto, pergunte com responder. Se faltar a quantidade de um serviço do orçamento, pergunte.
- Metragem: se ele disser medidas (ex.: parede de 3 por 2,8), calcule a área. "Metro" de parede/piso = m².
- Não invente preços: use a tabela. Só use preco_unitario se ele disser o preço.
- Respostas curtas, em português do Brasil.

Gestão financeira:
- "O orçamento X foi aprovado/fechado", "o cliente aceitou" = aprovar_orcamento. Se ele disser a forma de pagamento, monte as parcelas com datas (entrada = hoje, salvo se ele disser outra data).
- Conta que vai vencer no futuro ("tenho um boleto de 800 dia 15", "a Maria paga a 2ª parcela dia 10") = agendar_contas.
- Se o que ele pagou/recebeu corresponde a uma conta da lista CONTAS EM ABERTO (mesmo cliente/descrição/valor parecido), use quitar_contas com o nº da conta, e NÃO registrar_lancamentos.
- "Como está a obra X", "quanto lucrei na obra X", "lucro das obras" = consultar_obras. "O custo previsto da obra X é Y" = definir_obra.
- "Contas da semana", "o que vence", "quem me deve" = listar_contas (quem me deve = tipo receber).
- "Painel", "gráficos", "link" = link_painel.

Agenda de visitas técnicas (os clientes pedem pelo site; o horário fica reservado até ele responder):
- "Confirma a visita da Ana", "pode confirmar a 12" = responder_visita confirmar. "Não vou poder ir na da Ana" = recusar.
- "Minha agenda", "visitas da semana", "o que tenho amanhã" = agenda_visitas.
- "Bloqueia sexta de manhã", "não vou atender dia 24", "folga de 26 a 31" = ajustar_agenda bloquear. "Libera o sábado" = liberar.
- "Marca uma visita com o Pedro quinta às 10" = agendar_visita.
- "A partir de agora sábado só às 8" = definir_horarios.
- "Muda o preço da pintura interna para 26 o metro", "aumenta a mão de obra do forro para 45" = alterar_preco (não é orçamento).
- "Tela de orçamento", "tabela de preços no painel" = link_painel.

Site da empresa (o dono controla pelo WhatsApp):
- "Mostra o conteúdo do site", "quais fotos estão no site" = conteudo_site listar.
- "Tira do site a foto 3" = conteudo_site remover_foto. "Tira o serviço projeto 3D" = remover_servico (nome_atual).
- "Acrescenta no site o serviço de impermeabilização de laje" = adicionar_servico: escreva você a descrição curta.
- "Muda a descrição da pintura para ..." = editar_servico (nome_atual + descricao).
- Para colocar FOTO no site, ele manda a foto com a legenda "antes", "depois" ou "galeria" (explique isso se ele perguntar).
SITE:
{vitrine.para_ia()}

VISITAS (nº | situação | data hora | cliente | telefone | serviço):
{visitas.para_ia()}

OBRAS CADASTRADAS (nome | cliente | contratado | custo previsto | orçamento):
{_obras_para_ia()}

CONTAS EM ABERTO (nº | tipo | valor | vencimento | descrição | obra):
{_contas_para_ia()}

TABELA DE PREÇOS (código | serviço | unidade | preço unitário com material | palavras-chave):
{catalogo.texto_para_ia()}"""


def _mensagens(usuario, texto):
    msgs = []
    for h in db.historico_recente(usuario, 6):
        papel = "user" if h["papel"] == "user" else "assistant"
        if msgs and msgs[-1]["role"] == papel:
            msgs[-1]["content"] += "\n" + h["conteudo"]
        else:
            msgs.append({"role": papel, "content": h["conteudo"]})
    if msgs and msgs[0]["role"] == "assistant":
        msgs.pop(0)
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] += "\n" + texto
    else:
        msgs.append({"role": "user", "content": texto})
    return msgs


_AVISO_IA = {"motivo": None}      # preenchido quando o Claude falha e a IA grátis assume


def _motivo_falha(erro):
    t = str(erro).lower()
    if "credit balance" in t or "billing" in t or "402" in t:
        return "credito"
    if "authentication" in t or "api key" in t or "401" in t or "permission" in t:
        return "chave"
    return "instavel"


def _chamar_ia(usuario, texto):
    msgs = _mensagens(usuario, texto)
    _AVISO_IA["motivo"] = None
    if config.IA_PROVEDOR == "anthropic":
        try:
            return _ia_anthropic(msgs)
        except Exception as erro:
            if not config.IA_API_KEY:          # sem chave da Groq não há para onde trocar
                raise
            _AVISO_IA["motivo"] = _motivo_falha(erro)
            log.warning("Claude indisponível (%s): usando a IA grátis. Erro: %s", _AVISO_IA["motivo"], erro)
    return _ia_compativel_openai(msgs)


AVISOS_IA = {
    "credito": ("⚠️ *O crédito da Anthropic (Claude) acabou.* Continuo funcionando com a IA grátis, que pode errar um pouco mais.\n"
                "Para recarregar: platform.claude.com → Billing (Faturamento)."),
    "chave": ("⚠️ *A chave da Anthropic (Claude) não está sendo aceita.* Continuo funcionando com a IA grátis.\n"
              "Confira a variável ANTHROPIC_API_KEY no Railway."),
}


def _ia_anthropic(msgs):
    import anthropic
    cli = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = cli.messages.create(model=config.ANTHROPIC_MODEL, max_tokens=2000, system=_sistema(),
                               tools=FERRAMENTAS, tool_choice={"type": "any"}, messages=msgs)
    for bloco in resp.content:
        if bloco.type == "tool_use":
            return bloco.name, bloco.input
    texto_resp = " ".join(b.text for b in resp.content if b.type == "text")
    return "responder", {"texto": texto_resp or "Não entendi, pode repetir?"}


def _post_ia(url, headers, corpo):
    import httpx
    r = httpx.post(url, headers=headers, json=corpo, timeout=90)
    r.raise_for_status()
    return r.json()


def _ia_compativel_openai(msgs):
    """Groq (grátis com limite diário) ou outro serviço no padrão da OpenAI."""
    ferramentas = [{"type": "function", "function": {"name": f["name"], "description": f["description"],
                                                     "parameters": f["input_schema"]}} for f in FERRAMENTAS]
    corpo = {"model": config.IA_MODELO, "temperature": 0.2, "max_tokens": 2000,
             "messages": [{"role": "system", "content": _sistema()}] + msgs,
             "tools": ferramentas, "tool_choice": "required"}
    dados = _post_ia(f"{config.IA_BASE_URL.rstrip('/')}/chat/completions",
                     {"Authorization": f"Bearer {config.IA_API_KEY}"}, corpo)
    msg = dados["choices"][0]["message"]
    for chamada in msg.get("tool_calls") or []:
        fn = chamada.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            continue
        if fn.get("name") in {f["name"] for f in FERRAMENTAS}:
            return fn["name"], args
    return "responder", {"texto": (msg.get("content") or "").strip() or "Não entendi, pode repetir?"}


# ---------------------------------------------------------------- execução das ações
def _montar_item(it):
    cat = catalogo.item(it.get("codigo"))
    if cat:
        return {"codigo": cat["codigo"], "descricao": cat["servico"], "unidade": cat["unidade"],
                "quantidade": float(it["quantidade"]),
                "preco_unitario": float(it.get("preco_unitario") or cat["preco"]),
                "observacao": it.get("observacao") or ""}
    return {"codigo": "", "descricao": it.get("descricao") or "Serviço", "unidade": it.get("unidade") or "un",
            "quantidade": float(it["quantidade"]), "preco_unitario": float(it.get("preco_unitario") or 0),
            "observacao": it.get("observacao") or ""}


def _total(itens, desconto_pct):
    sub = round(sum(round(i["quantidade"] * i["preco_unitario"], 2) for i in itens), 2)
    return round(sub - round(sub * (desconto_pct or 0) / 100, 2), 2)


def _texto_orcamento(orc):
    linhas = [f"📄 *Orçamento nº {orc['id']:04d}* – {orc['cliente'] or 'Cliente'}"]
    for k, i in enumerate(orc["itens"], 1):
        aviso = "  ⚠️ sem preço na tabela – me diga o valor" if not i["preco_unitario"] else ""
        linhas.append(f"{k}. {i['descricao']}: {qtd(i['quantidade'])} {i['unidade']} × {brl(i['preco_unitario'])} = "
                      f"{brl(i['quantidade'] * i['preco_unitario'])}{aviso}")
    if orc.get("desconto_pct"):
        linhas.append(f"Desconto: {qtd(orc['desconto_pct'])}%")
    linhas.append(f"*Total: {brl(orc['total'])}*")
    linhas.append("Para corrigir, é só mandar outro áudio (ex.: \"muda a pintura para 50 metros\").")
    return "\n".join(linhas)


def _pdf(orc):
    destino = config.SAIDA_DIR / f"Orcamento_{orc['id']:04d}_{(orc['cliente'] or 'Cliente').replace(' ', '_')[:30]}.pdf"
    return gerar(orc, destino)


def executar(usuario, acao, args, texto_original):
    """Devolve uma lista de respostas: {'texto': ...} ou {'arquivo': Path, 'legenda': ..., 'mime': ...}."""
    if acao == "criar_orcamento":
        itens = [_montar_item(i) for i in args.get("itens", [])]
        desc = float(args.get("desconto_pct") or 0)
        total = _total(itens, desc)
        oid = db.salvar_orcamento(usuario, args.get("cliente") or "Cliente", args.get("endereco") or "", itens, desc,
                                  args.get("observacoes") or "", total)
        orc = db.obter_orcamento(oid)
        return [{"texto": _texto_orcamento(orc)}, {"arquivo": _pdf(orc), "legenda": f"Orçamento nº {oid:04d}"}]

    if acao == "alterar_orcamento":
        orc = db.obter_orcamento(args.get("numero"), usuario)
        if not orc:
            return [{"texto": "Não encontrei esse orçamento."}]
        itens = orc["itens"]
        for alt in args.get("alterar_itens", []) or []:
            k = int(alt["item"]) - 1
            if 0 <= k < len(itens):
                if alt.get("quantidade") is not None:
                    itens[k]["quantidade"] = float(alt["quantidade"])
                if alt.get("preco_unitario") is not None:
                    itens[k]["preco_unitario"] = float(alt["preco_unitario"])
        rem = sorted({int(r) - 1 for r in (args.get("remover_itens") or [])}, reverse=True)
        for k in rem:
            if 0 <= k < len(itens):
                itens.pop(k)
        itens += [_montar_item(i) for i in (args.get("adicionar_itens") or [])]
        cliente = args.get("cliente") or orc["cliente"]
        endereco = args.get("endereco") if args.get("endereco") is not None else orc["endereco"]
        desc = float(args["desconto_pct"]) if args.get("desconto_pct") is not None else float(orc["desconto_pct"] or 0)
        obs = args.get("observacoes") if args.get("observacoes") is not None else orc["observacoes"]
        total = _total(itens, desc)
        db.salvar_orcamento(usuario, cliente, endereco, itens, desc, obs, total, orc_id=orc["id"])
        orc = db.obter_orcamento(orc["id"])
        return [{"texto": "✏️ Orçamento atualizado.\n" + _texto_orcamento(orc)},
                {"arquivo": _pdf(orc), "legenda": f"Orçamento nº {orc['id']:04d} (atualizado)"}]

    if acao == "reenviar_orcamento":
        orc = db.obter_orcamento(args.get("numero"), usuario)
        if not orc:
            return [{"texto": "Não encontrei esse orçamento."}]
        return [{"arquivo": _pdf(orc), "legenda": f"Orçamento nº {orc['id']:04d} – {orc['cliente']}"}]

    if acao == "listar_orcamentos":
        lst = db.listar_orcamentos()
        if not lst:
            return [{"texto": "Ainda não há orçamentos."}]
        return [{"texto": "Últimos orçamentos:\n" + "\n".join(
            f"nº {o['id']:04d} – {o['cliente']} – {brl(o['total'])} ({o['criado_em'][:10]})" for o in lst)}]

    if acao == "registrar_lancamentos":
        linhas = []
        for l in args.get("lancamentos", []):
            l["obra"] = _nome_obra(l.get("obra"))
            data = l.get("data") or config.hoje().isoformat()
            db.inserir_lancamento(usuario, data, l["tipo"], float(l["valor"]), l.get("categoria"), l.get("obra"),
                                  l.get("forma_pagamento"), l.get("descricao"), texto_original)
            emoji = "🟢 Recebido" if l["tipo"] == "receita" else "🔴 Gasto"
            linhas.append(f"{emoji}: {brl(float(l['valor']))} – {financeiro.rotulo_categoria(l.get('categoria'))}"
                          f"{' – ' + l['descricao'] if l.get('descricao') else ''}"
                          f"{' – obra ' + l['obra'] if l.get('obra') else ''}"
                          f"{' (' + l['forma_pagamento'] + ')' if l.get('forma_pagamento') else ''}")
        obra = (args.get("lancamentos") or [{}])[-1].get("obra")
        extra = ""
        if obra:
            ls = db.lancamentos("2000-01-01", "2999-12-31", obra)
            e = sum(x["valor"] for x in ls if x["tipo"] == "receita"); s = sum(x["valor"] for x in ls if x["tipo"] == "despesa")
            extra = f"\nObra {obra} até agora: recebido {brl(e)}, gasto {brl(s)}, saldo {brl(e - s)}."
        obras_gasto = {l.get("obra") for l in args.get("lancamentos", []) if l.get("obra") and l["tipo"] == "despesa"}
        alertas = "".join(financeiro.alerta_obra(o) for o in obras_gasto)
        return [{"texto": "✅ Anotado!\n" + "\n".join(linhas) + extra + alertas + "\nSe errei, diga \"desfazer\"."}]

    if acao == "desfazer_ultimo_lancamento":
        l = db.excluir_ultimo_lancamento(usuario)
        if not l:
            return [{"texto": "Não há lançamento para desfazer."}]
        reaberta = db.reabrir_conta_do_lancamento(l["id"])
        return [{"texto": f"↩️ Apaguei o último lançamento: {l['tipo']} de {brl(l['valor'])} ({l['descricao'] or l['categoria']})."
                          + (f"\nA conta #{reaberta} voltou a ficar em aberto." if reaberta else "")}]

    if acao == "consultar_financeiro":
        i, f, rot = financeiro.periodo(args.get("periodo"), args.get("inicio"), args.get("fim"))
        return [{"texto": financeiro.resumo(i, f, rot, args.get("obra"), bool(args.get("detalhado")))}]

    if acao == "enviar_relatorio_excel":
        i, f, rot = financeiro.periodo(args.get("periodo"), args.get("inicio"), args.get("fim"))
        destino = config.SAIDA_DIR / f"Financeiro_{i}_a_{f}.xlsx"
        financeiro.relatorio_excel(i, f, rot, destino, args.get("obra"))
        return [{"arquivo": destino, "legenda": f"Lançamentos {rot}",
                 "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}]

    if acao == "aprovar_orcamento":
        orc = db.obter_orcamento(args.get("numero"), usuario)
        if not orc:
            return [{"texto": "Não encontrei esse orçamento."}]
        nome = _nome_obra(args.get("obra")) or orc["cliente"] or f"Orçamento {orc['id']}"
        previsto = args.get("custo_previsto")
        estimado = previsto is None
        if estimado:
            previsto = _custo_material(orc)
        db.salvar_obra(nome, cliente=orc["cliente"], orcamento_id=orc["id"], valor_contratado=orc["total"],
                       custo_previsto=previsto or None, situacao="andamento")
        linhas = [f"🤝 Orçamento nº {orc['id']:04d} aprovado! Obra *{nome}* criada.",
                  f"Valor contratado: {brl(orc['total'])}"]
        if previsto:
            linhas.append(f"Custo previsto: {brl(previsto)}" + (" (material da tabela – se for diferente, me diga o valor)" if estimado else ""))
        else:
            linhas.append("Custo previsto: não definido – diga \"o custo previsto da obra " + nome + " é X\" para eu acompanhar.")
        parcelas = args.get("parcelas") or []
        if parcelas:
            soma = 0
            linhas.append("\nParcelas a receber agendadas:")
            so_pct = all(p.get("percentual") and not p.get("valor") for p in parcelas) and \
                abs(sum(float(p["percentual"]) for p in parcelas) - 100) < 0.01
            for k, p in enumerate(parcelas, 1):
                valor = float(p.get("valor") or round(orc["total"] * float(p.get("percentual") or 0) / 100, 2))
                if so_pct and k == len(parcelas):
                    valor = round(orc["total"] - soma, 2)      # última parcela fecha o total sem diferença de centavos
                if not valor:
                    continue
                desc = p.get("descricao") or f"Parcela {k}/{len(parcelas)} – orçamento nº {orc['id']:04d}"
                cid = db.inserir_conta(usuario, "receber", valor, p["vencimento"], desc, nome, "pagamento_cliente")
                soma += valor
                linhas.append(f"#{cid} {brl(valor)} – {date.fromisoformat(p['vencimento']):%d/%m/%Y}")
            if abs(soma - orc["total"]) > 1:
                linhas.append(f"⚠️ As parcelas somam {brl(soma)}, diferente do total {brl(orc['total'])}.")
            linhas.append("Quando receber, diga \"recebi a entrada da " + nome + "\".")
        return [{"texto": "\n".join(linhas)}]

    if acao == "definir_obra":
        nome = _nome_obra(args["obra"])
        db.salvar_obra(nome, cliente=args.get("cliente"), valor_contratado=args.get("valor_contratado"),
                       custo_previsto=args.get("custo_previsto"), situacao=args.get("situacao"))
        return [{"texto": "✏️ Obra atualizada.\n" + financeiro.texto_obra(financeiro.situacao_obra(nome))}]

    if acao == "consultar_obras":
        if args.get("obra"):
            return [{"texto": financeiro.texto_obra(financeiro.situacao_obra(_nome_obra(args["obra"])))}]
        return [{"texto": financeiro.texto_obras()}]

    if acao == "agendar_contas":
        linhas = []
        for c in args.get("contas", []):
            obra = _nome_obra(c.get("obra"))
            cat = c.get("categoria") or ("pagamento_cliente" if c["tipo"] == "receber" else "outros")
            cid = db.inserir_conta(usuario, c["tipo"], float(c["valor"]), c["vencimento"], c.get("descricao"), obra, cat)
            linhas.append(financeiro.linha_conta(db.obter_conta(cid)))
        return [{"texto": "📅 Agendado! Vou te lembrar no dia.\n" + "\n".join(linhas)}]

    if acao == "quitar_contas":
        linhas, obras_gasto = [], set()
        for q in args.get("contas", []):
            c = db.obter_conta(int(q["id"]))
            if not c or c["situacao"] != "aberta":
                linhas.append(f"Conta #{q['id']} não está em aberto.")
                continue
            valor = float(q.get("valor") or c["valor"])
            tipo = "despesa" if c["tipo"] == "pagar" else "receita"
            cat = c["categoria"] or ("pagamento_cliente" if tipo == "receita" else "outros")
            lid = db.inserir_lancamento(usuario, q.get("data") or config.hoje().isoformat(), tipo, valor, cat, c["obra"],
                                        q.get("forma_pagamento"), c["descricao"], texto_original)
            db.marcar_conta(c["id"], "quitada", lid)
            linhas.append(f"{'🔴 Paga' if tipo == 'despesa' else '🟢 Recebida'}: #{c['id']} {brl(valor)} – {c['descricao'] or cat}")
            if valor < c["valor"] - 0.01:
                nid = db.inserir_conta(usuario, c["tipo"], round(c["valor"] - valor, 2), c["vencimento"],
                                       (c["descricao"] or "") + " (saldo restante)", c["obra"], c["categoria"])
                linhas.append(f"   Saldo de {brl(c['valor'] - valor)} continua em aberto (#{nid}).")
            if tipo == "despesa" and c["obra"]:
                obras_gasto.add(c["obra"])
        alertas = "".join(financeiro.alerta_obra(o) for o in obras_gasto)
        return [{"texto": "✅ Baixa feita!\n" + "\n".join(linhas) + alertas + "\nSe errei, diga \"desfazer\"."}]

    if acao == "listar_contas":
        return [{"texto": financeiro.texto_contas(args.get("filtro") or "proximas", int(args.get("dias") or 30), args.get("tipo"))}]

    if acao == "cancelar_conta":
        c = db.obter_conta(int(args["id"]))
        if not c or c["situacao"] != "aberta":
            return [{"texto": "Essa conta não está em aberto."}]
        db.marcar_conta(c["id"], "cancelada")
        return [{"texto": f"🗑️ Conta #{c['id']} cancelada ({brl(c['valor'])} – {c['descricao'] or ''})."}]

    if acao == "agenda_visitas":
        ini = date.fromisoformat(args["data_inicio"]) if args.get("data_inicio") else config.hoje()
        fim = date.fromisoformat(args["data_fim"]) if args.get("data_fim") else ini + timedelta(days=7)
        return [{"texto": visitas.texto_agenda(ini, fim)}]

    if acao == "responder_visita":
        v = visitas.obter(int(args["id"]))
        if not v or v["situacao"] in ("recusada", "cancelada"):
            return [{"texto": "Não encontrei esse pedido de visita em aberto. Diga \"minha agenda\" para ver a lista."}]
        tipo = args["acao"]
        if tipo == "confirmar":
            visitas.mudar(v["id"], "confirmada")
            return [{"texto": visitas.texto_confirmada(visitas.obter(v["id"]))}]
        if tipo == "remarcar":
            data, hora = args.get("data") or v["data"], visitas.hora_ok(args.get("hora") or v["hora"])
            try:
                visitas.remarcar(v["id"], data, hora)
            except visitas.Ocupado:
                return [{"texto": f"⚠️ {data[8:10]}/{data[5:7]} às {hora} não está livre (ocupado, bloqueado ou fora dos horários padrão)."}]
            visitas.mudar(v["id"], "confirmada")
            return [{"texto": "🔁 Remarcada.\n" + visitas.texto_confirmada(visitas.obter(v["id"]))}]
        visitas.mudar(v["id"], "recusada" if tipo == "recusar" else "cancelada", args.get("motivo"))
        return [{"texto": visitas.texto_recusada(v, args.get("motivo") or "", visitas.livres(5))}]

    if acao == "agendar_visita":
        hora = visitas.hora_ok(args.get("hora"))
        if not hora:
            return [{"texto": "Qual o horário da visita?"}]
        dia = date.fromisoformat(args["data"])
        conflito = [x for x in visitas.listar(dia, dia) if x["hora"] == hora]
        vid = visitas.criar(args["nome"], args.get("telefone") or "", args["data"], hora,
                            args.get("servico") or "", args.get("endereco") or "", "", args.get("detalhes") or "",
                            origem="whatsapp", situacao="confirmada", livre_obrigatorio=False)
        v = visitas.obter(vid)
        aviso = ("\n\n⚠️ Atenção: nesse horário já existe " + ", ".join(f"nº {x['id']} ({x['nome']})" for x in conflito) + ".") if conflito else ""
        return [{"texto": "📅 Visita marcada e horário fechado no site.\n" + visitas.texto_confirmada(v) + aviso}]

    if acao == "ajustar_agenda":
        if args["acao"] == "bloquear":
            visitas.bloquear(args["data_inicio"], args.get("data_fim"), args.get("horas"), args.get("motivo") or "")
            verbo = "🚫 Bloqueado no site"
        else:
            visitas.liberar(args["data_inicio"], args.get("data_fim"), args.get("horas"))
            verbo = "🟢 Liberado no site"
        ini = date.fromisoformat(args["data_inicio"])
        fim = date.fromisoformat(args["data_fim"]) if args.get("data_fim") else ini
        periodo = f"{ini:%d/%m}" + (f" a {fim:%d/%m}" if fim != ini else "")
        horas = ", ".join(h for h in (visitas.hora_ok(x) for x in args.get("horas") or []) if h) or "dia todo"
        conflito = [v for v in visitas.listar(ini, fim) if args["acao"] == "bloquear" and (horas == "dia todo" or v["hora"] in horas)]
        extra = ("\n⚠️ Já existe visita nesse período: " + "; ".join(f"nº {v['id']} {v['nome']} {v['data'][8:]}/{v['data'][5:7]} {v['hora']}" for v in conflito)
                 + ". Se precisar, diga \"recusar nº\" ou \"remarcar\".") if conflito else ""
        return [{"texto": f"{verbo}: {periodo} ({horas})." + extra}]

    if acao == "definir_horarios":
        norm = lambda xs: sorted({h for h in (visitas.hora_ok(x) for x in xs) if h}) if xs is not None else None
        c = visitas.salvar_cfg(semana=norm(args.get("semana")), sabado=norm(args.get("sabado")),
                               domingo=norm(args.get("domingo")), dias=args.get("dias_a_frente"))
        return [{"texto": f"⏰ Horários do site atualizados.\nSeg a sex: {', '.join(c['semana']) or 'sem visitas'}\n"
                          f"Sábado: {', '.join(c['sabado']) or 'sem visitas'}\nDomingo: {', '.join(c['domingo']) or 'sem visitas'}\n"
                          f"O cliente vê {c['dias']} dias à frente."}]

    if acao == "alterar_preco":
        antes = catalogo.item(args.get("codigo"))
        it = catalogo.alterar_preco(args.get("codigo"), args.get("mao_de_obra"), args.get("material"), args.get("preco_total"),
                                    args.get("mostrar_no_site"))
        if not it:
            return [{"texto": "Não achei esse serviço na tabela. Diga o nome como está na tabela ou abra o painel."}]
        site = " Aparece na calculadora do site." if it["site"] else ""
        return [{"texto": f"💲 {it['codigo']} – {it['servico']}: {brl(antes['preco'])} → *{brl(it['preco'])}* por {it['unidade']} "
                          f"(mão de obra {brl(it['mao_de_obra'])} + material {brl(it['material'])}).{site}"}]

    if acao == "conteudo_site":
        return vitrine.executar(usuario, args)

    if acao == "_pronto":
        return args["respostas"]

    if acao == "link_painel":
        return [{"texto": painel_link_texto()}]

    return [{"texto": args.get("texto") or "Pode repetir?"}]


def orcamento_do_painel(d: dict) -> dict:
    """Cria ou atualiza um orçamento montado na tela do painel."""
    itens = []
    for it in d.get("itens") or []:
        q = float(it.get("quantidade") or 0)
        desc = " ".join(str(it.get("descricao") or "").split())[:300]
        if q <= 0 or not desc:
            continue
        itens.append({"codigo": str(it.get("codigo") or "")[:8], "descricao": desc, "unidade": (str(it.get("unidade") or "un").strip() or "un")[:10],
                      "quantidade": q, "preco_unitario": max(0.0, round(float(it.get("preco_unitario") or 0), 2)),
                      "observacao": str(it.get("observacao") or "")[:200]})
    if not itens:
        raise ValueError("Adicione pelo menos um serviço.")
    desc_pct = min(100.0, max(0.0, float(d.get("desconto_pct") or 0)))
    orc_id = int(d["id"]) if d.get("id") else None
    if orc_id and not db.obter_orcamento(orc_id):
        orc_id = None
    oid = db.salvar_orcamento("painel", " ".join(str(d.get("cliente") or "").split())[:120] or "Cliente",
                              " ".join(str(d.get("endereco") or "").split())[:200], itens, desc_pct,
                              str(d.get("observacoes") or "").strip()[:1500], _total(itens, desc_pct), orc_id)
    return db.obter_orcamento(oid)


def _nome_obra(nome):
    """Usa o nome da obra já cadastrada quando o falado for parecido (ex.: 'Maria' -> 'Dona Maria')."""
    if not nome:
        return nome
    reg = db.obter_obra(nome)
    return reg["nome"] if reg else nome.strip()


def _custo_material(orc):
    """Estimativa do custo da obra: parte de material dos itens da tabela de preços."""
    total = 0.0
    for i in orc["itens"]:
        cat = catalogo.item(i.get("codigo"))
        if cat:
            total += cat["material"] * i["quantidade"]
    return round(total, 2)


def painel_link_texto():
    from .painel import senha_painel
    url = f"{config.PUBLIC_URL}/painel?k={senha_painel()}" if config.PUBLIC_URL else None
    if not url:
        return ("O painel está pronto, mas falta configurar a variável PUBLIC_URL com o endereço do servidor "
                "(ex.: https://seu-app.up.railway.app).")
    return (f"📊 Seu painel:\n{url}\n\nLá em cima tem as abas *Novo orçamento* (montar orçamento clicando) e *Tabela de preços*.\n"
            "Não compartilhe esse link: ele dá acesso aos seus números.")


def _ajuda():
    return (f"Oi! Sou o assistente da {config.NOME_ASSISTENTE}. Mande um áudio, por exemplo:\n"
            "🎤 \"Orçamento para a Dona Maria: pintura de 45 metros de parede e troca de 8 tomadas\"\n"
            "🎤 \"Gastei 380 de material na obra do João, no Pix\"\n"
            "🎤 \"Recebi 5 mil do João\"\n"
            "🎤 \"Quanto gastei este mês?\"  •  \"Manda a planilha do mês\"\n"
            "🎤 \"O orçamento 3 foi aprovado, 40% de entrada e o resto em 2 vezes\"\n"
            "🎤 \"Tenho um boleto de 800 da loja de material dia 15\"  •  \"O que vence esta semana?\"\n"
            "🎤 \"Quanto estou lucrando na obra do João?\"  •  \"Manda o painel\"\n"
            "🎤 \"Minha agenda da semana\"  •  \"Confirmar 12\"  •  \"Bloqueia sexta de manhã\"\n"
            "📷 Foto com a legenda \"antes\", \"depois\" ou \"galeria\" = vai para o site")


def processar(usuario, texto):
    if texto.strip().lower() in ("ajuda", "oi", "olá", "ola", "menu", "/ajuda"):
        return [{"texto": _ajuda()}]
    atalho = re.match(r"^\s*(confirmar|confirma|confirmo|recusar|recusa|recuso)\s*(?:a\s+|o\s+)?(?:visita\s+)?(?:n[ºo°.]*\s*)?#?(\d+)\s*$",
                      texto, re.IGNORECASE)
    rapido = vitrine.tratar_resposta(usuario, texto)      # "sim"/"não"/"galeria" para fotos e serviços do site
    if rapido:
        acao, args = "_pronto", {"respostas": rapido}
    elif atalho:                     # resposta rápida ao aviso de pedido, sem gastar IA
        acao, args = "responder_visita", {"id": int(atalho.group(2)),
                                          "acao": "confirmar" if atalho.group(1).lower().startswith("confirm") else "recusar"}
    else:
        acao, args = _chamar_ia(usuario, texto)
    respostas = executar(usuario, acao, args, texto)
    novos = visitas.avisos_pendentes()      # pedidos do site que chegaram enquanto o WhatsApp estava fora da janela
    if novos:
        respostas.append({"texto": novos})
    # avisa (uma vez por dia) quando o Claude ficou sem crédito ou com chave errada e a IA grátis assumiu
    motivo = _AVISO_IA["motivo"]
    if motivo in AVISOS_IA and db.ajuste(f"aviso_ia:{motivo}") != config.hoje().isoformat():
        db.gravar_ajuste(f"aviso_ia:{motivo}", config.hoje().isoformat())
        respostas.append({"texto": AVISOS_IA[motivo]})
    # uma vez por dia, na primeira conversa, lembra das contas vencidas/do dia e obras estouradas
    chave = f"lembrete_conversa:{usuario}"
    if acao != "listar_contas" and db.ajuste(chave) != config.hoje().isoformat():
        aviso, _ = financeiro.lembrete()
        if acao not in ("agenda_visitas", "responder_visita"):
            aviso = "\n\n".join(t for t in (visitas.resumo_hoje(), aviso) if t)
        db.gravar_ajuste(chave, config.hoje().isoformat())
        if aviso:
            respostas.append({"texto": aviso})
    db.salvar_historico(usuario, "user", texto)
    resumo = " | ".join(r["texto"][:600] for r in respostas if "texto" in r) or f"(enviei {acao})"
    db.salvar_historico(usuario, "assistant", resumo)
    return respostas
