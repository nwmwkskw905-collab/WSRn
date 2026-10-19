# Integracoes

Regra do projeto: **nenhum endpoint e inventado**. Cada chamada abaixo foi implementada a partir de
documentacao publica e tem teste de contrato. Onde a credencial/API real nao existe, o modulo
declara indisponibilidade em vez de simular sucesso.

## 1. Cakto

Base: `https://api.cakto.com.br/public_api`
Documentacao: <https://docs.cakto.com.br> (consultada em outubro/2026)

### Autenticacao

`POST /public_api/token/` com `application/x-www-form-urlencoded`:

```
client_id=<chave publica>&client_secret=<chave secreta>
```

Resposta: `access_token`, `expires_in` (~36000s), `scope`. Nao existe refresh token; o token e
renovado antes de expirar (margem de 60s) e mantido apenas em memoria. As credenciais ficam no
cofre local; a API do JARVIS devolve somente `has_key`/`has_token`.

### Endpoints usados

| Metodo | Caminho | Uso no JARVIS |
|---|---|---|
| POST | `/token/` | obter access token |
| GET | `/products/` | listar produtos (pagina/limite/busca) |
| POST | `/products/` | criar produto (gera oferta, checkout e link) |
| GET | `/products/{id}/` | detalhe do produto |
| GET | `/products/{id}/checkouts/` | listar checkouts do produto |
| GET | `/products/{id}/checkouts/{checkout_id}/` | detalhe do checkout (ofertas) |
| GET | `/offers/?product={id}` | ofertas do produto |
| GET | `/orders/` | sincronizar pedidos |
| GET | `/orders/analytics/` | analytics agregado (`group_by`, `DD-MM-YYYY`) |
| POST | `/webhooks/` | registrar endpoint de webhook |
| GET | `/webhooks/` | listar webhooks |
| POST | `/orders/{id}/refund/` | reembolso (exige aprovacao `cakto.refund`) |

### Criacao de produto

Campos obrigatorios: `name`, `description`, `price`, `type` (`unique|subscription`), `salesPage`.
Segundo a documentacao oficial, **criar o produto ja cria a oferta padrao, o checkout e o link**
(`https://pay.cakto.com.br/{offer_id}`). Nao existe endpoint separado de "criar checkout", e este
codigo nao tenta inventar um.

Fluxo de seguranca implementado:

```
UI: POST /api/approvals/request {action: "cakto.create_product"}
    -> risk=high, pin_required=true
UI: resolve com PIN -> status=approved
UI: POST /api/cakto/products {..., confirm_create: true, approval_id}
    -> consume(approval_id, "cakto.create_product")  [uso unico]
    -> chamada real a Cakto
    -> registra produto local com provider_id/offer_id/checkout_id/checkout_url
```

Sem credenciais, `GET /api/cakto/products` responde
`{"mode": "demonstracao", "warning": "Nenhuma credencial Cakto conectada...", "results": [produto com "_demo": true]}`.
Nada dessa lista e apresentado como dado real.

### Pedidos e integridade financeira

- Status considerados: `waiting_payment`, `paid`, `refused`, `refunded`, `chargedback`, `canceled`,
  `refund_requested`.
- **Somente `paid` entra como receita.** Pix/boleto gerado (`waiting_payment`) aparece em
  `pending_orders` e nunca em `gross_revenue_brl`.
- `refunded`/`chargedback` entram em `refunds_brl` e nao subtraem duas vezes.
- `net_revenue_estimate_brl` e explicitamente uma **estimativa** (taxas informadas/configuradas).
- Sem pedidos sincronizados, os relatorios retornam `is_empty: true` e a UI mostra
  "Nenhum pedido sincronizado — isso nao significa zero vendas", em vez de R$ 0,00 silencioso.

### Webhooks

Envelope: `{ "event": "...", "data": {...} }` (V2 pode enviar `data` como array — tratado).
Assinatura: `X-Cakto-Signature: v1=<hex HMAC-SHA256(secret, "{timestamp}.{raw_body}")>`,
tolerancia de 300s. Fallback por `secret` no corpo **apenas** quando o header nao existe.

Dois caminhos:

1. **Local** `POST /api/webhooks/cakto` (Bearer do runtime) — exige o PC ligado.
2. **Relay** `services/webhook-relay` — host HTTPS publico, guarda eventos com idempotencia
   (`event:id`) e encaminha ao runtime quando online. Variaveis:
   `CAKTO_WEBHOOK_SECRET`, `RELAY_TOKEN`, `JARVIS_RUNTIME_URL`, `JARVIS_RUNTIME_TOKEN`,
   `RELAY_DB`, `RELAY_FORWARD_INTERVAL`.

