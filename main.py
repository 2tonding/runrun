import os
import json
import httpx
import redis
import secrets
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from anthropic import Anthropic

# ============================================================
# CONFIGURAÇÃO
# ============================================================
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")
ZAPI_INSTANCE_ID    = os.environ.get("ZAPI_INSTANCE_ID")
ZAPI_TOKEN          = os.environ.get("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN   = os.environ.get("ZAPI_CLIENT_TOKEN")
REDIS_URL           = os.environ.get("REDIS_URL")
ADMIN_USER          = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS          = os.environ.get("ADMIN_PASS", "trocame123")

client = Anthropic(api_key=ANTHROPIC_API_KEY)
app    = FastAPI()
security = HTTPBasic()

def verificar_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verifica login e senha das rotas administrativas."""
    usuario_ok = secrets.compare_digest(credentials.username.encode(), ADMIN_USER.encode())
    senha_ok   = secrets.compare_digest(credentials.password.encode(), ADMIN_PASS.encode())
    if not (usuario_ok and senha_ok):
        raise HTTPException(
            status_code=401,
            detail="Acesso negado",
            headers={"WWW-Authenticate": "Basic"}
        )
    return credentials.username

# ============================================================
# CONEXÃO COM REDIS
# O histórico de cada aluno fica salvo pelo número de telefone.
# Nunca se perde, mesmo se o servidor reiniciar.
# ============================================================
r = redis.from_url(REDIS_URL, decode_responses=True)

# ============================================================
# SYSTEM PROMPT — Personalidade e protocolo do Coach Run
# ============================================================
SYSTEM_PROMPT = """
Você é o Coach Run, um treinador de corrida especialista com mais de 15 anos de experiência.
Você combina rigor científico com comunicação acessível, motivadora e humana.
Você fala de forma direta e prática, como um amigo que entende muito de corrida.

REGRAS ABSOLUTAS DE SEGURANÇA:
- Nunca ignore relatos de dor. Se o aluno mencionar dor, oriente a buscar avaliação médica.
- Nunca monte planilha sem fazer a anamnese completa primeiro.
- Nunca aumente o volume semanal em mais de 10% de uma semana para outra.
- Nunca substitua avaliação médica. Em caso de dúvidas de saúde, sempre oriente a consultar um profissional.
- Se o aluno relatar sintomas cardíacos (dor no peito, falta de ar desproporcional, palpitações), interrompa e oriente buscar atendimento médico imediatamente.

FLUXO DE ATENDIMENTO:

1. BOAS-VINDAS E ANAMNESE
Na primeira mensagem, apresente-se e explique que faremos uma anamnese — uma conversa estruturada
para entender o perfil completo do aluno antes de qualquer planilha. Faça UMA pergunta por vez.

Perguntas da anamnese (em ordem, uma por vez):
- Qual é o seu objetivo principal com a corrida?
- Se for prova: qual distância e tem data definida?
- Qual resultado quer alcançar? (só completar, tempo específico?)
- Há quanto tempo corre? (nunca / menos de 6 meses / 6 meses a 2 anos / mais de 2 anos)
- Quantos km corre por semana atualmente?
- Qual é seu pace atual em corridas fáceis (pace que consegue conversar)?
- Quantos dias por semana pode treinar?
- Quanto tempo disponível por treino (em minutos)?
- Tem acesso a pista, parque, esteira ou corre só na rua?
- Tem alguma lesão ativa ou recorrente?
- Tem alguma condição de saúde com restrição médica?
- Faz musculação ou treino de força complementar?

2. ZONAS DE TREINO — OBRIGATÓRIO ANTES DA PLANILHA
Antes de qualquer planilha, as zonas de treino precisam ser estabelecidas.
Se o aluno não tem referência de pace ou frequência cardíaca, prescreva um teste:
- Iniciantes: Teste de 2km (correr 2km no máximo esforço sustentável e registrar o tempo)
- Intermediários/Avançados: Teste de Cooper (correr o máximo em 12 minutos e registrar a distância)

Após o teste, calcule e apresente as zonas personalizadas em formato claro:
🎯 SUAS ZONAS DE TREINO
Z1 — Recuperação: pace > X:XX/km
Z2 — Aeróbico fácil: X:XX – X:XX/km
Z3 — Moderado: X:XX – X:XX/km
Z4 — Limiar: X:XX – X:XX/km
Z5 — Máximo: pace < X:XX/km

3. PLANO E ENTREGA SEMANAL
Após a anamnese e as zonas estabelecidas, monte internamente o plano completo (macrociclo de 8 a 24 semanas).
MAS entregue APENAS a semana atual ao aluno. Nunca entregue o plano inteiro.
Mencione o horizonte para criar expectativa: "Essa é sua Semana 1 de 16."

Formato de entrega da semana:
📅 SEMANA X — [Fase] | Volume: XX km
[dia]: [tipo de treino] — [distância/duração] em [zona] (pace: X:XX/km)
💡 Dica da semana: [insight específico]

4. ACOMPANHAMENTO CONTÍNUO
A cada semana, pergunte como foram os treinos antes de entregar a próxima semana.
Ajuste a planilha com base no feedback. Monitore sinais de overtraining:
- Treinos fáceis parecendo difíceis
- Cansaço persistente
- Falta de motivação
- Dores que não passam

5. RETESTES PERIÓDICOS
Proponha novo teste a cada 4-6 semanas, na transição entre fases, ou quando o aluno demonstrar
evolução significativa. Contextualize sempre: explique por que o reteste é importante naquele momento.

PROTOCOLOS DE TREINAMENTO:
- Distribuição 80/20: 80% do volume em Z1/Z2, 20% em Z3-Z5
- Regra dos 10%: nunca aumentar volume total em mais de 10% por semana
- Ciclo 3:1: 3 semanas de carga, 1 semana de recuperação (reduzir 20-30% do volume)
- Longão: 1x por semana, 25-35% do volume semanal, sempre em Z1/Z2
- Treino de limiar (Tempo Run): 1x por semana a partir do nível intermediário
- Intervalados: 1x por semana, nunca dois dias consecutivos de treino intenso
- Strides: 4-8x de 20 segundos ao final de corridas fáceis, 2x por semana

TOM E FORMATO PARA WHATSAPP:
- Mensagens curtas e diretas — WhatsApp não é lugar para parágrafos longos
- Use emojis com moderação para facilitar a leitura 🏃
- Faça apenas UMA pergunta por mensagem
- Quando entregar a planilha semanal, formate de forma clara e escaneável
- Celebre conquistas do aluno, mesmo as pequenas
"""

# ============================================================
# FUNÇÕES DE HISTÓRICO COM REDIS
# ============================================================

HISTORICO_LIMITE = 40  # máximo de mensagens guardadas por aluno

def obter_historico(telefone: str) -> list:
    """Busca o histórico do aluno no Redis."""
    dados = r.get(f"historico:{telefone}")
    if not dados:
        return []
    historico = json.loads(dados)
    return historico[-HISTORICO_LIMITE:]


def salvar_historico(telefone: str, historico: list):
    """Salva o histórico do aluno no Redis. Sem expiração — guarda para sempre."""
    r.set(f"historico:{telefone}", json.dumps(historico))


def salvar_mensagem(telefone: str, role: str, conteudo: str):
    """Adiciona uma mensagem ao histórico do aluno no Redis."""
    historico = obter_historico(telefone)
    historico.append({"role": role, "content": conteudo})
    salvar_historico(telefone, historico)


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

async def enviar_whatsapp(telefone: str, mensagem: str):
    """Envia mensagem de volta para o aluno via Z-API."""
    # Corrige o número brasileiro — adiciona o 9 após o DDD se necessário
    numero_limpo = telefone.replace("+", "").replace("-", "").replace(" ", "")
    if numero_limpo.startswith("55") and len(numero_limpo) == 12:
        numero_limpo = numero_limpo[:4] + "9" + numero_limpo[4:]

    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
    headers = {
        "Content-Type": "application/json",
        "Client-Token": ZAPI_CLIENT_TOKEN
    }
    payload = {
        "phone": numero_limpo,
        "message": mensagem
    }
    print(f"ENVIANDO para {numero_limpo}")
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(url, headers=headers, json=payload)
        print(f"Z-API STATUS: {response.status_code} | {response.text}")


async def chamar_claude(telefone: str, mensagem_usuario: str) -> str:
    """Envia o histórico + nova mensagem para o Claude e retorna a resposta."""
    salvar_mensagem(telefone, "user", mensagem_usuario)
    historico = obter_historico(telefone)

    resposta = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=historico
    )

    texto_resposta = resposta.content[0].text
    salvar_mensagem(telefone, "assistant", texto_resposta)
    return texto_resposta


# ============================================================
# ROTAS
# ============================================================

@app.get("/")
def status():
    """Rota de verificação — confirma que o servidor está no ar."""
    return {"status": "Coach Run online 🏃"}


@app.get("/alunos")
def listar_alunos(admin: str = Depends(verificar_admin)):
    """Lista todos os alunos que já conversaram com o Coach Run."""
    chaves = r.keys("historico:*")
    alunos = []
    for chave in chaves:
        telefone = chave.replace("historico:", "")
        historico = obter_historico(telefone)
        total_mensagens = len(historico)
        ultima_mensagem = historico[-1]["content"][:60] + "..." if historico else ""
        alunos.append({
            "telefone": telefone,
            "total_mensagens": total_mensagens,
            "ultima_mensagem": ultima_mensagem
        })
    return {"total_alunos": len(alunos), "alunos": alunos}


@app.get("/historico/{telefone}")
def ver_historico(telefone: str, admin: str = Depends(verificar_admin)):
    """Retorna o histórico completo de conversa de um aluno."""
    historico = obter_historico(telefone)
    if not historico:
        return {"erro": "Aluno não encontrado ou sem histórico"}
    return {
        "telefone": telefone,
        "total_mensagens": len(historico),
        "conversa": historico
    }


@app.delete("/historico/{telefone}")
def apagar_historico(telefone: str, admin: str = Depends(verificar_admin)):
    """Apaga o histórico de um aluno — útil para resetar a conversa."""
    r.delete(f"historico:{telefone}")
    return {"status": "ok", "mensagem": f"Histórico de {telefone} apagado."}


@app.post("/webhook")
async def webhook(request: Request):
    """Recebe as mensagens do WhatsApp via Z-API."""
    try:
        dados = await request.json()

        if dados.get("type") != "ReceivedCallback":
            return {"status": "ignorado"}

        if dados.get("fromMe"):
            return {"status": "ignorado"}

        if dados.get("isGroup"):
            return {"status": "ignorado"}

        telefone = dados.get("phone", "")
        texto    = dados.get("text", {}).get("message", "")

        if not telefone or not texto:
            return {"status": "ignorado"}

        print(f"Mensagem de {telefone}: {texto}")

        resposta = await chamar_claude(telefone, texto)
        await enviar_whatsapp(telefone, resposta)

        print(f"Resposta enviada para {telefone}")
        return {"status": "ok"}

    except Exception as e:
        print(f"ERRO: {e}")
        return {"status": "erro", "detalhe": str(e)}
