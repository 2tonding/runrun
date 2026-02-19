import os
import json
import httpx
from fastapi import FastAPI, Request
from anthropic import Anthropic

# ============================================================
# CONFIGURAÇÃO
# ============================================================
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ZAPI_INSTANCE_ID = os.environ.get("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.environ.get("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.environ.get("ZAPI_CLIENT_TOKEN")

client = Anthropic(api_key=ANTHROPIC_API_KEY)
app = FastAPI()

# ============================================================
# MEMÓRIA DAS CONVERSAS
# Guarda o histórico de cada aluno pelo número de telefone.
# Em produção, substitua por um banco de dados (Redis ou PostgreSQL).
# ============================================================
conversas: dict[str, list] = {}

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
# FUNÇÕES AUXILIARES
# ============================================================

def obter_historico(telefone: str) -> list:
    """Retorna o histórico de conversa do aluno. Limita a 40 mensagens para não estourar o contexto."""
    if telefone not in conversas:
        conversas[telefone] = []
    return conversas[telefone][-40:]


def salvar_mensagem(telefone: str, role: str, conteudo: str):
    """Salva uma mensagem no histórico do aluno."""
    if telefone not in conversas:
        conversas[telefone] = []
    conversas[telefone].append({"role": role, "content": conteudo})


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
        model="claude-opus-4-6",
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


@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        print(f"DADOS RECEBIDOS: {dados}")

        if dados.get("type") != "ReceivedCallback":
            print(f"IGNORADO - tipo: {dados.get('type')}")
            return {"status": "ignorado"}

        if dados.get("fromMe"):
            print("IGNORADO - fromMe")
            return {"status": "ignorado"}

        if dados.get("isGroup"):
            print("IGNORADO - grupo")
            return {"status": "ignorado"}

        telefone = dados.get("phone", "")
        texto = dados.get("text", {}).get("message", "")
        print(f"TELEFONE: {telefone} | TEXTO: {texto}")

        if not telefone or not texto:
            print("IGNORADO - sem telefone ou texto")
            return {"status": "ignorado"}

        print(f"CHAMANDO CLAUDE para {telefone}")
        resposta = await chamar_claude(telefone, texto)
        print(f"RESPOSTA CLAUDE: {resposta[:100]}")

        await enviar_whatsapp(telefone, resposta)
        print(f"MENSAGEM ENVIADA para {telefone}")

        return {"status": "ok"}

    except Exception as e:
        print(f"ERRO: {e}")
        return {"status": "erro", "detalhe": str(e)}
