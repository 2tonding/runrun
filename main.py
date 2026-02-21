import os
import io
import json
import tempfile
import httpx
import redis
import secrets
from fastapi import FastAPI, Request, Depends, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from anthropic import Anthropic
from datetime import datetime

# ============================================================
# CONFIGURACAO
# ============================================================
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ZAPI_INSTANCE_ID  = os.environ.get("ZAPI_INSTANCE_ID")
ZAPI_TOKEN        = os.environ.get("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.environ.get("ZAPI_CLIENT_TOKEN")
REDIS_URL         = os.environ.get("REDIS_URL")
ADMIN_USER        = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS        = os.environ.get("ADMIN_PASS", "admin123")
BASE_URL          = os.environ.get("BASE_URL", "https://SEU-DOMINIO.up.railway.app")
AGENT_NAME        = os.environ.get("AGENT_NAME", "Agente")
AGENT_MODEL       = os.environ.get("AGENT_MODEL", "claude-haiku-4-5-20251001")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY")

AGENT_PROMPT_PADRAO = """Voce e um assistente prestativo e simpatico.
Responda de forma clara, direta e em portugues.
No WhatsApp, seja breve — uma ideia por mensagem, no maximo."""

client   = Anthropic(api_key=ANTHROPIC_API_KEY)
app      = FastAPI()
security = HTTPBasic()

# ============================================================
# REDIS
# ============================================================
r = redis.from_url(REDIS_URL, decode_responses=True)

# ============================================================
# AUTENTICACAO ADMIN
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
# PROMPT — salvo no Redis, editavel pelo painel
# ============================================================
PROMPT_KEY = "config:agent_prompt"

def obter_prompt() -> str:
    prompt = r.get(PROMPT_KEY)
    return prompt if prompt else AGENT_PROMPT_PADRAO

def salvar_prompt(prompt: str):
    r.set(PROMPT_KEY, prompt)

# ============================================================
# ARQUIVOS DE REFERENCIA — salvos no Redis, usados no prompt
# ============================================================
ARQUIVO_PREFIX = "config:arquivo:"

def listar_arquivos() -> list:
    chaves = r.keys(f"{ARQUIVO_PREFIX}*")
    arquivos = []
    for chave in sorted(chaves):
        nome = chave.replace(ARQUIVO_PREFIX, "")
        tamanho = len(r.get(chave) or "")
        arquivos.append({"nome": nome, "tamanho": tamanho})
    return arquivos

def obter_arquivo(nome: str) -> str | None:
    return r.get(f"{ARQUIVO_PREFIX}{nome}")

def salvar_arquivo(nome: str, conteudo: str):
    r.set(f"{ARQUIVO_PREFIX}{nome}", conteudo[:20000])  # limite 20k chars

def apagar_arquivo(nome: str):
    r.delete(f"{ARQUIVO_PREFIX}{nome}")

def injetar_arquivos_no_prompt(prompt: str) -> str:
    """Substitui [nome_arquivo] pelo conteudo real salvo no Redis."""
    import re
    referencias = re.findall(r'\[([a-zA-Z0-9_\-]+)\]', prompt)
    for nome in referencias:
        conteudo = obter_arquivo(nome)
        if conteudo:
            prompt = prompt.replace(f"[{nome}]", f"\n\n=== CONTEUDO DE '{nome}' ===\n{conteudo}\n=== FIM DE '{nome}' ===\n")
    return prompt

# ============================================================
# HISTORICO COM REDIS
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
# PROCESSAMENTO DE ARQUIVOS E AUDIO
# ============================================================

async def transcrever_audio(url_audio: str) -> str:
    """Baixa o audio e transcreve usando Groq Whisper."""
    if not GROQ_API_KEY:
        return "[Audio recebido, mas GROQ_API_KEY nao configurada]"

    try:
        async with httpx.AsyncClient(timeout=60) as http:
            # Baixa o audio
            r_audio = await http.get(url_audio)
            conteudo = r_audio.content

            # Envia para o Groq Whisper
            response = await http.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": ("audio.ogg", conteudo, "audio/ogg")},
                data={"model": "whisper-large-v3", "language": "pt"}
            )

            if response.status_code == 200:
                texto = response.json().get("text", "")
                print(f"AUDIO TRANSCRITO: {texto[:100]}")
                return f"[Audio transcrito]: {texto}"
            else:
                print(f"GROQ ERRO: {response.status_code} | {response.text}")
                return "[Nao foi possivel transcrever o audio]"

    except Exception as e:
        print(f"ERRO ao transcrever audio: {e}")
        return "[Erro ao processar audio]"


