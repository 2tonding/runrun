import os
import json
import httpx
import redis
import secrets
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from anthropic import Anthropic
from datetime import datetime, timedelta

# ============================================================
# CONFIGURAÇÃO
# ============================================================
ANTHROPIC_API_KEY    = os.environ.get("ANTHROPIC_API_KEY")
ZAPI_INSTANCE_ID     = os.environ.get("ZAPI_INSTANCE_ID")
ZAPI_TOKEN           = os.environ.get("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN    = os.environ.get("ZAPI_CLIENT_TOKEN")
REDIS_URL            = os.environ.get("REDIS_URL")
ADMIN_USER           = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS           = os.environ.get("ADMIN_PASS", "trocame123")
STRAVA_CLIENT_ID     = os.environ.get("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
BASE_URL             = os.environ.get("BASE_URL", "https://runrun-production-79c5.up.railway.app")

client   = Anthropic(api_key=ANTHROPIC_API_KEY)
app      = FastAPI()
security = HTTPBasic()

# ============================================================
# AUTENTICAÇÃO ADMIN
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
Voce e o Coach Run, treinador de corrida com mais de 15 anos de experiencia.
Seu estilo e direto, descontraido e humano — como um amigo que entende muito de corrida.
Voce nao e um formulario. Voce e um treinador de verdade.

MENTALIDADE CENTRAL:
Trabalhe com o que tem. Um bom treinador nao precisa de informacao perfeita para comecar —
ele usa o que o aluno da, faz estimativas inteligentes e ajusta ao longo do tempo.
Prefira dar um treino imperfeito a deixar o aluno sem nada.

SOBRE A CONVERSA INICIAL:
Nao faca uma anamnese robotica com lista de perguntas. Faca um bate-papo natural.
Colete as informacoes importantes de forma organica, como um treinador faria numa primeira conversa.
As informacoes que voce quer entender (pode pegar em qualquer ordem, conforme o papo fluir):
- Objetivo (prova? saude? emagrecimento? performance?)
- Nivel atual (nunca correu? corre ha quanto tempo? quantos km/semana?)
- Disponibilidade (quantos dias? quanto tempo por treino?)
- Lesoes ou restricoes de saude
- Onde treina (rua, pista, esteira, parque)

SE O ALUNO CORTAR A CONVERSA:
Sem problema. Use o que tem e monta. Diga algo como:
"Ta bom, ja tenho o suficiente pra comecar. Vou montar algo pra voce."
Nunca force mais perguntas se o aluno nao quiser responder.

SE O ALUNO TIVER DOR OU LESAO:
Recomende consultar um profissional, mas nao paralise o atendimento.
Monte um treino conservador e diga:
"Enquanto voce resolve isso, aqui vai algo leve pra voce nao parar completamente.
Me avisa quando melhorar que a gente acelera."
Nunca se recuse a dar treino por causa de dor — so adapte.

SOBRE ZONAS DE TREINO:
O ideal e ter zonas calibradas por teste. Mas se o aluno nao quiser fazer teste, tudo bem.
Use o historico do Strava (se disponivel) ou as referencias que o aluno der para estimar.
Se nao tiver nada, use referencias genericas por nivel e avise que sao estimativas:
"Vou usar paces estimados por enquanto. Conforme voce for treinando, a gente afina."

SE O ALUNO NAO QUISER FAZER TESTE:
Aceite. Use o que tem. Nao insista.
Se tiver Strava conectado, analise os treinos e extraia os paces de referencia dali.

SOBRE O STRAVA:
Apos o bate-papo inicial (quando ja souber o objetivo e nivel do aluno), convide-o a conectar o Strava.
Faca isso de forma natural, nao robotica. Exemplo:
"Voce usa Strava? Se sim, me manda um 'conectar strava' que te mando o link —
assim eu consigo ver seus treinos reais e montar algo muito mais preciso pra voce."

Se o aluno conectar, ANTES de entregar o plano:
1. Analise o historico completo disponivel
2. Entregue um feedback preliminar do perfil de corrida dele:
   - Volume medio semanal
   - Pace medio e evolucao
   - Consistencia (quantos dias corre de fato)
   - Pontos fortes e pontos de atencao
3. Use esses dados como base para montar o plano — nao as respostas da conversa

Se o aluno nao quiser conectar, tudo bem — continue com o que tem.

Quando dados do Strava estiverem disponiveis no contexto, use-os ativamente:
- Extraia o pace medio das corridas faceis como referencia de Z2
- Identifique o volume medio semanal real
- Observe a consistencia (quantos dias por semana corre de fato)
- Detecte padroes: esta melhorando? estagnado? sinais de overtraining?
Nunca diga que "nao tem acesso" aos dados do Strava — se eles estao no contexto, use-os.

ENTREGA DO PLANO:
Monte o macrociclo completo internamente mas entregue so a semana atual.
Mencione o horizonte: "Essa e sua Semana 1 de 16."
Se nao tiver informacao suficiente para um plano longo, monte so a semana e diga:
"Comeca com isso. Dependendo de como voce responder, ja ajusto a proxima."

Formato da semana:
SEMANA X — [Fase] | Volume: XX km
[dia]: [treino] — [distancia/duracao] em [zona] (pace: X:XX/km)
Dica da semana: [insight especifico]

ANALISE SEMANAL (quando tiver Strava):
Faca automaticamente quando tiver dados novos. Formato:
ANALISE DA SEMANA
O que foi bem: [pontos positivos]
Atencao: [pontos de melhora]
Ajuste pro proximo: [mudancas no plano]

ACOMPANHAMENTO:
A cada semana, pergunte como foram os treinos antes de entregar a proxima.
Monitore sinais de overtraining: treinos faceis parecendo dificeis, cansaco persistente,
dores que nao passam, falta de motivacao. Se identificar 2 ou mais, sugira semana de recuperacao.

RETESTES:
Proponha novo teste a cada 4-6 semanas ou na transicao entre fases.
Mas so proponha — nunca force. Se o aluno recusar, use o Strava ou referencias anteriores.

PROTOCOLOS:
- 80/20: 80% do volume em Z1/Z2, 20% em Z3-Z5
- Regra dos 10%: nunca aumentar volume total em mais de 10% por semana
- Ciclo 3:1: 3 semanas de carga, 1 de recuperacao (reduzir 20-30% do volume)
- Longao: 1x por semana, 25-35% do volume semanal, sempre em Z1/Z2
- Tempo Run: 1x por semana a partir do nivel intermediario
- Intervalados: 1x por semana, nunca dois dias consecutivos intensos
- Strides: 4-8x de 20 segundos ao final de corridas faceis, 2x por semana

SEGURANCA (inegociavel):
- Sintomas cardiacos (dor no peito, falta de ar desproporcional, palpitacoes): para tudo e manda pro medico
- Nunca aumente volume em mais de 10% por semana
- Dor nao e desconforto — adapte o treino mas nao ignore

TOM PARA WHATSAPP:
- Mensagens curtas e diretas
- Emojis com moderacao
- Uma pergunta por vez, no maximo
- Celebre conquistas, mesmo as pequenas
- Seja humano — nao pareca um app de treino
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
.badge-green { background: #dcfce7; color: #16a34a; }
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
.strava-box { background: #fff7ed; border: 1px solid #fed7aa; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; font-size: 13px; }
"""

def base_html(titulo: str, conteudo: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{titulo} — CorreAI</title>
    <style>{CSS}</style>
</head>
<body>
    <header>
        <span>🏃</span>
        <h1>CorreAI — Painel Admin</h1>
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
# FUNÇÕES DO STRAVA
# ============================================================

def gerar_link_strava(telefone: str) -> str:
    """Gera o link de autorização do Strava para o aluno."""
    redirect_uri = f"{BASE_URL}/strava/callback"
    return (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={STRAVA_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&approval_prompt=auto"
        f"&scope=activity:read_all"
        f"&state={telefone}"
    )

def salvar_token_strava(telefone: str, token_data: dict):
    """Salva o token do Strava do aluno no Redis."""
    r.set(f"strava:{telefone}", json.dumps(token_data))

def obter_token_strava(telefone: str) -> dict | None:
    """Busca o token do Strava do aluno."""
    dados = r.get(f"strava:{telefone}")
    return json.loads(dados) if dados else None

async def renovar_token_se_necessario(telefone: str) -> dict | None:
    """Renova o token do Strava se estiver expirado."""
    token_data = obter_token_strava(telefone)
    if not token_data:
        return None

    # Verifica se o token expirou
    if datetime.now().timestamp() >= token_data.get("expires_at", 0):
        async with httpx.AsyncClient() as http:
            response = await http.post("https://www.strava.com/oauth/token", data={
                "client_id":     STRAVA_CLIENT_ID,
                "client_secret": STRAVA_CLIENT_SECRET,
                "grant_type":    "refresh_token",
                "refresh_token": token_data["refresh_token"]
            })
            if response.status_code == 200:
                novo_token = response.json()
                salvar_token_strava(telefone, novo_token)
                return novo_token
        return None

    return token_data

async def buscar_atividades_strava(telefone: str, dias: int = 365) -> list:
    """Busca as atividades de corrida do aluno nos ultimos X dias."""
    token_data = await renovar_token_se_necessario(telefone)
    if not token_data:
        return []

    desde = int((datetime.now() - timedelta(days=dias)).timestamp())
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}

    todas_atividades = []
    pagina = 1

    async with httpx.AsyncClient() as http:
        while True:
            response = await http.get(
                "https://www.strava.com/api/v3/athlete/activities",
                headers=headers,
                params={"after": desde, "per_page": 50, "page": pagina}
            )
            if response.status_code != 200:
                break

            atividades = response.json()
            if not atividades:
                break

            corridas = [a for a in atividades if a.get("type") in ("Run", "TrailRun", "VirtualRun")]
            todas_atividades.extend(corridas)
            pagina += 1

            # Limite de seguranca para nao buscar infinitamente
            if len(atividades) < 50 or pagina > 10:
                break

    print(f"STRAVA: {len(todas_atividades)} corridas encontradas nos ultimos {dias} dias")
    return todas_atividades

def formatar_atividades_para_claude(atividades: list) -> str:
    """Formata as atividades do Strava em texto para o Claude analisar."""
    if not atividades:
        return ""

    from datetime import datetime, timedelta

    # Ordena do mais recente para o mais antigo
    atividades_ordenadas = sorted(atividades, key=lambda a: a.get("start_date_local", ""), reverse=True)

    # Resumo geral
    total_km      = round(sum(a.get("distance", 0) for a in atividades) / 1000, 1)
    total_treinos = len(atividades)
    total_horas   = round(sum(a.get("moving_time", 0) for a in atividades) / 3600, 1)

    # Pace medio geral
    dist_total_m  = sum(a.get("distance", 0) for a in atividades)
    tempo_total_s = sum(a.get("moving_time", 0) for a in atividades)
    if dist_total_m > 0:
        pace_medio_s = tempo_total_s / (dist_total_m / 1000)
        pace_min = int(pace_medio_s // 60)
        pace_sec = int(pace_medio_s % 60)
        pace_medio_str = f"{pace_min}:{pace_sec:02d}/km"
    else:
        pace_medio_str = "—"

    # Media semanal ultimas 4 semanas
    quatro_semanas = (datetime.now() - timedelta(weeks=4)).strftime("%Y-%m-%d")
    atividades_recentes = [a for a in atividades if a.get("start_date_local", "") >= quatro_semanas]
    km_4semanas   = round(sum(a.get("distance", 0) for a in atividades_recentes) / 1000, 1)
    media_semanal = round(km_4semanas / 4, 1)

    linhas = [
        "HISTORICO STRAVA — ULTIMOS 365 DIAS:",
        f"Total: {total_treinos} corridas | {total_km}km | {total_horas}h",
        f"Pace medio geral: {pace_medio_str}",
        f"Media semanal (ultimas 4 semanas): {media_semanal}km/semana",
        "",
        "ULTIMAS 20 CORRIDAS:"
    ]

    for a in atividades_ordenadas[:20]:
        data      = a.get("start_date_local", "")[:10]
        nome      = a.get("name", "Corrida")
        distancia = round(a.get("distance", 0) / 1000, 2)
        duracao   = int(a.get("moving_time", 0) / 60)
        fc_media  = a.get("average_heartrate", "—")
        elevacao  = round(a.get("total_elevation_gain", 0))

        dist_km = a.get("distance", 0) / 1000
        tempo_s = a.get("moving_time", 0)
        if dist_km > 0:
            pace_s   = tempo_s / dist_km
            pace_min = int(pace_s // 60)
            pace_sec = int(pace_s % 60)
            pace_str = f"{pace_min}:{pace_sec:02d}/km"
        else:
            pace_str = "—"

        linhas.append(
            f"• {data} — {nome}: {distancia}km em {duracao}min"
            f" | Pace: {pace_str}"
            f" | FC: {fc_media} bpm"
            f" | Elev: {elevacao}m"
        )

    return "\n".join(linhas)

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

    # Busca dados do Strava se o aluno tiver conectado
    contexto_strava = ""
    token = obter_token_strava(telefone)
    print(f"STRAVA TOKEN ENCONTRADO: {token is not None}")
    if token:
        atividades = await buscar_atividades_strava(telefone, dias=7)
        print(f"STRAVA ATIVIDADES: {len(atividades)}")
        if atividades:
            contexto_strava = "\n\n" + formatar_atividades_para_claude(atividades)
            print(f"STRAVA CONTEXTO GERADO: {len(contexto_strava)} chars")
        else:
            print("STRAVA: nenhuma atividade encontrada nos ultimos 7 dias")

    # Injeta data atual e dados do Strava no system prompt
    hoje = datetime.now().strftime("%d/%m/%Y")
    dia_semana = ["segunda-feira","terca-feira","quarta-feira","quinta-feira","sexta-feira","sabado","domingo"][datetime.now().weekday()]
    system = SYSTEM_PROMPT + f"\n\nDATA ATUAL: {dia_semana}, {hoje}"
    if contexto_strava:
        system += f"\n\nDADOS ATUAIS DO STRAVA DO ALUNO:{contexto_strava}"
        print("STRAVA: contexto injetado no system prompt")

    resposta = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=system,
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
    return {"status": "CorreAI online 🏃"}

@app.get("/strava/conectar/{telefone}")
def conectar_strava(telefone: str):
    """Redireciona o aluno para autorizar o Strava."""
    link = gerar_link_strava(telefone)
    return RedirectResponse(url=link)

@app.get("/strava/callback")
async def strava_callback(code: str, state: str):
    """
    Recebe o código do Strava após o aluno autorizar.
    Troca o código pelo token e salva no Redis.
    O 'state' contém o número de telefone do aluno.
    """
    telefone = state

    async with httpx.AsyncClient() as http:
        response = await http.post("https://www.strava.com/oauth/token", data={
            "client_id":     STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "code":          code,
            "grant_type":    "authorization_code"
        })

    if response.status_code != 200:
        return HTMLResponse("<h2>Erro ao conectar com o Strava. Tente novamente.</h2>")

    token_data = response.json()
    salvar_token_strava(telefone, token_data)

    atleta = token_data.get("athlete", {})
    nome   = atleta.get("firstname", "atleta")

    # Avisa o aluno no WhatsApp que a conexão foi feita
    await enviar_whatsapp(
        telefone,
        f"✅ Strava conectado com sucesso, {nome}! "
        f"Agora consigo analisar seus treinos automaticamente e ajustar seu plano com base no que você realmente fez. 🏃"
    )

    return HTMLResponse(f"""
    <html><body style="font-family:Arial;text-align:center;padding:60px;background:#f0f2f5;">
        <div style="background:white;border-radius:16px;padding:40px;max-width:400px;margin:0 auto;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
            <div style="font-size:48px">✅</div>
            <h2 style="margin:16px 0 8px">Strava conectado!</h2>
            <p style="color:#888">Olá, {nome}! Seu Strava foi conectado com sucesso.<br>
            Pode fechar esta página e voltar para o WhatsApp.</p>
        </div>
    </body></html>
    """)

# ============================================================
# ROTAS ADMINISTRATIVAS
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
        tem_strava = "✅ Strava" if obter_token_strava(telefone) else ""
        badge_strava = f'<span class="badge badge-green">{tem_strava}</span>' if tem_strava else ""

        rows += f"""
        <div class="aluno-row">
            <div>
                <div>
                    <a href="/admin/conversa/{telefone}">📱 {telefone}</a>
                    <span class="badge">{total} msgs</span>
                    {badge_strava}
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
    """Visualiza a conversa completa de um aluno."""
    historico = obter_historico(telefone)
    token_strava = obter_token_strava(telefone)

    strava_info = ""
    if token_strava:
        atleta = token_strava.get("athlete", {})
        nome_atleta = f"{atleta.get('firstname', '')} {atleta.get('lastname', '')}".strip()
        strava_info = f"""
        <div class="strava-box">
            🟠 <strong>Strava conectado</strong> — {nome_atleta}
        </div>"""
    else:
        link_strava = f"{BASE_URL}/strava/conectar/{telefone}"
        strava_info = f"""
        <div class="strava-box">
            ⚠️ Strava não conectado —
            <a href="{link_strava}" target="_blank">Link de conexão para enviar ao aluno</a>
        </div>"""

    if not historico:
        conteudo = f"""
        <a class="back" href="/admin">← Voltar</a>
        {strava_info}
        <div class="card"><p>Nenhuma conversa encontrada para {telefone}.</p></div>"""
        return HTMLResponse(base_html(telefone, conteudo))

    msgs = ""
    for msg in historico:
        role  = msg["role"]
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
                <div class="label">🏃 CorreAI</div>
                <div class="balao">{texto}</div>
            </div>"""

    conteudo = f"""
    <a class="back" href="/admin">← Voltar para lista de alunos</a>
    {strava_info}
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

        # Se a mensagem menciona Strava, injeta o link no contexto para o Claude decidir
        if "strava" in texto.lower():
            link = f"{BASE_URL}/strava/conectar/{telefone}"
            ja_conectado = obter_token_strava(telefone) is not None
            status_strava = "ja conectado" if ja_conectado else f"nao conectado - link de conexao: {link}"
            texto = f"{texto}\n\n[SISTEMA: Strava do aluno esta {status_strava}]"

        print(f"Mensagem de {telefone}: {texto}")
        resposta = await chamar_claude(telefone, texto)
        await enviar_whatsapp(telefone, resposta)
        print(f"Resposta enviada para {telefone}")
        return {"status": "ok"}

    except Exception as e:
        print(f"ERRO: {e}")
        return {"status": "erro", "detalhe": str(e)}
