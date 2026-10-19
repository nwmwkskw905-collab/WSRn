# Companheiro movel (iPhone)

A PWA em `apps/mobile-companion` permite enviar comandos, ver tarefas, consultar vendas reais e
aprovar operacoes — sem jailbreak, sem app da App Store e sem permissao de controle total do iOS
(que a Apple nao oferece a terceiros).

## O que o iPhone pode e nao pode fazer

| Pode | Nao pode |
|---|---|
| Enviar comandos de texto ao runtime | Controlar outros apps do iPhone |
| Consultar tarefas, vendas confirmadas e aprovacoes | Ler notificacoes ou tela de outros apps |
| Aprovar/negar acoes (com PIN no PC, quando exigido) | Executar acoes sem o PC ligado |
| Instalar na tela inicial como PWA | Gravar chamadas ou microphone em segundo plano |

## Pre-requisitos

1. PC ligado, com JARVIS aberto e runtime em `127.0.0.1:8765`.
2. Uma URL **HTTPS** publica apontando para a porta 8765. Duas opcoes testadas em campo:
   - **Tailscale Funnel** (recomendado, sem abrir firewall):
     ```
     tailscale funnel 8765
     # ex.: https://seu-pc.tailXXXX.ts.net
     ```
   - **Cloudflare Tunnel**:
     ```
     cloudflared tunnel --url http://127.0.0.1:8765
     ```
3. No JARVIS: **Dispositivos** → informe a URL em "URL publica do runtime" → **Salvar URL**.

> Expor o runtime na internet aumenta a superficie de ataque. O acesso continua exigindo token de
> dispositivo, e `/api/mobile/claim` aceita codigo de uso unico com limite de tentativas. Ainda
> assim: use um tunel dedicado, mantenha o app atualizado e revogue dispositivos que nao usa.

## Pareamento passo a passo

1. No PC: **Dispositivos → Gerar codigo**. Um codigo de 6 digitos aparece (validade 10 minutos).
2. No iPhone, abra a URL publica no Safari (ou a PWA ja instalada).
3. Preencha:
   - URL do runtime (a mesma que aparece no PC);
   - codigo de 6 digitos;
   - nome do dispositivo (ex.: "iPhone da Ana").
4. Toque em **Parear**. O app guarda o token em `localStorage` e passa a mostrar "pareado".
5. Instale na tela inicial: Compartilhar → **Adicionar a Tela de Inicio**.

O codigo e **de uso unico**. Se expirar, gere outro. Apos 10 tentativas por minuto, o runtime
responde `429`.

## Revogar acesso

No PC: **Dispositivos** lista os tokens por prefixo (8 caracteres) e data. **Revogar** invalida o
token imediatamente; o iPhone passa a receber `401` e precisa de novo pareamento.

## Testando a PWA localmente

```bash
cd apps/mobile-companion
python3 -m http.server 4173 --bind 0.0.0.0
```

Abra `http://localhost:4173`. Para testar o pareamento de verdade, a URL precisa ser HTTPS publica —
o iPhone nao acessa `localhost` do PC e o Safari exige HTTPS para service worker fora de localhost.

## O que a PWA chama

| Metodo | Rota | Uso |
|---|---|---|
| POST | `/api/mobile/claim` | troca codigo por token (publica, uso unico) |
| GET | `/api/status` | verificar conexao |
| POST | `/api/mobile/chat` | enviar comando |
| GET | `/api/messages` | historico da conversa |
| GET | `/api/mobile/tasks` | tarefas |
| GET | `/api/sales/dashboard` | vendas confirmadas |
| GET | `/api/mobile/approvals` | aprovacoes pendentes |
| POST | `/api/approvals/{id}/resolve` | aprovar/negar |

As aprovacoes criticas continuam exigindo PIN definido no PC; a PWA nao contorna essa regra.
