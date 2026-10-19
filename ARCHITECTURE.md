# Arquitetura

O JARVIS e dividido em quatro processos/logicos independentes. Nenhum deles confia no anterior
apenas por proximidade: cada fronteira tem contrato, validacao e auditoria.

```
┌────────────────────────────── Electron (Windows) ──────────────────────────────┐
│ main process                                                                   │
│  ├─ BackendManager  spawna/recupera o runtime Python, le o token do disco       │
│  ├─ Tray / atalhos / autostart / janela flutuante / updater                    │
│  └─ IPC allowlist: runtime:request (somente /api/*), info, janela, updates     │
│        ▲ contextIsolation, sandbox, nodeIntegration=false                      │
│  renderer (React)                                                              │
│    ├─ 20 secoes, nenhuma chamada direta a rede em producao (usa IPC)           │
│    ├─ Voz: Web Speech API + indicador visivel + wake word opcional             │
│    └─ Aprovacao: solicita -> mostra risco -> PIN -> resolve -> executa         │
└────────────────────────────────────────────────────────────────────────────────┘
                 │ HTTP 127.0.0.1:8765 + Bearer token (arquivo 0600)
┌────────────────▼───────────────── FastAPI runtime ─────────────────────────────┐
│ middleware: bearer/mobile token, headers de seguranca, no-store                │
│ api/routes.py  73 rotas /api (openapi gerado em teste)                         │
│ engine/        planner determinista -> LLM validador (opcional)                │
│                tasks.py: state machine + checkpoints + kill switch             │
│                skills.py: contrato de skill (escopo, risco, verificacao)       │
│ tools/         registry.py: allowlist, validacao de params, risk               │
│                builtin.py: fs, shell, windows (UIA), pesquisa, testes          │
│ security/      permissions.py, approvals.py (PIN), secrets.py, injection.py    │
│ modules/       business, sales, ads, cakto, development, gamestudio, memory    │
│ llm/           router + budget + providers (openai/anthropic/gemini/ollama)    │
└────────────────────────────────────────────────────────────────────────────────┘
        │ HTTPS                                     │ HTTPS (opcional)
┌───────▼──────────┐                     ┌──────────▼─────────────────────────────┐
│ Cakto public API │                     │ services/webhook-relay (HTTPS publico) │
│ OAuth2 + orders  │                     │ HMAC v1, tolerancia 300s, idempotencia │
└──────────────────┘                     └────────────────────────────────────────┘
```

## 1. Camadas e responsabilidades

| Camada | Responsabilidade | Nunca faz |
|---|---|---|
| Renderer | apresentar estado real, coletar intencao, mostrar risco | acessar disco, guardar segredo, chamar endpoint fora da allowlist |
| Preload | expor API minima tipada via `contextBridge` | expor `ipcRenderer` cru |
| Main (Electron) | ciclo de vida do backend, tray, janela, updater | executar logica de negocio |
| Runtime (FastAPI) | planejar, autorizar, executar, verificar, persistir | contornar permissao ou PIN |
| Tools | efeito real no SO | receber caminho sem checar raiz autorizada |
| Modulos | regra de negocio por dominio | inventar dado ausente |

## 2. Persistencia (SQLite + migracoes versionadas)

`jarvis/db.py` aplica migracoes em `schema_migrations` e habilita WAL. Tabelas principais:

- `tasks`, `task_steps`, `task_events` — estado duravel, checkpoints e trilha de execucao.
- `permissions`, `approvals`, `audit_log` — autorizacao e rastreabilidade.
- `messages`, `memories` (+ FTS5) — conversa e memoria consultavel.
- `integrations`, `secrets` — credenciais cifradas e metadados de conexao.
- `businesses`, `products`, `customers`, `leads`, `orders`, `campaigns` — dominio comercial.
- `webhook_events` — deduplicacao `event:id`.
- `projects`, `artifacts` — codigo gerado e arquivos com SHA-256.
- `runtime_state` — kill switch, tokens moveis, cursos de pareamento, cache de idempotencia.
- `usage_ledger`, `model_stats` — custo e qualidade por provedor.

Backups: `GET /api/backup` usa a API de backup do SQLite (arquivo consistente com WAL).

## 3. Motor de tarefas

Estados: `queued → planning → running → completed | partially_completed | failed | cancelled`,
com `paused` e `awaiting_approval` como estados de espera.

Garantias implementadas:

1. **Plano persistido** (`plan_json` + `task_steps`) antes de qualquer efeito.
2. **Retry limitado** por etapa (`max_attempts=2`) apenas para erros nao-permissivos.
3. **Deteccao de loop**: mesma assinatura `idx:skill:params` mais de duas vezes encerra a tarefa.
4. **Teto de chamadas** por tarefa (`CONFIG.max_tool_calls_per_task`).
5. **Cancelamento/pausa** verificados entre etapas; kill switch bloqueia novas acoes na hora.
6. **Recuperacao no boot**: tarefas `running/planning/queued/awaiting_approval` viram `paused` com
   etapa em execucao resetada para `pending` — nunca se assume que o efeito ocorreu.
