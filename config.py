"""Configurações lidas das variáveis de ambiente (arquivo .env no servidor)."""
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent

# carrega o arquivo .env (se existir) para rodar no computador; no servidor as variáveis já vêm configuradas
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _linha in _env_file.read_text(encoding="utf-8").splitlines():
        _linha = _linha.strip()
        if _linha and not _linha.startswith("#") and "=" in _linha:
            _k, _v = _linha.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())


def _env(nome, padrao=""):
    v = os.environ.get(nome, padrao).strip()
    return padrao if v.startswith("cole_aqui") else v      # ignora os exemplos do .env.example


# --- WhatsApp Cloud API (Meta)
WHATSAPP_TOKEN = _env("WHATSAPP_TOKEN")            # token de acesso (temporário ou permanente)
PHONE_NUMBER_ID = _env("PHONE_NUMBER_ID")          # ID do número que envia (número de teste ou o seu)
VERIFY_TOKEN = _env("VERIFY_TOKEN", "tajima-teste")  # palavra-senha que você escolhe para o webhook
APP_SECRET = _env("APP_SECRET")                    # chave secreta do app (para conferir a assinatura)
GRAPH_VERSION = _env("GRAPH_VERSION", "v23.0")

# --- Quem pode usar o assistente (números com DDI e DDD, separados por vírgula)
ALLOWED_NUMBERS = [n for n in _env("ALLOWED_NUMBERS").replace(" ", "").split(",") if n]

# --- Inteligência artificial
# IA_PROVEDOR = "anthropic" (Claude, pago por uso) ou "groq" (camada gratuita, com limite diário).
# Se não for informado: usa Claude quando houver ANTHROPIC_API_KEY; senão, Groq.
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-haiku-5-5")
IA_PROVEDOR = _env("IA_PROVEDOR", "anthropic" if ANTHROPIC_API_KEY else "groq").lower()
IA_BASE_URL = _env("IA_BASE_URL", "https://api.groq.com/openai/v1")   # qualquer serviço compatível com a API da OpenAI
IA_MODELO = _env("IA_MODELO", "openai/gpt-oss-120b")

# --- Transcrição de áudio (qualquer serviço compatível com a API da OpenAI: Groq, OpenAI...)
STT_API_KEY = _env("STT_API_KEY")
STT_BASE_URL = _env("STT_BASE_URL", "https://api.groq.com/openai/v1")
STT_MODEL = _env("STT_MODEL", "whisper-large-v3-turbo")
IA_API_KEY = _env("IA_API_KEY", STT_API_KEY)          # no Groq, a mesma chave serve para áudio e IA

# --- Dados
DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "dados")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "assistente.db"
SAIDA_DIR = DATA_DIR / "arquivos"
SAIDA_DIR.mkdir(parents=True, exist_ok=True)
# PERFIL = nome da pasta em clientes/ com o logo.jpg e o catalogo.csv daquela empresa.
# Sem PERFIL, usa a pasta data/ (Tajima Service).
PERFIL = _env("PERFIL")
PASTA_PERFIL = BASE_DIR / "clientes" / PERFIL if PERFIL else BASE_DIR / "data"
if PERFIL and not PASTA_PERFIL.is_dir():
    raise RuntimeError(f"PERFIL '{PERFIL}' não encontrado: crie a pasta clientes/{PERFIL}")
CATALOGO_CSV = Path(_env("CATALOGO_CSV", str(PASTA_PERFIL / "catalogo.csv")))
LOGO = Path(_env("LOGO", str(PASTA_PERFIL / "logo.jpg")))

# --- Dados da empresa (aparecem no PDF do orçamento)
EMPRESA = _env("EMPRESA", "Tajima Service – Reparos e Reformas")
TELEFONE = _env("TELEFONE", "(11) 97785-3860")
EMAIL = _env("EMAIL", "tajimaservice@outlook.com.br")
INSTAGRAM = _env("INSTAGRAM", "@tajimaservice")
CNPJ = _env("CNPJ")                                   # opcional; aparece no PDF se preenchido
RAMO = _env("RAMO", "reparos e reformas")             # tipo de serviço da empresa (ajuda a IA)
NOME_ASSISTENTE = _env("NOME_ASSISTENTE", "Tajima Service")  # nome curto usado nas mensagens
COR_PRINCIPAL = _env("COR_PRINCIPAL", "#0A1F5C")      # cores do PDF (código hexadecimal)
COR_DESTAQUE = _env("COR_DESTAQUE", "#0B8FDB")
VALIDADE_DIAS = int(_env("VALIDADE_DIAS", "15"))
CONDICOES_PAGAMENTO = _env(
    "CONDICOES_PAGAMENTO",
    "40% de entrada na aprovação e saldo em parcelas conforme o andamento da obra, com a última na entrega.",
)

# --- Fuso horário (o servidor roda em UTC; as datas seguem o horário de Brasília)
FUSO = ZoneInfo(_env("FUSO", "America/Sao_Paulo"))


def agora() -> datetime:
    return datetime.now(FUSO).replace(tzinfo=None)


def hoje() -> date:
    return agora().date()


# --- Gestão financeira
ALERTA_PCT = float(_env("ALERTA_PCT", "80"))          # avisa quando o gasto da obra passa deste % do custo previsto
HORA_LEMBRETE = int(_env("HORA_LEMBRETE", "8"))       # hora do resumo diário de contas (0 a 23; -1 desliga)
TEMPLATE_LEMBRETE = _env("TEMPLATE_LEMBRETE")         # nome do modelo aprovado na Meta (para lembrar fora da janela de 24 h)
TEMPLATE_IDIOMA = _env("TEMPLATE_IDIOMA", "pt_BR")

# --- Agenda de visitas (site)
TEMPLATE_VISITA = _env("TEMPLATE_VISITA")             # modelo aprovado na Meta para avisar pedido do site fora da janela de 24 h
# endereços do site que podem consultar a agenda (separados por vírgula); vazio = qualquer site
SITE_URL = _env("SITE_URL").rstrip("/")             # endereço do site, para as mensagens ("já aparece em ...")
SITE_ORIGENS = [o.rstrip("/") for o in _env("SITE_ORIGENS").replace(" ", "").split(",") if o]

# --- Painel no navegador
PAINEL_SENHA = _env("PAINEL_SENHA")                   # se vazio, o assistente cria uma senha e manda junto com o link
_dominio = _env("RAILWAY_PUBLIC_DOMAIN")              # o Railway preenche sozinho quando você gera o domínio
PUBLIC_URL = _env("PUBLIC_URL", f"https://{_dominio}" if _dominio else "").rstrip("/")


def chave_numero(n: str) -> str:
    """Normaliza números do Brasil: DDD + últimos 8 dígitos (o WhatsApp às vezes tira o 9)."""
    d = "".join(ch for ch in (n or "") if ch.isdigit())
    if d.startswith("55") and len(d) >= 12:
        return d[2:4] + d[-8:]
    return d


def autorizado(numero: str) -> bool:
    if not ALLOWED_NUMBERS:
        return True
    return chave_numero(numero) in {chave_numero(n) for n in ALLOWED_NUMBERS}
