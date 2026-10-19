# Documentacao

| Documento | Para que serve |
|---|---|
| [../README.md](../README.md) | visao geral, estado real, instalacao, build |
| [../ARCHITECTURE.md](../ARCHITECTURE.md) | camadas, banco, motor, aprovacao, IPC |
| [../SECURITY.md](../SECURITY.md) | modelo de ameaca, controles e limitacoes |
| [../INTEGRATIONS.md](../INTEGRATIONS.md) | Cakto, Meta, busca, LLMs, relay, voz |
| [AUTONOMY.md](AUTONOMY.md) | niveis 0–4, pre-autorizacao, kill switch |
| [SETUP_WINDOWS.md](SETUP_WINDOWS.md) | instalacao, bandeja, backup, desinstalacao |
| [MOBILE_COMPANION.md](MOBILE_COMPANION.md) | pareamento do iPhone via HTTPS |
| [VALIDATION_REPORT.md](VALIDATION_REPORT.md) | cenarios A–L e relatorio de 23 pontos |

Documentos sao verificados por teste quando possivel: `tests/test_module_manifests.py` valida os
manifestos e `tests/test_ui_contract.py` impede que a interface chame endpoints inexistentes.
