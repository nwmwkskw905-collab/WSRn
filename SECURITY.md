# Seguranca

Este documento descreve o modelo de ameaca, os controles implementados e o que **nao** esta
resolvido. Nenhum controle aqui e decorativo: todos tem teste automatizado correspondente.

## 1. Modelo de ameaca

| Ativo | Ameaca | Controle |
|---|---|---|
| Credenciais (Cakto, LLMs, Meta) | vazamento em disco, log, Git ou resposta HTTP | cofre cifrado, redacao, nunca devolvidas pela API |
| Controle do computador | execucao de acao destrutiva ou fora de escopo | permissao por escopo, raiz autorizada, aprovacao com PIN |
| Dinheiro | gasto/reembolso nao autorizado | R$ 0,00 por padrao, aprovacao critica com PIN, uso unico |
| Runtime local | acesso por outro processo/usuario da maquina | bind em 127.0.0.1, bearer token 0600, IPC com allowlist |
| Celular pareado | token roubado ou codigo brute-forced | codigo de uso unico, 10 tentativas/min, token revogavel |
| Conteudo externo | prompt injection | conteudo marcado como dado, deteccao e neutralizacao |
| Auditoria | negacao de acao | `audit_log` append-only na pratica + eventos de tarefa |

## 2. Superficie de rede

- O runtime escuta `127.0.0.1:8765` por padrao (`JARVIS_HOST`/`JARVIS_PORT`).
- `JARVIS_REQUIRE_AUTH=1` e o padrao; `0` existe apenas para desenvolvimento/testes e aparece no
  `/health` como `warning`.
- Rotas publicas: `/health`, `/docs`, `/openapi.json`, `/api/mobile/claim`.
- `/api/mobile/claim` exige codigo valido, de uso unico, com limite de tentativas e nao revela
  detalhes (403 generico).
- CORS restrito a origens conhecidas (`CONFIG.allowed_origins`), sem credenciais.
- Headers: `X-Content-Type-Options: nosniff` e `Cache-Control: no-store` em todas as respostas.
- Expor o runtime na internet so via tunel HTTPS com autenticacao (ver `docs/MOBILE_COMPANION.md`).
  Isso e uma decisao consciente do usuario e aumenta a superficie de ataque.

## 3. Credenciais

- `security/secrets.py`: DPAPI (`CryptProtectData`, escopo do usuario) quando disponivel no Windows;
  fallback AES-GCM com chave derivada e arquivo de chave local com permissao restrita.
- Valores nunca retornam pela API: `status()` informa apenas `has_key`, `has_token`, backend e ambiente.
- `sanitize()` remove `client_secret`, `api_key`, `token`, `password`, `pin` antes de persistir
  payloads de aprovacao.
- `redact()` remove padroes de chave em logs e mensagens de erro.
- Nenhuma credencial e enviada a provedores de IA; prompts usam somente o necessario.
- `.gitignore` bloqueia `.env`, sqlite, `credentials.json` e service accounts.

## 4. Permissoes

19 escopos, cada um com risco (`low|medium|high|critical`) e categoria. Concessao:

- exige escopo conhecido (desconhecido => bloqueado por padrao);
- pode ter `roots` (caminhos) e `allow_globs`;
- pode expirar (`expires_in_hours`) e ser revogada individualmente ou em massa;
- `revoke_all` registra auditoria.

Antes de qualquer efeito, `PermissionEngine.require()` avalia: kill switch, concessao, expiracao,
caminho, comando, nivel de autonomia e necessidade de aprovacao.

Comandos de shell passam por allowlist de prefixos; metacaracteres (`;`, `&&`, `|`, backticks,
redirecionamento) sao recusados.

## 5. Aprovacao e PIN

- PIN de 6+ digitos, PBKDF2-HMAC-SHA256, 210.000 iteracoes, salt de 16 bytes.
- Comparacao em tempo constante (`hmac.compare_digest`).
- Tentativas erradas sao auditadas como `denied`.
- Aprovacao expira em 24h, e de uso unico e vinculada a acao (`consume(id, action)`).
- `critical` sempre exige PIN, inclusive nos niveis 3 e 4.
- Voz nunca aprova acao financeira: o fluxo exige digitacao na UI.

