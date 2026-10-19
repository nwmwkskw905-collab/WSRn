# packages/shared

Contratos compartilhados entre processos. A fonte de verdade atual e
`apps/desktop/src/shared/contracts.ts` (consumida pelo main, preload e renderer).

Tipos principais:

- `JarvisBridge` — superficie exposta pelo preload (IPC tipado).
- `RuntimeResponse<T>` — `{ ok, status, data, error? }`, identico ao retorno de `lib/api.ts`.
- `AppInfo` — versao, plataforma, data dir, estado do backend, flags de seguranca.
- `UpdateInfo` — resultado da checagem de releases (com `signature` explicito).

Regra: qualquer novo canal IPC deve ser adicionado aqui **e** em
`apps/desktop/src/main/index.ts`, com validacao de origem. O renderer nunca importa `electron`.
