# JARVIS AI

Assistente autonomo para Windows 10/11 x64: aplicativo desktop (Electron + React + TypeScript),
runtime local em Python/FastAPI, motor de tarefas duravel, controle real do computador, voz em
pt-BR, pesquisa com fontes, CRM, integracao Cakto, modulos de negocios, vendas e anuncios, alem de
um companheiro movel (PWA) para iPhone.

> **Principio central:** o que nao foi executado e verificado aparece como
> **AGUARDANDO CONFIGURACAO EXTERNA** ou **VALIDACAO REAL PENDENTE**. Nenhum numero financeiro e
> inventado, nenhum endpoint foi suposto, e nenhuma acao de alto impacto roda sem aprovacao registrada.

---

## 1. O que ja funciona de fato (verificado neste repositorio)

| Area | Evidencia |
|---|---|
| Runtime FastAPI com 73 rotas `/api` | `python -m pytest tests -q` (83 testes) + smoke `app.openapi()` |
| Motor de tarefas com plano, etapas, retry, loop detection, pausa, retomada, cancelamento, kill switch | `tests/test_engine.py`, `/api/validation/run` (cenarios D, J) |
| Permissoes granulares, PIN PBKDF2, cofre AES-GCM/DPAPI, auditoria e redacao de logs | `tests/test_security.py`, `/api/diagnostics` |
| Cakto com client credentials, produtos, ofertas/checkout, pedidos, analytics, webhook idempotente | `tests/test_cakto.py` (transporte HTTP simulado no nivel de protocolo, nao API real) |
| Vendas somente com pedidos `paid`; Pix gerado nao conta como receita | `tests/test_ads_sales.py` |
| Ads com gasto padrao R$ 0,00, bloqueio de orcamento sem aprovacao com PIN | `tests/test_mobile_and_approvals.py` |
| Geracao real de projetos (web/estoque) com `pytest` executado e artefatos com SHA-256 | `tests/test_development.py` |
| Interface React com 20 secoes, typecheck e build de producao | `npm run typecheck`, `npm run build` |
| As 20 secoes renderizam sem erro (jsdom) | `npm run smoke:render` → `{navItems: 20, blank: [], errors: []}` |
| Contratos da UI x runtime (nenhum endpoint inventado) | `tests/test_ui_contract.py` |
| Pareamento de iPhone com codigo de uso unico + limite de tentativas | `tests/test_mobile_and_approvals.py` |
| Servidor MCP (stdio) somente leitura por padrao | `tests/test_mcp.py`, `python -m jarvis.mcp` |

## 2. O que depende de voce ou de uma maquina Windows

| Item | Situacao |
|---|---|
| `JARVIS-Setup.exe` / `JARVIS-Portable.exe` | O pipeline existe (`.github/workflows/jarvis-release.yml`), mas **este ambiente e Linux**: nenhum `.exe` foi gerado aqui. **AGUARDANDO EXECUCAO DO CI.** |
| Controle de janelas via pywinauto/UIA, DPAPI e captura de tela | Codigo presente e testado por contrato; **VALIDACAO REAL PENDENTE** em Windows 10/11. |
| Chamadas reais a Cakto | Precisa de `client_id`/`client_secret`. Sem isso a API responde `aguardando configuracao externa` e a listagem vem marcada `_demo`. |
| Publicacao de anuncios na Meta/Google/TikTok | **VALIDACAO REAL PENDENTE** (app aprovado, conta de anuncios e token de escrita). Gasto permanece R$ 0,00. |
| Provedores de IA (OpenAI/Anthropic/Gemini/Ollama) | Opcionais. Sem chave, o assistente responde com regras locais e declara isso. |
| Godot | Sem `godot` no `PATH`, o Game Studio entrega projeto + GDD com status `validation_pending`; nenhum executavel e gerado. |
| PWA no iPhone | Funciona, mas exige URL HTTPS publica (Tailscale Funnel/Cloudflare Tunnel) e o PC ligado. |

## 3. Estrutura do repositorio

```
apps/desktop            Electron + React + Vite (UI de 20 secoes, preload seguro, updater)
apps/mobile-companion   PWA do iPhone (pareamento por codigo, chat, tarefas, vendas, aprovacoes)
services/agent-runtime  FastAPI + motor de tarefas + ferramentas + modulos (Python 3.11+)
  jarvis/               pacote principal
  JARVIS-Agent-Runtime.spec   empacotamento PyInstaller (onedir/x64)
services/webhook-relay  receptor HTTPS de webhooks Cakto com HMAC e idempotencia
packages/shared         contratos compartilhados
modules/                manifesto executavel de cada modulo (validado por teste)
tests/                  suite obrigatoria (pytest)
docs/                   relatorio de validacao e guias operacionais
```

## 4. Requisitos

