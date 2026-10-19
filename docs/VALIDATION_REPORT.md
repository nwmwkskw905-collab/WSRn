# Relatorio de validacao

Data das execucoes: **2026-10-19** (UTC).
Ambiente de verificacao: Linux x86_64, Python 3.11.2, Node 22.22.3, npm 10.9.8.
**Nao havia maquina Windows disponivel.** Tudo que depende de Windows esta marcado como
`VALIDACAO REAL PENDENTE`. Nada foi simulado como se fosse execucao real.

## Comandos e resultados brutos

```text
$ python -m pytest tests -q
83 passed, 1 warning in 5.26s

$ npx tsc -p apps/desktop/tsconfig.main.json --noEmit
(0 erros)

$ npx tsc -p apps/desktop/tsconfig.renderer.json --noEmit
(0 erros)

$ npm run smoke:render      # bundle de producao em jsdom, clicando nas 20 secoes
{"navItems": 20, "blank": [], "errors": []}

$ npx vite build           # apps/desktop
dist/renderer/index.html                      0.80 kB
dist/renderer/assets/index-*.css             25.12 kB
dist/renderer/assets/index-*.js             252.17 kB
built in ~1.0s

$ POST /api/validation/run   # dados limpos + fs.write + shell.execute
{"passed": 6, "failed": 0, "blocked": 0, "pending": 7, "total": 13}
```

Cobertura por arquivo: `test_core`, `test_security`, `test_tools`, `test_engine`, `test_cakto`,
`test_ads_sales`, `test_development`, `test_api`, `test_webhook_relay`, `test_ui_contract`,
`test_mobile_and_approvals`, `test_module_manifests`, `test_mcp`.

## Cenarios obrigatorios A–L

| Cenario | Descricao | Status | Evidencia |
|---|---|---|---|
| A | Abrir Bloco de Notas e digitar um texto | `platform_unsupported` local / **VALIDACAO REAL PENDENTE** | skill `windows.notepad` + `tests/test_engine.py`; exige Windows + `automation.input` + aprovacao |
| B | Organizar Downloads sem apagar | **PASSED** | `/api/validation/run` → 4 arquivos movidos, `deleted_anything=false`; `tests/test_engine.py` |
| C | Pesquisa com fontes e analise | `requires_configuration` **AGUARDANDO CONFIGURACAO EXTERNA** | `research.report` + `security/injection.py`; sem provedor de busca configurado declara indisponibilidade |
| D | Gerar software e executar testes | **PASSED** | projeto `validacao-cadastro-de-produtos`, `pytest exit=0`; `tests/test_development.py` |
| E | Projeto Godot | `requires_configuration` **VALIDACAO REAL PENDENTE** | projeto + cena + script + GDD gerados; `godot_installed=false` → `validation_pending`, sem executavel |
| F | Listar produtos Cakto | `requires_configuration` **AGUARDANDO CONFIGURACAO EXTERNA** | `tests/test_cakto.py` com transporte simulado; sem credencial retorna `_demo` + aviso |
| G | Criar produto Cakto + checkout | `requires_configuration` **AGUARDANDO CONFIGURACAO EXTERNA** | aprovar (PIN) → `consume` → POST; teste garante bloqueio sem `approval_id` |
| H | Preparar/publicar campanha Meta | `requires_configuration` **VALIDACAO REAL PENDENTE** | preparo com R$ 0,00 + `tests/test_ads_sales.py`; publicacao exige conta/token reais |
| I | Vendas e faturamento | `requires_configuration` **AGUARDANDO CONFIGURACAO EXTERNA** | sem pedidos: `is_empty=true` e mensagem explicita; teste garante que so `paid` conta |
| J | Recuperacao apos reinicio | **PASSED** | `running → paused`, etapa reexecutavel, evento `task.recovered` |
| K | Prompt injection | **PASSED** | 5 padroes detectados, conteudo encapsulado como `UNTRUSTED` |
| L | Cancelamento de tarefa | **PASSED** | status `cancelled`, `cancel_requested=1`, auditoria registrada |