async def extrair_texto_pdf(url_arquivo: str) -> str:
    """Baixa e extrai texto de um PDF."""
    try:
        import pdfplumber

        async with httpx.AsyncClient(timeout=60) as http:
            r_arquivo = await http.get(url_arquivo)
            conteudo = r_arquivo.content

        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            paginas = []
            for i, pagina in enumerate(pdf.pages[:20]):  # limite de 20 paginas
                texto = pagina.extract_text()
                if texto:
                    paginas.append(f"[Pagina {i+1}]\n{texto}")

        texto_completo = "\n\n".join(paginas)
        print(f"PDF EXTRAIDO: {len(texto_completo)} caracteres")
        return f"[Conteudo do PDF enviado pelo usuario]:\n{texto_completo[:8000]}"

    except Exception as e:
        print(f"ERRO ao ler PDF: {e}")
        return "[Nao foi possivel ler o PDF]"


async def extrair_texto_excel(url_arquivo: str) -> str:
    """Baixa e extrai dados de um arquivo XLS/XLSX."""
    try:
        import openpyxl

        async with httpx.AsyncClient(timeout=60) as http:
            r_arquivo = await http.get(url_arquivo)
            conteudo = r_arquivo.content

        wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
        linhas_total = []

        for nome_aba in wb.sheetnames[:3]:  # limite de 3 abas
            ws = wb[nome_aba]
            linhas_total.append(f"[Aba: {nome_aba}]")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= 100:  # limite de 100 linhas por aba
                    linhas_total.append("... (mais linhas omitidas)")
                    break
                linha = " | ".join(str(c) if c is not None else "" for c in row)
                if linha.strip():
                    linhas_total.append(linha)

        texto_completo = "\n".join(linhas_total)
        print(f"EXCEL EXTRAIDO: {len(texto_completo)} caracteres")
        return f"[Conteudo da planilha enviada pelo usuario]:\n{texto_completo[:8000]}"

    except Exception as e:
        print(f"ERRO ao ler Excel: {e}")
        return "[Nao foi possivel ler a planilha]"


async def processar_midia(dados: dict) -> str | None:
    """
    Detecta o tipo de midia recebida e retorna o texto extraido.
    Retorna None se nao for midia suportada.
    """
    # Audio
    audio = dados.get("audio", {})
    if audio and audio.get("audioUrl"):
        print("AUDIO recebido — transcrevendo...")
        return await transcrever_audio(audio["audioUrl"])

    # Documento (PDF ou Excel)
    documento = dados.get("document", {})
    if documento:
        url      = documento.get("documentUrl", "")
        filename = documento.get("fileName", "").lower()
        mime     = documento.get("mimeType", "").lower()

        if not url:
            return None

        if "pdf" in mime or filename.endswith(".pdf"):
            print("PDF recebido — extraindo texto...")
            return await extrair_texto_pdf(url)

        if any(x in mime for x in ["excel", "spreadsheet", "xlsx", "xls"]) or \
           filename.endswith((".xlsx", ".xls")):
            print("EXCEL recebido — extraindo dados...")
            return await extrair_texto_excel(url)

        return f"[Arquivo recebido: {filename} — tipo nao suportado para leitura automatica]"

    return None

