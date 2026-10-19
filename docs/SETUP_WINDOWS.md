# Instalacao e operacao no Windows

## Requisitos

- Windows 10 (22H2+) ou Windows 11, x64.
- Conta de usuario comum. O instalador e **por usuario** (nao exige administrador).
- 4 GB de RAM livre, 300 MB de disco para o app.
- Microfone apenas se voce quiser usar voz.
- Python so e necessario na **compilacao**; o usuario final recebe o runtime congelado.

## Instalacao (usuario final)

1. Baixe `JARVIS-Setup-<versao>.exe` do artefato `JARVIS-Windows-Release` ou das releases.
2. Confira o SHA-256 contra `SHA256SUMS.txt`:
   ```powershell
   Get-FileHash .\JARVIS-Setup-0.9.0.exe -Algorithm SHA256
   ```
3. Execute. O NSIS cria:
   - `%LOCALAPPDATA%\Programs\JARVIS AI\` (aplicacao)
   - atalho **JARVIS AI** no Menu Iniciar e no Desktop
   - entrada opcional de inicializacao com o Windows (desativada por padrao)
4. Ao abrir, o backend sobe em `127.0.0.1:8765` e um token e gravado em
   `%APPDATA%\JARVIS AI\runtime-token` (somente leitura/escrita do seu usuario).

> Sem certificado de assinatura configurado, o SmartScreen pode exibir "Windows protegeu o seu PC".
> Verifique o hash e prossiga por "Mais informacoes". O app nunca baixa ou instala atualizacoes
> silenciosamente.

## Primeiros passos

1. **Configuracoes → PIN local**: 6 ou mais digitos. Sem PIN, acoes de alto risco nao podem ser
   aprovadas.
2. **Seguranca**: conceda os escopos necessarios (arquivos, automacao, tela, shell, internet). O
   padrao e tudo negado.
3. **Configuracoes → Modelos**: opcional. Sem chave, o assistente usa regras locais e avisa.
4. **Cakto** (opcional): `client_id` e `client_secret` da chave publica/privada, ambiente
   `production` ou `demo`; use "Verificar conexao" e depois "Sincronizar Cakto".
5. **Dispositivos** (opcional): gere um codigo de pareamento para o iPhone.

## Bandeja, janela flutuante e atalhos

- Fechar a janela **nao encerra** o app: ele vai para a bandeja.
- `Ctrl + Shift + J`: mostrar/esconder o modo flutuante (sempre no topo).
- Menu da bandeja: Abrir, Modo flutuante, **PARAR JARVIS**, Reiniciar backend, Sair.
- "Sempre no topo" e "Iniciar com o Windows" ficam em Configuracoes → Aplicativo.

## Parada de emergencia

Tres formas equivalentes:

1. Botao vermelho na barra inferior (icone de parada).
2. Menu da bandeja → **PARAR JARVIS**.
3. Dizer/escrever "Jarvis, pare tudo" ou "parar jarvis".

Efeito: nenhuma nova acao externa inicia; tarefas ativas vao para `paused`. Para liberar:
`POST /api/security/release` (botao em Seguranca). Nenhuma tarefa retoma sozinha.

## Dados, backup e desinstalacao

- Dados: `%APPDATA%\JARVIS AI\` (banco `jarvis.sqlite3`, token, workspace, projetos, backups).
- Backup: Logs → **Backup do banco** gera arquivo consistente em `backups/`.
- Logs: `%APPDATA%\JARVIS AI\logs\backend.log` e a tela Logs (auditoria + eventos).
- Desinstalar: Configuracoes do Windows → Aplicativos → JARVIS AI. O desinstalador **preserva** seus
  dados por padrao (`deleteAppDataOnUninstall: false`). Para remover tudo, apague a pasta acima
  manualmente depois de desinstalar.
- Se voce criou projetos, eles estao em `%APPDATA%\JARVIS AI\workspace\projects` e nao sao apagados
  pelo desinstalador.

## Compilando o instalador

Ver README secao 6. Resumo:

```powershell
python -m venv .venv; .venv\Scripts\activate
pip install -r services\agent-runtime\requirements.txt "pyinstaller==6.11.1"
powershell -ExecutionPolicy Bypass -File services\agent-runtime\build-runtime.ps1
npm ci
npm run dist
```

Verifique antes de distribuir:

```powershell
Get-ChildItem apps\desktop\release\*.exe | ForEach-Object { Get-FileHash $_.FullName -Algorithm SHA256 }
```

## Problemas comuns

| Sintoma | Causa provavel | Acao |
|---|---|---|
| "Runtime local inacessivel" | backend nao iniciou / porta ocupada | Configuracoes → Reiniciar backend; ver `logs/backend.log` |
| Voz nao reconhece | reconhecimento nativo indisponivel no Electron | use texto; configure STT local (faster-whisper) |
| "Permissao negada" ao mover arquivos | raiz nao autorizada | Seguranca → escopo de arquivos → adicionar pasta |
| PIN recusado | PIN nao configurado ou incorreto | redefina em Configuracoes → PIN (exige PIN atual) |
| Cakto "aguardando configuracao externa" | credenciais ausentes | salve `client_id`/`client_secret` e teste a conexao |
| Meta "nao conectado" | token/conta ausentes | configure Meta Ads; publicacao exige aprovacao |
| Godot `validation_pending` | Godot fora do PATH | instale Godot 4 e reabra o app |
| Antivirus bloqueia o exe | binario nao assinado | verifique checksum; assine com certificado proprio |

## Desempenho e limites

- Automacao visual e lenta por natureza; prefira API nativa → UIA → CLI.
- Tarefas usam no maximo `JARVIS_MAX_TOOL_CALLS` chamadas (padrao 40) e 2 tentativas por etapa.
- O runtime e single-user; nao exponha a porta 8765 sem tunel autenticado.
