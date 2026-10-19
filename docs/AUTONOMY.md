# Niveis de autonomia

A autonomia e aplicada no **runtime**, nao na interface. Mesmo que a UI envie um nivel maior, o
motor cruza nivel + permissao concedida + risco do escopo + aprovacao registrada.

| Nivel | Nome | Leitura | Baixo/medio risco | Alto risco | Critico |
|---|---|---|---|---|---|
| 0 | Observacao | sim | bloqueado | bloqueado | bloqueado |
| 1 | Assistencia | sim | executa | aprovacao com PIN | aprovacao com PIN |
| 2 | Supervisionada | sim | executa | aprovacao com PIN | aprovacao com PIN |
| 3 | Delimitada | sim | executa | PIN **ou** `pre_authorize` vigente | aprovacao com PIN |
| 4 | Delegada | sim | executa | idem nivel 3 | aprovacao com PIN |

O que "pre_authorize" significa:

```json
POST /api/permissions
{
  "scope": "automation.input",
  "granted": true,
  "config": { "pre_authorize": true, "pre_authorize_until": "2026-11-01T00:00:00+00:00" }
}
```

- So vale para escopos de risco `high`.
- Expira na data informada; sem data, vale ate ser revogado.
- Nivel 2 ignora a pre-autorizacao (sempre pede PIN).
- Nivel 0 continua bloqueado.
- `critical` nunca e dispensado: reembolso, orcamento de anuncios e exclusao permanente sempre
  pedem PIN.

## Por que 0-4 e nao "confianca total"

O pedido original exige autorizacoes registradas e revogaveis. Um botao "autonomia total" seria
irreversivel na pratica; o modelo acima mantem cada ampliacao explicita, auditada e reversivel —
inclusive porque `revoke_all` desliga tudo de uma vez.

## Registro

Toda mudanca de permissao grava em `audit_log` (`permission.update`) com o `config` aplicado.
Aprovacoes gravaram `approval.request`, `approval.resolve` e `approval.consume`.

## Parada de emergencia

`POST /api/security/stop` (botao, bandeja, comando de voz "pare tudo"):

1. marca `kill_switch` em `runtime_state`;
2. muda tarefas ativas para `paused` e marca `cancel_requested`;
3. `require()` recusa qualquer escopo com efeito externo enquanto ativo;
4. a UI mostra **PARADO** no topo.

Retomar exige `POST /api/security/release`; nenhuma tarefa volta sozinha.