7. **Verificacao**: cada skill devolve `verification`; `failed/partial` rebaixa o resultado.
8. **Efeitos externos**: idempotency key por `skill+params` com cache em `runtime_state`.

## 4. Aprovacao (fluxo completo)

```
UI: POST /api/approvals/request {action, summary, data}
      -> allowlist APPROVAL_ACTIONS decide risco (high/critical) e cria registro pending
UI: usuario revisa o resumo e digita o PIN
UI: POST /api/approvals/{id}/resolve {approve, pin}
      -> PBKDF2 confere; status=approved (uso unico, expira em 24h; registro em auditoria)
UI: executa a acao real passando approval_id
      -> servico chama approvals.consume(id, action): confere acao, expiracao e marca consumed
      -> so entao a chamada externa acontece
```

Regras duras:

- Acao fora da allowlist retorna HTTP 400 — nao existe "aprovar qualquer coisa".
- `consume` so aceita a **mesma** acao e estado `approved`; replay e recusado.
- PIN e obrigatorio para `high`/`critical`; voz nunca substitui PIN.
- Tarefas aguardando aprovacao sao retomadas somente apos `resolve` aprovado.

## 5. Permissoes e autonomia

Escopos de `permissions.py` (19): arquivos, automacao, tela, microfone, internet, shell, instalacao,
Cakto (read/write/refund), anuncios (read/write/budget), publicacao, mensagens, acesso remoto,
exclusao de dados. Cada escopo tem risco e categoria; a concessao pode expirar.

Autonomia 0–4 (tabela completa em `docs/AUTONOMY.md`):

| Nivel | Efeito |
|---|---|
| 0 Observacao | apenas leituras (`fs.read`, `internet`, `cakto.read`, `ads.read`) |
| 1 Assistencia | baixo/medio risco executa; alto risco pede aprovacao |
| 2 Supervisionada | igual, com aprovacao obrigatoria por acao de alto risco |
| 3 Delimitada | alto risco sem prompt **somente** com `pre_authorize` registrado e vigente |
| 4 Delegada | idem 3; **critico continua exigindo PIN** |

## 6. Roteamento de modelos

`llm/router.py` escolhe provedor por finalidade (`chat`, `planning`), privacidade e disponibilidade:
Ollama local > provedor com chave > `local-rules`. O plano sugerido por LLM e **validado**:
skills desconhecidas sao descartadas, parametros sao checados e o numero de etapas e limitado.
Sem tabela de precos configurada, o custo aparece como `unavailable` — nunca estimado.

## 7. Comunicacao com o desktop

- Backend escuta somente `127.0.0.1` (padrao) e exige `Authorization: Bearer <token>`.
- Token: `<data_dir>/runtime-token`, criado com permissao `0600`.
- Todas as rotas (exceto `/health`, `/docs`, `/openapi.json`, `/api/mobile/claim`) exigem token.
- Tokens moveis (`mob_...`) tem escopo `read/chat/approvals` e podem ser revogados por prefixo.
- O renderer nao tem `nodeIntegration`; janelas novas sao negadas e links externos abrem no navegador
  apenas se forem `https://`.
- CSP: estrita no build (`script-src 'self' file:`, sem inline, sem ws) e flexibilizada apenas no
  servidor de desenvolvimento para o Fast Refresh. Definida em `vite.config.ts` via
  `transformIndexHtml`, com `base: "./"` para funcionar em `file://`.

## 8. Mobile companion

PWA estatica (`apps/mobile-companion`) sem build step. Fluxo: `pair-code` (6 digitos, 10 min, uso
unico, maximo 10 tentativas/minuto) → `claim` devolve token → o app guarda em `localStorage` e chama
`/api/mobile/*` com `Authorization`. Requer HTTPS publico e o PC ligado.

## 9. MCP

`jarvis/mcp` expoe o registry por stdio (JSON-RPC 2.0) para clientes MCP. E read-only por padrao,
nao resolve aprovacoes e reaplica as permissoes do desktop em cada chamada — ou seja, e uma segunda
porta de entrada, nao um atalho de privilegio.

## 10. Decisoes e limites

- Determinismo primeiro: nenhuma acao depende de modelo para ser autorizada.
- Nada de "modo demo" silencioso: dados ficticios vem marcados (`_demo`) com aviso explicito.
- Sem atualizacao silenciosa: o app verifica releases e abre a pagina; a instalacao e do usuario.
- Sem nuvem propria: o runtime e local; o relay e opcional e nao executa nada.