## Relatorio de 23 pontos

Legenda de status:
- **VERIFICADO** — executado neste ambiente com evidencia reproduzivel.
- **PENDENTE EXTERNO** — depende de credencial/conta; o codigo recusa em vez de simular.
- **PENDENTE REAL** — depende de Windows ou de API real; existe apenas validacao por contrato.

### 1. Instalador Windows por usuario (NSIS)
**PENDENTE REAL.** `apps/desktop/package.json` define `nsis.oneClick=false`, `perMachine=false`,
`allowToChangeInstallationDirectory=true`, atalhos de Desktop e Menu Iniciar. O workflow
`jarvis-release.yml` empacota em `windows-latest`. Nenhum `.exe` foi gerado neste ambiente Linux.

### 2. Executavel portatil
**PENDENTE REAL.** Alvo `portable` configurado com `JARVIS-Portable.exe`; mesma dependencia de CI.

### 3. Icone original, atalhos, autostart e bandeja
**VERIFICADO (codigo) + PENDENTE REAL (visual).** `resources/icon.png|ico|tray.png` gerados e
inspecionados; `createTray`, `app.setLoginItemSettings`, atalhos via electron-builder.
Startup/atalhos so podem ser confirmados apos instalar no Windows.

### 4. Janela flutuante e atalho global
**VERIFICADO (codigo).** `toggleFloating`, `alwaysOnTop`, `Ctrl+Shift+J` em `src/main/index.ts`;
renderer detecta modo flutuante e renderiza `FloatingShell` com microfone e botao de parada.

### 5. Servico local com token
**VERIFICADO.** Runtime em `127.0.0.1:8765`; `runtime-token` com `0600`; middleware aceita apenas
Bearer valido ou token movel registrado. `tests/test_api.py`, `tests/test_mobile_and_approvals.py`.

### 6. Persistencia e migracoes
**VERIFICADO.** SQLite com `schema_migrations`, WAL e 20+ tabelas; `GET /api/backup` gera copia
consistente. Testes usam diretorio limpo a cada execucao.

### 7. Atualizacoes verificadas (sem instalacao silenciosa)
**VERIFICADO (logica).** `updater.ts` consulta `releases/latest`, compara semver, devolve
`signature: "not_configured"` e apenas abre a pagina. Nao baixa nem executa binario.

### 8. Desinstalador e retencao de dados
**PENDENTE REAL.** Configurado `deleteAppDataOnUninstall=false`; remocao de dados e manual e
documentada. Validacao do fluxo NSIS depende de Windows.

### 9. Logs, diagnostico e auditoria
**VERIFICADO.** `/api/logs/audit`, `/api/logs/events`, `/api/diagnostics` (banco, token 0600, cofre,
PIN, Cakto, workflow, Godot), `backend.log`, tela Logs com backup e execucao de cenarios.

### 10. Recuperacao de falhas do motor
**VERIFICADO.** Cenario J; tarefas interrompidas viram `paused`, etapas `running` voltam a `pending`,
evento `task.recovered`; retomada e manual.

### 11. Voz pt-BR com indicador visivel
**VERIFICADO (codigo) + PENDENTE REAL (microfone).** Web Speech API em pt-BR com resultados
interinos, wake word `jarvis`, botoes de iniciar/parar e indicador animado. Reconhecimento nativo do
Electron pode exigir chave Google; a UI informa e sugere texto/STT local.

### 12. Controle real do Windows (UIA)
**PENDENTE REAL.** `windows.open_app`, `windows.type_text`, `windows.capture` exigem pywinauto/UIA;
fora do Windows retornam erro explicito de plataforma. Ordem de escalonamento documentada.

### 13. Motor autonomo 0–4 com autorizacoes revogaveis
**VERIFICADO.** Matriz em `docs/AUTONOMY.md` e `tests/test_security.py`
(`test_autonomy_levels_have_distinct_policy`): nivel 0 bloqueia efeitos, 3/4 so dispensam PIN com
`pre_authorize` vigente e escopo `high`; `critical` sempre exige PIN.

