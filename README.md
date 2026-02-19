# Coach Run — Guia de Deploy Completo

Este guia te leva do zero até o agente funcionando no WhatsApp, passo a passo.

---

## O que você vai precisar

- Conta no [Railway](https://railway.app) (gratuita para começar)
- Conta no [GitHub](https://github.com) (gratuita)
- Chave de API da Anthropic ([console.anthropic.com](https://console.anthropic.com))
- Um número de WhatsApp dedicado para o bot (pode ser chip avulso)

---

## PARTE 1 — Preparar o código no GitHub

### Passo 1 — Criar o repositório

1. Acesse [github.com](https://github.com) e faça login
2. Clique em **"New repository"** (botão verde no canto superior direito)
3. Dê o nome `coach-run`
4. Deixe como **Public** (necessário para o Railway no plano gratuito)
5. Clique em **"Create repository"**

### Passo 2 — Subir os arquivos

1. Na página do repositório criado, clique em **"uploading an existing file"**
2. Arraste os 3 arquivos para a área de upload:
   - `main.py`
   - `requirements.txt`
   - `README.md`
3. Clique em **"Commit changes"**

---

## PARTE 2 — Subir o servidor no Railway

### Passo 3 — Criar conta e novo projeto

1. Acesse [railway.app](https://railway.app) e faça login com sua conta GitHub
2. Clique em **"New Project"**
3. Escolha **"Deploy from GitHub repo"**
4. Selecione o repositório `coach-run`

### Passo 4 — Configurar as variáveis de ambiente

Ainda no Railway, dentro do seu projeto:

1. Clique no serviço criado
2. Vá na aba **"Variables"**
3. Adicione as seguintes variáveis (clique em "New Variable" para cada uma):

| Variável | Valor | Como obter |
|----------|-------|-----------|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | [console.anthropic.com](https://console.anthropic.com) → API Keys |
| `EVOLUTION_API_URL` | URL da sua Evolution API | Você vai preencher depois — deixe vazio por enquanto |
| `EVOLUTION_API_KEY` | Sua chave da Evolution | Você vai preencher depois |
| `EVOLUTION_INSTANCE` | Nome da instância | Você vai preencher depois |
| `PORT` | `8000` | Digitar manualmente |

### Passo 5 — Configurar o comando de start

1. Na aba **"Settings"** do serviço
2. Em **"Start Command"**, coloque:
   ```
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```
3. Salve

### Passo 6 — Pegar a URL do servidor

1. Na aba **"Settings"**, encontre a seção **"Domains"**
2. Clique em **"Generate Domain"**
3. Copie a URL gerada — ela vai parecer com:
   ```
   https://coach-run-production.up.railway.app
   ```
4. Teste abrindo essa URL no navegador — deve aparecer:
   ```json
   {"status": "Coach Run online 🏃"}
   ```

---

## PARTE 3 — Configurar a Evolution API

A Evolution API é o "tradutor" entre o WhatsApp e o seu servidor.

### Passo 7 — Subir a Evolution API no Railway

1. No seu projeto do Railway, clique em **"New"** → **"GitHub Repo"**
2. Cole este repositório: `https://github.com/EvolutionAPI/evolution-api`
3. Na aba **"Variables"** do novo serviço, adicione:

| Variável | Valor |
|----------|-------|
| `AUTHENTICATION_TYPE` | `apikey` |
| `AUTHENTICATION_API_KEY` | Crie uma senha forte (ex: `minha-chave-secreta-123`) |
| `PORT` | `8080` |

4. Em **"Settings"** → **"Start Command"**:
   ```
   npm start
   ```
5. Gere um domínio para este serviço também. Copie a URL.

### Passo 8 — Criar a instância do WhatsApp

Com a Evolution API no ar, você vai conectar o número do WhatsApp:

1. Abra o navegador e acesse:
   ```
   https://SUA-EVOLUTION-URL/instance/create
   ```
   Substitua `SUA-EVOLUTION-URL` pela URL gerada no passo anterior.

2. Faça a requisição POST com estas informações (use o Postman, Insomnia, ou o próprio Swagger da Evolution em `/docs`):
   ```json
   {
     "instanceName": "coach-run",
     "qrcode": true
   }
   ```
   No header, adicione: `apikey: minha-chave-secreta-123`

3. A resposta vai trazer um **QR Code**. Escaneie com o WhatsApp do número que você quer usar como bot.

4. Pronto — o número está conectado!

### Passo 9 — Configurar o Webhook

Agora você precisa dizer à Evolution API para onde enviar as mensagens recebidas (seu servidor no Railway).

Acesse:
```
https://SUA-EVOLUTION-URL/webhook/set/coach-run
```

Com o body:
```json
{
  "url": "https://SUA-URL-DO-RAILWAY/webhook",
  "webhook_by_events": false,
  "webhook_base64": false,
  "events": ["MESSAGES_UPSERT"]
}
```

---

## PARTE 4 — Conectar tudo

### Passo 10 — Preencher as variáveis que faltavam

Volte ao Railway, no serviço `coach-run`, aba **"Variables"**, e preencha:

| Variável | Valor |
|----------|-------|
| `EVOLUTION_API_URL` | URL da sua Evolution API (ex: `https://evolution-production.up.railway.app`) |
| `EVOLUTION_API_KEY` | A chave que você criou (`minha-chave-secreta-123`) |
| `EVOLUTION_INSTANCE` | `coach-run` |

### Passo 11 — Testar!

1. Mande uma mensagem para o número conectado
2. O Coach Run deve responder em alguns segundos

Se não responder, veja os logs em Railway → seu serviço → aba **"Logs"**.

---

## Solução de Problemas Comuns

**O servidor não inicia:**
- Verifique se o `Start Command` está exatamente como indicado
- Confira se todas as variáveis de ambiente foram preenchidas

**O bot não responde:**
- Verifique nos Logs do Railway se está chegando requisição no `/webhook`
- Confirme se o webhook foi configurado corretamente na Evolution API
- Teste a URL do servidor diretamente no navegador

**Erro de API Key da Anthropic:**
- Verifique se a chave começa com `sk-ant-`
- Confirme se a chave tem créditos disponíveis em console.anthropic.com

**WhatsApp desconectou:**
- A Evolution API pode desconectar ocasionalmente
- Acesse `/instance/connect/coach-run` na Evolution API para escanear o QR Code novamente

---

## Próximos Passos (quando quiser evoluir)

- **Banco de dados:** Substituir a memória em RAM por Redis ou PostgreSQL para não perder histórico se o servidor reiniciar
- **Painel de administração:** Ver todos os alunos e conversas
- **Pagamento:** Integrar com Stripe ou Hotmart para cobrar mensalmente e liberar/bloquear acesso automaticamente
- **Múltiplos números:** Escalar para vários treinadores ou nichos diferentes

---

*Coach Run — Guia de Deploy v1.0*