## 6. Auditoria e logs

- `audit_log`: timestamp, ator (`user|agent|system|mobile|relay`), acao, recurso, decisao, detalhes.
- `task_events`: trilha por tarefa (criacao, plano, etapa, aprovacao, falha, recuperacao).
- `logs/backend.log` no Electron recebe stdout/stderr do runtime.
- `/api/logs/audit` e `/api/logs/events` sao paginados e limitados.
- A UI expoe os dois e permite backup do banco (`/api/backup`).
- Retencao: o banco cresce; nao ha rotacao automatica (ver limitacoes).

## 7. Prompt injection e conteudo externo

`security/injection.py`:

1. Todo conteudo externo (pagina, resultado de busca, payload de webhook) e encapsulado como dado.
2. Padroes imperativos ("ignore instrucoes", "execute", "envie para", "chave de API") sao detectados
   e classificados em `low|medium|high`.
3. O plano/relatorio marca `[CONTEUDO EXTERNO NAO CONFAVEL]` e nunca converte texto em ferramenta.
4. Somente skills conhecidas e parametros validados podem ser executados — a saida de um site nao
   vira chamada de ferramenta.

## 8. Electron

- `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`, `webSecurity: true`.
- Preload expoe apenas metodos tipados; `ipcRenderer` nao vaza.
- IPC valida a origem (`dev URL` ou `file://`) antes de qualquer acao.
- `runtime:request` aceita **somente** caminhos `/api/*`.
- Janelas novas bloqueadas; `window.open` externo apenas `https://`.
- Permissao de midia: apenas microfone, apenas para origem confiavel, e nenhuma camera.
- `will-attach-webview` negado.

## 9. Dinheiro e acoes irreversiveis

- Orcamento de anuncios inicia em R$ 0,00; `set_budget_policy` exige `approval_id` valido.
- Aprovacao de orcamento e `critical` e expira junto com a politica (dias configuraveis).
- Publicacao de campanha exige aprovacao propria (`ads.publish_meta`).
- Reembolso (`cakto.refund`) e `critical`, nunca automatico.
- Nao existe compra, transferencia ou saque autonomo no codigo.
- Criacao de produto na Cakto consome a aprovacao **antes** da chamada externa.

## 10. Limitacoes conhecidas (honestas)

1. **Nao ha validacao em maquina Windows real neste ambiente** — DPAPI, UIA e pywinauto foram
   implementados por contrato e testados com dublês; a execucao real esta **VALIDACAO REAL PENDENTE**.
2. **Sem certificado de assinatura**, o SmartScreen pode alertar. O updater informa
   `signature: "not_configured"` e nao instala nada sozinho.
3. **Sem rate limiting global** nas rotas alem do pareamento; o runtime e local e de usuario unico.
4. **Sem rotacao de logs**; o SQLite pode crescer com o uso.
5. **Senha do cofre**: no fallback AES-GCM a chave fica no mesmo perfil do usuario; ela protege
   contra copia casual do banco, nao contra um atacante com o mesmo usuario logado. No Windows,
   DPAPI amarra a chave ao usuario/máquina.
6. **PWA** guarda o token em `localStorage`; XSS no dominio do tunel comprometeria o token. Use um
   tunel dedicado e mantenha o runtime atualizado.
7. **Modo demo**: quando ativo, dados ficticios sao marcados; ainda assim, nao use producao para
   demonstracoes publicas sem revisar as permissoes.
8. **Sem auditoria externa** de seguranca. Este e um projeto pessoal, nao certificado.

## 11. Como reportar

Abra uma issue privada no repositorio descrevendo o cenario, sem incluir credenciais, tokens ou
dados pessoais. Nunca anexe `runtime-token`, banco ou logs completos.