# ============================================================
# LAYOUT BASE DO PAINEL
# ============================================================
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Arial, sans-serif; background: #f0f2f5; color: #333; }
header { background: #1a1a2e; color: white; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
header h1 { font-size: 18px; }
header a { color: #aab4ff; text-decoration: none; font-size: 14px; margin-left: auto; }
header a:hover { text-decoration: underline; }
.container { max-width: 860px; margin: 30px auto; padding: 0 20px; }
.card { background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
.card h2 { font-size: 16px; margin-bottom: 16px; color: #555; }
a { color: #4f46e5; text-decoration: none; }
a:hover { text-decoration: underline; }
.badge { display: inline-block; background: #e0e7ff; color: #4f46e5; border-radius: 20px; padding: 2px 10px; font-size: 12px; margin-left: 8px; }
.aluno-row { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid #f0f0f0; }
.aluno-row:last-child { border-bottom: none; }
.aluno-info { font-size: 12px; color: #999; margin-top: 4px; max-width: 540px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.btn { display: inline-block; padding: 6px 14px; border-radius: 8px; font-size: 13px; cursor: pointer; border: none; text-decoration: none; }
.btn-primary { background: #4f46e5; color: white; }
.btn-primary:hover { background: #4338ca; text-decoration: none; color: white; }
.btn-danger { background: #fee2e2; color: #dc2626; }
.btn-danger:hover { background: #fecaca; text-decoration: none; }
.back { display: inline-block; margin-bottom: 16px; font-size: 14px; }
.total { font-size: 13px; color: #888; margin-bottom: 16px; }
.chat { display: flex; flex-direction: column; gap: 10px; }
.msg { display: flex; flex-direction: column; max-width: 80%; }
.msg.usuario { align-self: flex-end; align-items: flex-end; }
.msg.agente { align-self: flex-start; align-items: flex-start; }
.label { font-size: 11px; color: #aaa; margin-bottom: 3px; padding: 0 6px; }
.balao { padding: 10px 14px; border-radius: 16px; font-size: 14px; line-height: 1.6; }
.usuario .balao { background: #dcf8c6; border-bottom-right-radius: 4px; }
.agente .balao { background: #f8f8f8; border-bottom-left-radius: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.08); }
textarea { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; font-family: monospace; line-height: 1.6; resize: vertical; min-height: 300px; }
textarea:focus { outline: none; border-color: #4f46e5; box-shadow: 0 0 0 2px rgba(79,70,229,0.1); }
.success { background: #dcfce7; color: #16a34a; padding: 10px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }
.nav { display: flex; gap: 12px; margin-bottom: 20px; }
.nav a { padding: 8px 16px; border-radius: 8px; background: white; font-size: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.nav a.ativo { background: #4f46e5; color: white; }
.nav a:hover { text-decoration: none; background: #e0e7ff; }
.nav a.ativo:hover { background: #4338ca; }
"""

def base_html(titulo: str, conteudo: str, pagina_ativa: str = "") -> str:
    nav_usuarios = 'class="ativo"' if pagina_ativa == "usuarios" else ""
    nav_prompt   = 'class="ativo"' if pagina_ativa == "prompt" else ""
    nav_arquivos = 'class="ativo"' if pagina_ativa == "arquivos" else ""
    return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{titulo} — {AGENT_NAME}</title>
    <style>{CSS}</style>
</head>
<body>
    <header>
        <span>🤖</span>
        <h1>{AGENT_NAME} — Painel Admin</h1>
        <a href="/admin">Inicio</a>
    </header>
    <div class="container">
        <div class="nav">
            <a href="/admin" {nav_usuarios}>Usuarios</a>
            <a href="/admin/prompt" {nav_prompt}>Editar Prompt</a>
            <a href="/admin/arquivos" {nav_arquivos}>Arquivos</a>
        </div>
        {conteudo}
    </div>
</body>
</html>"""

# ============================================================
# FUNCOES AUXILIARES
# ============================================================

async def enviar_whatsapp(telefone: str, mensagem: str):
    numero_limpo = telefone.replace("+", "").replace("-", "").replace(" ", "")
    if numero_limpo.startswith("55") and len(numero_limpo) == 12:
        numero_limpo = numero_limpo[:4] + "9" + numero_limpo[4:]

    url     = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
    headers = {"Content-Type": "application/json", "Client-Token": ZAPI_CLIENT_TOKEN}
    payload = {"phone": numero_limpo, "message": mensagem}

    print(f"ENVIANDO para {numero_limpo}")
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(url, headers=headers, json=payload)
        print(f"Z-API STATUS: {response.status_code} | {response.text}")


async def chamar_claude(telefone: str, mensagem_usuario: str) -> str:
    salvar_mensagem(telefone, "user", mensagem_usuario)
    historico = obter_historico(telefone)

    hoje       = datetime.now().strftime("%d/%m/%Y")
    dia_semana = ["segunda-feira","terca-feira","quarta-feira","quinta-feira",
                  "sexta-feira","sabado","domingo"][datetime.now().weekday()]

    prompt_base = injetar_arquivos_no_prompt(obter_prompt())
    system = prompt_base + f"\n\nDATA ATUAL: {dia_semana}, {hoje}"

    resposta = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=1024,
        system=system,
        messages=historico
    )

    texto_resposta = resposta.content[0].text
    salvar_mensagem(telefone, "assistant", texto_resposta)
    return texto_resposta

# ============================================================
# ROTAS PUBLICAS
# ============================================================

@app.get("/")
def status():
    return {"status": f"{AGENT_NAME} online"}

# ============================================================
# PAINEL ADMIN — USUARIOS
# ============================================================

@app.get("/admin", response_class=HTMLResponse)
def painel_admin(admin: str = Depends(verificar_admin)):
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
                    <a href="/admin/conversa/{telefone}">{telefone}</a>
                    <span class="badge">{total} msgs</span>
                </div>
                <div class="aluno-info">{ultima}</div>
            </div>
            <a href="/admin/apagar/{telefone}" onclick="return confirm('Apagar historico de {telefone}?')">
                <span class="btn btn-danger">Apagar</span>
            </a>
        </div>"""

    if not rows:
        rows = "<p style='color:#888;padding:20px 0'>Nenhum usuario ainda.</p>"

    conteudo = f"""
    <div class="card">
        <h2>Usuarios ({len(chaves)} total)</h2>
        {rows}
    </div>"""

    return HTMLResponse(base_html("Usuarios", conteudo, "usuarios"))


@app.get("/admin/conversa/{telefone}", response_class=HTMLResponse)
def ver_conversa(telefone: str, admin: str = Depends(verificar_admin)):
    historico = obter_historico(telefone)

    if not historico:
        conteudo = f"""
        <a class="back" href="/admin">← Voltar</a>
        <div class="card"><p>Nenhuma conversa para {telefone}.</p></div>"""
        return HTMLResponse(base_html(telefone, conteudo))

    msgs = ""
    for msg in historico:
        role  = msg["role"]
        texto = msg["content"].replace("\n", "<br>")
        if role == "user":
            msgs += f"""
            <div class="msg usuario">
                <div class="label">Usuario</div>
                <div class="balao">{texto}</div>
            </div>"""
        else:
            msgs += f"""
            <div class="msg agente">
                <div class="label">{AGENT_NAME}</div>
                <div class="balao">{texto}</div>
            </div>"""

    conteudo = f"""
    <a class="back" href="/admin">← Voltar</a>
    <div class="card">
        <h2>Conversa com {telefone}</h2>
        <div class="total">{len(historico)} mensagens</div>
        <div class="chat">{msgs}</div>
    </div>"""

    return HTMLResponse(base_html(telefone, conteudo))


@app.get("/admin/apagar/{telefone}")
def apagar_historico(telefone: str, admin: str = Depends(verificar_admin)):
    r.delete(f"historico:{telefone}")
    return RedirectResponse(url="/admin")

# ============================================================
# PAINEL ADMIN — EDITAR PROMPT
# ============================================================

@app.get("/admin/prompt", response_class=HTMLResponse)
def editar_prompt_get(admin: str = Depends(verificar_admin), salvo: str = ""):
    prompt_atual = obter_prompt()
    aviso = '<div class="success">Prompt salvo com sucesso!</div>' if salvo == "1" else ""

    conteudo = f"""
    {aviso}
    <div class="card">
        <h2>Editar Prompt do Agente</h2>
        <p style="font-size:13px;color:#888;margin-bottom:16px;">
            Define o comportamento do agente. Salve e ja entra em vigor — sem redeploy.
        </p>
        <form method="post" action="/admin/prompt">
            <textarea name="prompt">{prompt_atual}</textarea>
            <br><br>
            <button type="submit" class="btn btn-primary">Salvar Prompt</button>
        </form>
    </div>"""

    return HTMLResponse(base_html("Editar Prompt", conteudo, "prompt"))


@app.post("/admin/prompt")
async def editar_prompt_post(
    prompt: str = Form(...),
    admin: str = Depends(verificar_admin)
):
    salvar_prompt(prompt.strip())
    return RedirectResponse(url="/admin/prompt?salvo=1", status_code=303)

# ============================================================
# PAINEL ADMIN — ARQUIVOS DE REFERENCIA
# ============================================================

@app.get("/admin/arquivos", response_class=HTMLResponse)
async def painel_arquivos(admin: str = Depends(verificar_admin), salvo: str = ""):
    arquivos = listar_arquivos()
    aviso = '<div class="success">Arquivo salvo com sucesso!</div>' if salvo == "1" else ""

    rows = ""
    for arq in arquivos:
        kb = round(arq["tamanho"] / 1024, 1)
        nome_arq = arq["nome"]
        rows += f"""
        <div class="aluno-row">
            <div>
                <div><strong>[{nome_arq}]</strong> &nbsp;
                    <span style="font-size:12px;color:#888;">{kb} KB</span>
                </div>
                <div class="aluno-info">Use [{nome_arq}] no prompt para referenciar este arquivo</div>
            </div>
            <a href="/admin/arquivos/apagar/{nome_arq}" onclick="return confirm('Apagar {nome_arq}?')">
                <span class="btn btn-danger">Apagar</span>
            </a>
        </div>"""

    if not rows:
        rows = "<p style='color:#888;padding:12px 0'>Nenhum arquivo ainda.</p>"

    conteudo = f"""
    {aviso}
    <div class="card">
        <h2>Arquivos de Referencia</h2>
        <p style="font-size:13px;color:#888;margin-bottom:16px;">
            Faca upload de PDFs ou arquivos de texto. Depois use <code>[nome]</code> no prompt
            para injetar o conteudo automaticamente. Ex: <em>"Siga a metodologia em [metodologia]"</em>
        </p>
        {rows}
    </div>
    <div class="card">
        <h2>Novo Arquivo</h2>
        <form method="post" action="/admin/arquivos" enctype="multipart/form-data">
            <div style="margin-bottom:12px;">
                <label style="font-size:13px;color:#555;display:block;margin-bottom:6px;">
                    Nome de referencia (sem espacos, ex: metodologia, cardapio, manual)
                </label>
                <input type="text" name="nome" required placeholder="metodologia"
                    style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:14px;">
            </div>
            <div style="margin-bottom:16px;">
                <label style="font-size:13px;color:#555;display:block;margin-bottom:6px;">
                    Arquivo (PDF ou TXT — max 500KB)
                </label>
                <input type="file" name="arquivo" accept=".pdf,.txt,.md" required
                    style="font-size:14px;">
            </div>
            <button type="submit" class="btn btn-primary">Salvar Arquivo</button>
        </form>
    </div>"""

    return HTMLResponse(base_html("Arquivos", conteudo, "arquivos"))


@app.post("/admin/arquivos")
async def upload_arquivo(
    nome: str = Form(...),
    arquivo: UploadFile = File(...),
    admin: str = Depends(verificar_admin)
):
    conteudo_bytes = await arquivo.read()
    filename = arquivo.filename.lower()

    # Extrai texto conforme o tipo
    if filename.endswith(".pdf"):
        try:
            import pdfplumber, io
            with pdfplumber.open(io.BytesIO(conteudo_bytes)) as pdf:
                paginas = []
                for i, pagina in enumerate(pdf.pages[:30]):
                    texto = pagina.extract_text()
                    if texto:
                        paginas.append(texto)
            texto_final = "\n\n".join(paginas)
        except Exception as e:
            texto_final = f"[Erro ao ler PDF: {e}]"
    else:
        # TXT, MD e outros textos
        try:
            texto_final = conteudo_bytes.decode("utf-8")
        except Exception:
            texto_final = conteudo_bytes.decode("latin-1", errors="ignore")

    # Nome seguro — apenas letras, numeros e hifen
    import re
    nome_seguro = re.sub(r"[^a-zA-Z0-9_\-]", "", nome).lower()
    if not nome_seguro:
        nome_seguro = "arquivo"

    salvar_arquivo(nome_seguro, texto_final)
    print(f"ARQUIVO SALVO: [{nome_seguro}] — {len(texto_final)} chars")
    return RedirectResponse(url="/admin/arquivos?salvo=1", status_code=303)


@app.get("/admin/arquivos/apagar/{nome}")
def apagar_arquivo_rota(nome: str, admin: str = Depends(verificar_admin)):
    apagar_arquivo(nome)
    return RedirectResponse(url="/admin/arquivos")


# ============================================================
# WEBHOOK
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
        if not telefone:
            return {"status": "ignorado"}

        # Tenta processar midia (audio, PDF, Excel)
        texto_midia = await processar_midia(dados)
        if texto_midia:
            print(f"MIDIA processada de {telefone}")
            resposta = await chamar_claude(telefone, texto_midia)
            await enviar_whatsapp(telefone, resposta)
            return {"status": "ok"}

        # Mensagem de texto normal
        texto = dados.get("text", {}).get("message", "")
        if not texto:
            return {"status": "ignorado"}

        print(f"Mensagem de {telefone}: {texto}")
        resposta = await chamar_claude(telefone, texto)
        await enviar_whatsapp(telefone, resposta)
        print(f"Resposta enviada para {telefone}")
        return {"status": "ok"}

    except Exception as e:
        print(f"ERRO: {e}")
        return {"status": "erro", "detalhe": str(e)}
