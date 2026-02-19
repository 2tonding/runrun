import os
import json
import httpx
import redis
import secrets
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
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

client   = Anthropic(api_key=ANTHROPIC_API_KEY)
app      = FastAPI()
security = HTTPBasic()

# ============================================================
# AUTENTICAÇÃO
# ============================================================

def verificar_admin(credentials: HTTPBasicCredentials = Depends(security)):
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
# ============================================================
r = redis.from_url(REDIS_URL, decode_responses=True)

# ============================================================
# SYSTEM PROMPT
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
# LAYOUT BASE DO PAINEL
# ============================================================
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Arial, sans-serif; background: #f0f2f5; color: #333; }
header { background: #1a1a2e; color: white; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
header h1 { font-size: 18px; }
.container { max-width: 800px; margin: 30px auto; padding: 0 20px; }
.card { background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
.card h2 { font-size: 16px; margin-bottom: 16px; color: #555; }
a { color: #4f46e5; text-decoration: none; }
a:hover { text-decoration: underline; }
.badge { display: inline-block; background: #e0e7ff; color: #4f46e5; border-radius: 20px; padding: 2px 10px; font-size: 12px; margin-left: 8px; }
.aluno-row { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid #f0f0f0; }
.aluno-row:last-child { border-bottom: none; }
.aluno-info { font-size: 12px; color: #999; margin-top: 4px; max-width: 480px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.btn { display: inline-block; padding: 6px 14px; border-radius: 8px; font-size: 13px; cursor: pointer; border: none; text-decoration: none; }
.btn-danger { background: #fee2e2; color: #dc2626; }
.btn-danger:hover { background: #fecaca; text-decoration: none; }
.back { display: inline-block; margin-bottom: 16px; font-size: 14px; }
.total { font-size: 13px; color: #888; margin-bottom: 16px; }
.chat { display: flex; flex-direction: column; gap: 10px; }
.msg { display: flex; flex-direction: column; max-width: 80%; }
.msg.aluno { align-self: flex-end; align-items: flex-end; }
.msg.bot { align-self: flex-start; align-items: flex-start; }
.label { font-size: 11px; color: #aaa; margin-bottom: 3px; padding: 0 6px; }
.balao { padding: 10px 14px; border-radius: 16px; font-size: 14px; line-height: 1.6; }
.aluno .balao { background: #dcf8c6; border-bottom-right-radius: 4px; }
.bot .balao { background: #f8f8f8; border-bottom-left-radius: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.08); }
"""

def base_html(titulo: str, conteudo: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{titulo} — Coach Run</title>
    <style>{CSS}</style>
</head>
<body>
    <header>
        <span>🏃</span>
        <h1>Coach Run — Painel Admin</h1>
    </header>
    <div class="container">
        {conteudo}
    </div>
</body>
</html>"""

# ============================================================
# FUNÇÕES DE HISTÓRICO COM REDIS
# ============================================================

HISTORICO_LIMITE = 40

def obter_historico(telefone: str) -> list:
    dados = r.get(f"historico:{telefone}")
    if not dados:
        return []
    return json.loads(dados)[-HISTORICO_LIMITE:]

def salvar_historico(telefone: str, historico: list):
    r.set(f"historico:{telefone}", json.dumps(historico))

def salvar_mensagem(telefone: str, role: str, conteudo: str):
    historico = obter_historico(telefone)
    historico.append({"role": role, "content": conteudo})
    salvar_historico(telefone, historico)

# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

async def enviar_whatsapp(telefone: str, mensagem: str):
    numero_limpo = telefone.replace("+", "").replace("-", "").replace(" ", "")
    if numero_limpo.startswith("55") and len(numero_limpo) == 12:
        numero_limpo = numero_limpo[:4] + "9" + numero_limpo[4:]

    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
    headers = {"Content-Type": "application/json", "Client-Token": ZAPI_CLIENT_TOKEN}
    payload = {"phone": numero_limpo, "message": mensagem}

    print(f"ENVIANDO para {numero_limpo}")
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(url, headers=headers, json=payload)
        print(f"Z-API STATUS: {response.status_code} | {response.text}")

async def chamar_claude(telefone: str, mensagem_usuario: str) -> str:
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
# ROTAS PÚBLICAS
# ============================================================

@app.get("/")
def status():
    return {"status": "Coach Run online 🏃"}

# ============================================================
# ROTAS ADMINISTRATIVAS — protegidas com login e senha
# ============================================================

@app.get("/admin", response_class=HTMLResponse)
def painel_admin(admin: str = Depends(verificar_admin)):
    """Painel principal — lista todos os alunos."""
    chaves = r.keys("historico:*")
    rows = ""
    for chave in sorted(chaves):
        telefone = chave.replace("historico:", "")
        historico = obter_historico(telefone)
        total = len(historico)
        ultima = historico[-1]["content"][:80] + "..." if historico else "—"
        rows += f"""
        <div class="aluno-row">
            <div>
                <div>
                    <a href="/admin/conversa/{telefone}">📱 {telefone}</a>
                    <span class="badge">{total} msgs</span>
                </div>
                <div class="aluno-info">{ultima}</div>
            </div>
            <a href="/admin/apagar/{telefone}" onclick="return confirm('Apagar histórico de {telefone}?')">
                <span class="btn btn-danger">🗑 Apagar</span>
            </a>
        </div>"""

    if not rows:
        rows = "<p style='color:#888;padding:20px 0'>Nenhum aluno ainda.</p>"

    conteudo = f"""
    <div class="card">
        <h2>👥 Alunos ({len(chaves)} total)</h2>
        {rows}
    </div>"""

    return HTMLResponse(base_html("Alunos", conteudo))


@app.get("/admin/conversa/{telefone}", response_class=HTMLResponse)
def ver_conversa(telefone: str, admin: str = Depends(verificar_admin)):
    """Visualiza a conversa completa de um aluno no estilo WhatsApp."""
    historico = obter_historico(telefone)

    if not historico:
        conteudo = f"""
        <a class="back" href="/admin">← Voltar</a>
        <div class="card"><p>Nenhuma conversa encontrada para {telefone}.</p></div>"""
        return HTMLResponse(base_html(telefone, conteudo))

    msgs = ""
    for msg in historico:
        role = msg["role"]
        texto = msg["content"].replace("\n", "<br>")
        if role == "user":
            msgs += f"""
            <div class="msg aluno">
                <div class="label">👤 Aluno</div>
                <div class="balao">{texto}</div>
            </div>"""
        else:
            msgs += f"""
            <div class="msg bot">
                <div class="label">🏃 Coach Run</div>
                <div class="balao">{texto}</div>
            </div>"""

    conteudo = f"""
    <a class="back" href="/admin">← Voltar para lista de alunos</a>
    <div class="card">
        <h2>💬 Conversa com {telefone}</h2>
        <div class="total">{len(historico)} mensagens</div>
        <div class="chat">{msgs}</div>
    </div>"""

    return HTMLResponse(base_html(telefone, conteudo))


@app.get("/admin/apagar/{telefone}")
def apagar_historico(telefone: str, admin: str = Depends(verificar_admin)):
    """Apaga o histórico de um aluno e volta para o painel."""
    r.delete(f"historico:{telefone}")
    return RedirectResponse(url="/admin")

# ============================================================
# WEBHOOK — recebe mensagens do WhatsApp
# ============================================================

@app.post("/webhook")
async def webhook(request: Request):
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