- **Windows 10/11 x64** para uso completo (automacao nativa).
- Node.js 20+ e npm 10+.
- Python 3.11+ (3.12 recomendado). O runtime tambem e distribuido congelado via PyInstaller.
- 4 GB de RAM livre; 300 MB de disco para o app + projetos gerados.

## 5. Desenvolvimento local

```bash
# 1. dependencias Python
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r services/agent-runtime/requirements.txt
pip install -r services/agent-runtime/requirements-dev.txt

# 2. testes (nao precisam de Windows nem de credenciais)
python -m pytest tests -q

# 3. runtime isolado (gera token em <data_dir>/runtime-token)
JARVIS_DATA_DIR=/tmp/jarvis-dev JARVIS_REQUIRE_AUTH=0 python -m uvicorn jarvis.main:app \
  --app-dir services/agent-runtime --host 127.0.0.1 --port 8765

# 4. interface
npm install
npm run dev            # Vite em http://localhost:5173 + Electron
```

O renderer nunca ve o token: as chamadas passam por IPC (`runtime:request`) e o processo principal
injeta `Authorization: Bearer <token>`.

## 6. Build do aplicativo Windows

```powershell
# runtime congelado (gera services/agent-runtime/dist/jarvis-agent-runtime/)
powershell -ExecutionPolicy Bypass -File services/agent-runtime/build-runtime.ps1

# instalador NSIS por usuario + portatil
npm ci
npm run dist
```

Saidas esperadas em `apps/desktop/release/`:

- `JARVIS-Setup-<versao>.exe` (NSIS, `perMachine=false`, atalhos no Menu Iniciar e Desktop)
- `JARVIS-Portable.exe`
- `SHA256SUMS.txt` e `build-info.json` (gerados pelo CI)

O CI `.github/workflows/jarvis-release.yml` executa: testes, typecheck, build, PyInstaller, checagem
de saude do executavel congelado, empacotamento, checksums e upload do artefato
**`JARVIS-Windows-Release`**. Em tags `v*`, anexa os binarios a um draft release.

## 7. Primeiro uso

1. Abra o app: o backend sobe sozinho em `127.0.0.1:8765` com token proprio.
2. **Configuracoes → PIN local**: defina um PIN de 6+ digitos (obrigatorio para acoes sensiveis).
3. **Seguranca**: conceda apenas as permissoes que pretende usar. Nada e concedido por padrao.
4. **Configuracoes → Modelos**: informe chave do provedor (opcional) e limites de custo.
5. **Cakto**: cole `client_id`/`client_secret`, teste a conexao e sincronize pedidos.
6. Fale ou digite. Para parar tudo, clique em **PARAR JARVIS** (barra inferior, bandeja ou diga
   "Jarvis, pare tudo").

## 8. Seguranca resumida

- Permissoes por escopo (`fs.read`, `automation.input`, `ads.budget`, ...), com expiracao e revogacao.
- Alto risco: aprovacao com **PIN** registrada em banco, de uso unico e vinculada a acao.
- Critico (reembolso, orcamento de anuncios, exclusao permanente): PIN em **qualquer** nivel de autonomia.
- Cofre local: DPAPI no Windows; AES-GCM com chave protegida no restante.
- Logs e auditoria passam por redacao de segredos; a API nunca devolve credenciais.
- Conteudo externo (web, webhook) e tratado como **dado**, nunca como instrucao.
- Anuncios comecam com R$ 0,00 e nao existe compra/transferencia autonoma.

Detalhes: [SECURITY.md](SECURITY.md) e [docs/AUTONOMY.md](docs/AUTONOMY.md).

## 9. Documentacao

- [ARCHITECTURE.md](ARCHITECTURE.md) — camadas, banco, state machine, IPC, fluxo de aprovacao.
- [SECURITY.md](SECURITY.md) — modelo de ameaca, cofre, PIN, redacao, limites conhecidos.
- [INTEGRATIONS.md](INTEGRATIONS.md) — Cakto (endpoints verificados), Meta, busca, LLMs, MCP, relay.
- [docs/VALIDATION_REPORT.md](docs/VALIDATION_REPORT.md) — relatorio de 23 pontos com evidencias.
- [docs/SETUP_WINDOWS.md](docs/SETUP_WINDOWS.md) — instalacao, atalhos, bandeja, desinstalacao.
- [docs/MOBILE_COMPANION.md](docs/MOBILE_COMPANION.md) — pareamento do iPhone passo a passo.
- [modules/README.md](modules/README.md) — contratos dos modulos.

## 10. Licenca e uso

Uso pessoal/proprio. Nao inclui burlar captcha, UAC, DRM, anticheat, termos de plataformas, nem
enviar mensagens em massa. Voce e responsavel pelas contas e credenciais conectadas.