Ambos deduplicam e nunca tratam Pix gerado como venda paga.

### Estado atual

**AGUARDANDO CONFIGURACAO EXTERNA** para chamadas reais. Os testes usam um transporte HTTP simulado
(`httpx.MockTransport`) que valida o protocolo (URL, metodo, corpo, paginacao e erros), nao a conta
do usuario. Isso esta declarado em `tests/test_cakto.py` e no relatorio de validacao.

## 2. Meta Ads

- Graph API v21.0, `POST /{ad_account}/campaigns` e `/{ad_account}/adsets`.
- Campanhas e adsets sao criados **PAUSED**; ativacao e manual.
- Exige `ads.publish_meta` (high) + `approval_id` valido + politica de orcamento vigente.
- Bloqueio de duplicidade por nome + `external_id` existente.
- Sem token/conta: retorna erro explicito (`Meta Ads nao conectado`).
- **VALIDACAO REAL PENDENTE**: nao ha conta/app aprovado neste ambiente.

## 3. Google Ads e TikTok Ads

Nao implementados. Os adaptadores informam indisponibilidade; a UI nao mostra botao que finge
publicar. Requerem OAuth proprio, revisao de app e politicas especificas.

## 4. Pesquisa na internet

Provedores suportados em `GET|POST /api/research/config`:

| Provedor | Requer | Observacao |
|---|---|---|
| `searxng` | URL da instancia | sem chave; roda local ou self-hosted |
| `brave` | API key | plano gratuito limitado |
| `serper` | API key | busca Google via terceiro |
| `none` | — | pesquisa declara indisponibilidade |

Todo resultado externo passa por `security/injection.py` antes de entrar em um relatorio. O
relatorio lista URL, titulo, trecho e classificacao de confiabilidade — sem inventar fontes.

## 5. Provedores de IA

| Provedor | Tipo | Chave | Observacao |
|---|---|---|---|
| `ollama` | local | nao | `base_url` configuravel |
| `openai` | nuvem | sim | modelos configurados pelo usuario |
| `anthropic` | nuvem | sim | idem |
| `gemini` | nuvem | sim | idem |
| `local-rules` | interno | nao | fallback deterministico, sempre declarado |

Custos: sem tabela de precos por modelo, `cost_source` fica `unavailable` e nenhum valor e exibido
como se fosse real. Limites: `monthly_budget_usd`, `max_calls_per_day`, `allow_paid`.

## 6. Voz

- STT: Web Speech API (Chromium/Edge) em `apps/desktop/src/renderer/lib/voice.ts`, `pt-BR`,
  resultados interinos + final, indicador visivel e botao de parada.
- Wake word: modo continuo com extracao de `\bjarvis\b` antes de executar o comando.
- TTS: `speechSynthesis` com voz pt-BR selecionavel, rate/pitch/volume.
- faster-whisper/Piper: declarados como opcionais em `pyproject.toml`; **nao empacotados** nesta
  entrega. O app informa quando o reconhecimento nativo nao esta disponivel.

## 7. MCP (Model Context Protocol)

Servidor stdio em `services/agent-runtime/jarvis/mcp` (`python -m jarvis.mcp`), sem SDK externo:
JSON-RPC 2.0 com `initialize`, `tools/list`, `tools/call` e `ping` (MCP 2024-11-05).

- **Somente leitura por padrao.** Apenas ferramentas de risco `low` e sem efeito externo aparecem
  (`fs.read_text`, `fs.list`, `fs.hash`, `system.info`).
- `JARVIS_MCP_ALLOW_WRITE=1` libera ferramentas de escrita, mas cada chamada ainda passa por
  `PermissionEngine.require()` no nivel de autonomia 1 e pode ser negada.
- Ferramenta desconhecida nunca e executada; resultados passam por `sanitize()`.
- Aprovacoes com PIN nao sao resolvidas pelo MCP: se uma ferramenta exigir aprovacao, o servidor
  retorna erro e o usuario decide no desktop.
- Teste: `tests/test_mcp.py` (6 casos, incluindo tentativa de escrita sem opt-in e negacao por
  permissao).

Configuracao de exemplo (Claude Desktop ou outro cliente MCP):

```json
{
  "mcpServers": {
    "jarvis": {
      "command": "python",
      "args": ["-m", "jarvis.mcp"],
      "env": { "JARVIS_DATA_DIR": "%APPDATA%\\JARVIS AI" }
    }
  }
}
```

## 8. GitHub Releases (updates)

`apps/desktop/src/main/updater.ts` consulta `releases/latest` de `nwmwkskw905-collab/WSRn`,
compara semver, devolve `signature: "not_configured"` e apenas abre a pagina de releases. Nao ha
download/instalacao automatica.
