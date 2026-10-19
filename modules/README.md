# Modulos

Cada pasta contem um `module.json` que declara **o que o modulo realmente faz** e e validado por
`tests/test_module_manifests.py`: skills, tools, permissoes, rotas e caminho de implementacao
precisam existir no runtime. Um manifesto que mente quebra a suite.

| Modulo | Nome | Status |
|---|---|---|
| `business-intelligence` | JARVIS BUSINESS INTELLIGENCE | implemented |
| `sales-engine` | JARVIS SALES ENGINE | implemented |
| `ads-manager` | JARVIS ADS MANAGER | validation_pending |
| `cakto` | Integracao Cakto | requires_external_configuration |
| `development-studio` | JARVIS DEVELOPMENT STUDIO | implemented |
| `game-studio` | JARVIS GAME STUDIO | validation_pending |
| `memory` | Memoria operacional | implemented |
| `computer-control` | Controle do computador | requires_external_configuration |
| `research` | Pesquisa na internet | requires_external_configuration |
| `voice` | Voz pt-BR | implemented |
| `autonomy` | Motor de tarefas autonomo | implemented |

## Formato

```json
{
  "id": "sales-engine",
  "name": "JARVIS SALES ENGINE",
  "objective": "uma frase sobre o resultado entregue",
  "implementation": "services/agent-runtime/jarvis/modules/sales.py",
  "skills": ["sales.report"],
  "tools": [],
  "permissions": ["cakto.read"],
  "routes": ["/api/sales/report"],
  "status": "implemented",
  "limitations": ["o que NAO esta resolvido"]
}
```

- `status`: `implemented` | `requires_external_configuration` | `validation_pending`.
- `limitations` e obrigatorio e precisa ser honesto (sem "TODO resolver depois").
- O manifesto nao executa codigo; e contrato e documentacao verificavel.

## Por que nao ha plugins dinamicos

Carregar Python de terceiros dentro de um agente com acesso ao sistema operacional seria uma
superficie de ataque enorme. Novos modulos entram por codigo revisado em
`services/agent-runtime/jarvis/modules/` e passam a ser declarados aqui.