### 14. Pesquisa com fontes e defesa contra injection
**VERIFICADO (defesa) / PENDENTE EXTERNO (busca).** Cenario K passa com 5 achados; sem provedor, a
pesquisa falha de forma declarada.

### 15. JARVIS BUSINESS INTELLIGENCE
**VERIFICADO.** `/api/businesses/plan` retorna cenarios pessimista/base/otimista com premissas
explicitas e disclaimer; teste garante que nao ha promessa de receita.

### 16. JARVIS SALES ENGINE
**VERIFICADO (logica) / PENDENTE EXTERNO (dados).** Invariante: `paid_orders=1` gera
`gross_revenue_brl=97.0`, taxas 6.0; Pix pendente nao soma receita; `is_empty` explica ausencia.

### 17. JARVIS ADS MANAGER
**VERIFICADO (guardrails).** Orcamento padrao R$ 0,00; `POST /api/ads/budget` sem `approval_id` →
403; aprovacao consumida nao pode ser reutilizada; publicacao cria campanha **PAUSED**.
**PENDENTE REAL** contra a Graph API.

### 18. Integracao Cakto
**VERIFICADO (contrato) / PENDENTE EXTERNO (conta).** Token client-credentials, produtos, ofertas,
checkouts, pedidos, analytics e webhooks implementados conforme docs oficiais; nenhum endpoint
inventado. Criacao exige aprovacao com PIN consumida antes da chamada.

### 19. Development Studio
**VERIFICADO.** Dois tipos reais (`web-app`, `inventory-system`); arquivos escritos, sintaxe
verificada, `pytest` executado com `exit_code=0`, limitacoes declaradas (sem instalador).

### 20. Game Studio (Godot)
**PENDENTE REAL.** Gera `project.godot`, cena, script e GDD; sem Godot no PATH, status
`validation_pending` e `build=not_generated`. Nenhum executavel e alegado.

### 21. Memoria e CRM
**VERIFICADO.** Memoria com 6 tipos, FTS5, busca, edicao/remocao; CRM com estagios, consentimento e
`eligible_for_contact`; nenhum disparo automatico de mensagens.

### 22. Seguranca aplicada
**VERIFICADO.** 19 escopos, PIN PBKDF2 (210k), cofre AES-GCM/DPAPI, `consume` de uso unico,
kill switch, redacao de segredos, allowlist de comandos, CORS restrito, headers `no-store`,
IPC com origem validada e apenas `/api/*`.

### 23. Suite de testes, CI e reprodutibilidade
**VERIFICADO.** 83 testes em 13 arquivos + smoke de renderizacao das 20 secoes; typecheck e build do renderer; workflow com 3 jobs
(testes Linux, typecheck/build, Windows x64 com PyInstaller + health check do executavel congelado +
checksums + artefato `JARVIS-Windows-Release`). O workflow ainda **nao foi executado** neste
repositorio remoto.

## O que falta para considerar "pronto para producao"

1. Rodar o workflow em `windows-latest` e validar instalacao, atalhos, bandeja, autostart,
   desinstalacao e assinatura digital.
2. Executar em Windows real os cenarios A (Notepad), B (Downloads), E (Godot) e a captura de tela.
3. Conectar uma conta Cakto de teste e executar F/G/I com pedidos reais, conferindo totais.
4. Configurar Meta Ads (app aprovado) e validar publicacao pausada + limites.
5. Configurar provedor de busca e LLM; medir custo real com tabela de precos.
6. Revisar o pareamento movel com tunel HTTPS e testar revogacao em dispositivo fisico.

## Declaracao de honestidade

- Nenhum dado financeiro deste repositorio e inventado; valores ausentes aparecem como "sem dado".
- Testes com transporte HTTP simulado estao marcados como tal e **nao** contam como passes de API real.
- Nenhum binario Windows e declarado existente sem execucao do CI.
- Nenhum segredo aparece neste relatorio, nos logs ou no Git.
