import { useEffect, useState } from "react";
import { api, bridge, formatDate, formatMoney, usePolling } from "../lib/api";
import { Badge, Button, Card, CodeBlock, CopyButton, Empty, Field, Metric, Spinner, StatusBadge, Toggle, useToast } from "../components/ui";
import type { PageProps } from "./types";

export function ComputerPage({ status, refreshStatus }: PageProps) {
  const { notify } = useToast();
  const tools = usePolling("/api/tools", 30000);
  const perms = usePolling("/api/permissions", 10000);
  const [apps, setApps] = useState("notepad, calc, mspaint, explorer");
  const [path, setPath] = useState("Downloads");
  const [notepadText, setNotepadText] = useState("Lista de tarefas:\n- Revisar prioridades\n- Executar proximo passo");
  const isWindows = status?.capabilities?.windows_automation;

  useEffect(() => {
    void api("/api/settings").then((result) => {
      const value = result.data?.["windows.allowed_apps"];
      if (Array.isArray(value)) setApps(value.join(", "));
    });
  }, []);

  const grant = async (scope: string, granted: boolean) => {
    await api("/api/permissions", { method: "POST", body: { scope, granted, config: {} } });
    await perms.refresh();
    refreshStatus();
    notify(`${scope} ${granted ? "concedido" : "revogado"}.`, granted ? "good" : "warn");
  };

  return (
    <div className="page">
      {!isWindows && <div className="alert alert-warn">Este ambiente nao e Windows. As ferramentas de automacao existem, mas recusam executar e retornam “plataforma nao suportada”. Nada e simulado.</div>}
      <div className="metric-grid">
        <Metric label="Automacao" value={isWindows ? "disponivel" : "indisponivel"} hint="pywinauto/UIA no Windows" tone={isWindows ? "good" : "warn"} />
        <Metric label="Captura de tela" value={perms.data?.permissions?.find((p: any) => p.scope === "screen.capture")?.granted ? "permitida" : "bloqueada"} hint="requer permissao" />
        <Metric label="Mouse/teclado" value={perms.data?.permissions?.find((p: any) => p.scope === "automation.input")?.granted ? "permitido" : "bloqueado"} hint="alto impacto + aprovacao" />
        <Metric label="Comandos locais" value={perms.data?.permissions?.find((p: any) => p.scope === "shell.execute")?.granted ? "permitidos" : "bloqueados"} hint="lista branca" />
      </div>
      <div className="two-col">
        <Card title="Controle do Windows" subtitle="Acoes reais com verificacao; alto risco pede aprovacao">
          <div className="row wrap gap-sm">
            <Button icon="chat" onClick={() => void grant("automation.input", true)}>Permitir automacao</Button>
            <Button icon="computer" onClick={() => void grant("screen.capture", true)}>Permitir captura</Button>
            <Button icon="terminal" onClick={() => void grant("shell.execute", true)}>Permitir comandos</Button>
          </div>
          <Field label="Aplicativos permitidos (lista branca)" hint="Separados por virgula; nenhum outro app sera aberto automaticamente."><input value={apps} onChange={(e) => setApps(e.target.value)} /></Field>
          <Button icon="check" onClick={async () => {
            const list = apps.split(",").map((s) => s.trim()).filter(Boolean);
            await api("/api/settings/windows.allowed_apps", { method: "PUT", body: { value: list } });
            notify("Lista de aplicativos salva.", "good");
          }}>Salvar lista</Button>
          <Field label="Texto para o Bloco de Notas"><textarea rows={3} value={notepadText} onChange={(e) => setNotepadText(e.target.value)} /></Field>
          <Button variant="primary" icon="computer" onClick={async () => {
            const result = await api("/api/chat", { method: "POST", body: { message: `Jarvis, abra o Bloco de Notas e escreva: ${notepadText.replace(/\n/g, " | ")}`, conversation_id: "computer" } });
            notify(result.ok ? "Tarefa criada; aprovacao pode ser necessaria." : result.error || "Falha", result.ok ? "info" : "bad");
          }}>Executar no Windows</Button>
          <Field label="Pasta para organizar"><input value={path} onChange={(e) => setPath(e.target.value)} /></Field>
          <Button icon="folder" onClick={async () => {
            const result = await api("/api/chat", { method: "POST", body: { message: `Jarvis, organize os arquivos da pasta "${path}"`, conversation_id: "computer" } });
            notify(result.ok ? "Tarefa de organizacao criada." : result.error || "Falha", result.ok ? "info" : "bad");
          }}>Organizar arquivos</Button>
          <p className="muted small">Ordem de preferencia: APIs nativas → acessibilidade (UIA) → seletores de navegador → CLI → visao → coordenadas. Nunca contornamos UAC, login ou anticheat.</p>
        </Card>
        <Card title="Ferramentas registradas" subtitle="Escopos e riscos declarados">
          <div className="tool-list">
            {tools.data?.tools?.map((tool: any) => (
              <div key={tool.name} className="tool-row">
                <div><code>{tool.name}</code><span className="muted small">{tool.description}</span></div>
                <div className="row gap-xs"><Badge tone="neutral">{tool.scope}</Badge><Badge tone={tool.risk === "high" ? "bad" : tool.risk === "medium" ? "warn" : "good"}>{tool.risk}</Badge></div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

export function DevicesPage(_props: PageProps) {
  const { notify } = useToast();
  const devices = usePolling("/api/mobile/devices", 10000);
  const [pair, setPair] = useState<any>(null);
  const [url, setUrl] = useState("");
  return (
    <div className="page">
      <div className="two-col">
        <Card title="iPhone · PWA pareada" subtitle="Comandos e relatorios pelo telefone, com o PC como nucleo">
          <div className="row wrap gap-sm">
            <Badge tone="warn">validacao em dispositivo fisico pendente</Badge>
            <Badge tone="neutral">HTTPS obrigatorio</Badge>
          </div>
          <p className="muted small">A Apple nao permite controle irrestrito de outros aplicativos. O escopo suportado e: enviar comandos, consultar tarefas/vendas, receber notificacoes e aprovar operacoes com PIN.</p>
          <Field label="URL publica do runtime (tunel HTTPS)" hint="Ex.: Tailscale Funnel ou Cloudflare Tunnel apontando para 127.0.0.1:8765."><input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://jarvis.exemplo.ts.net" /></Field>
          <Button icon="check" onClick={async () => { await api("/api/settings/mobile.public_url", { method: "PUT", body: { value: url } }); notify("URL salva. Reinicie o tunel se necessario.", "good"); }}>Salvar URL</Button>
          <Button variant="primary" icon="devices" onClick={async () => {
            const result = await api("/api/mobile/pair-code", { method: "POST" });
            if (result.ok) { setPair(result.data); notify("Codigo de pareamento gerado (10 minutos).", "good"); }
            else notify(result.error || "Falha", "bad");
          }}>Gerar codigo</Button>
          {pair && (
            <div className="pair-box">
              <span className="eyebrow">CODIGO DE PAREAMENTO</span>
              <div className="pair-code">{pair.code}</div>
              <span className="muted small">Expira em 10 minutos. Informe a URL e o codigo na PWA do iPhone.</span>
              <CopyButton value={pair.code} label="Copiar codigo" />
            </div>
          )}
        </Card>
        <Card title="Dispositivos autorizados" subtitle="Tokens revogaveis">
          {devices.data?.devices?.length ? devices.data.devices.map((device: any) => (
            <div key={device.prefix} className="list-row">
              <div><strong>{device.device}</strong><span className="muted small">{device.masked || device.prefix} · {formatDate(device.created_at)}</span></div>
              <Button variant="danger" icon="trash" onClick={async () => { await api(`/api/mobile/devices/${device.prefix}`, { method: "DELETE" }); await devices.refresh(); notify("Dispositivo revogado.", "warn"); }}>Revogar</Button>
            </div>
          )) : <Empty title="Nenhum dispositivo" hint="Gere um codigo e conecte a PWA em apps/mobile-companion." />}
          <p className="muted small">A PWA esta em <code>apps/mobile-companion</code>. Ela exige HTTPS e token pareado; sem isso, nao acessa o runtime.</p>
        </Card>
      </div>
    </div>
  );
}

export function LogsPage({ refreshStatus }: PageProps) {
  const { notify } = useToast();
  const audit = usePolling("/api/logs/audit?limit=120", 6000);
  const diagnostics = usePolling("/api/diagnostics", 15000);
  const events = usePolling("/api/logs/events?limit=80", 6000);
  const [validation, setValidation] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="page">
      <div className="two-col">
        <Card title="Diagnostico" subtitle="Checagens reais do ambiente">
          {diagnostics.data?.checks?.map((check: any) => (
            <div key={check.name} className="check-row"><span>{check.name.replaceAll("_", " ")}</span><StatusBadge status={check.status} />{check.detail && <span className="muted small">{check.detail}</span>}</div>
          ))}
          <p className="muted small">Dados: {diagnostics.data?.paths?.data_dir}</p>
          <div className="row gap-sm">
            <Button icon="download" onClick={async () => {
              const result = await api("/api/backup");
              notify(result.ok ? `Backup criado: ${result.data.path}` : result.error || "Falha", result.ok ? "good" : "bad");
            }}>Backup do banco</Button>
            <Button icon="refresh" onClick={() => { void diagnostics.refresh(); refreshStatus(); }}>Reexecutar</Button>
          </div>
        </Card>
        <Card title="Validacao automatizada" subtitle="Cenarios executados localmente, com evidencias">
          <Button variant="primary" icon="shield" onClick={async () => {
            setBusy(true);
            const result = await api("/api/validation/run", { method: "POST" });
            setBusy(false);
            if (!result.ok) { notify(result.error || "Falha", "bad"); return; }
            setValidation(result.data);
          }} disabled={busy}>{busy ? "Executando cenarios..." : "Executar cenarios seguros"}</Button>
          {busy && <Spinner label="Rodando B, D, J, K, L e memoria" />}
          {validation && (
            <div className="validation-box">
              <div className="row wrap gap-sm">
                <Badge tone="good">{validation.summary.passed} aprovados</Badge>
                <Badge tone="warn">{validation.summary.pending} pendentes</Badge>
                <Badge tone="bad">{validation.summary.failed} falhas</Badge>
              </div>
              {Object.entries(validation.scenarios).map(([key, value]: any) => (
                <div key={key} className="validation-row"><strong>{key}</strong><StatusBadge status={value.status} /><span className="muted small">{value.detail}</span></div>
              ))}
              <p className="muted small">{validation.summary.honesty_note}</p>
            </div>
          )}
        </Card>
      </div>
      <Card title="Auditoria" subtitle="Permissoes, ferramentas, aprovacoes e decisoes">
        <div className="table-wrap tall"><table><thead><tr><th>Quando</th><th>Ator</th><th>Acao</th><th>Recurso</th><th>Decisao</th></tr></thead><tbody>
          {audit.data?.audit?.map((row: any) => <tr key={row.id}><td className="muted small">{formatDate(row.ts)}</td><td>{row.actor}</td><td><code>{row.action}</code></td><td className="small">{row.resource}</td><td><StatusBadge status={row.decision} /></td></tr>)}
        </tbody></table></div>
      </Card>
      <Card title="Eventos do motor" subtitle="Planejamento, execucao, aprovacoes e falhas">
        <div className="event-log tall">
          {events.data?.events?.slice(-60).reverse().map((event: any) => (
            <div key={event.id} className="event-row"><span className="muted small">{formatDate(event.ts)}</span><code>{event.kind}</code><span className="muted small">{JSON.stringify(event.payload).slice(0, 220)}</span></div>
          ))}
        </div>
      </Card>
    </div>
  );
}

export function SettingsPage({ status, info, refreshStatus }: PageProps) {
  const { notify } = useToast();
  const llm = usePolling("/api/llm/state", 10000);
  const [provider, setProvider] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [budget, setBudget] = useState({ monthly_budget_usd: 0, max_calls_per_day: 0, allow_paid: false });
  const [update, setUpdate] = useState<any>(null);
  const [autoLaunch, setAutoLaunch] = useState(false);
  const [alwaysOnTop, setAlwaysOnTop] = useState(false);

  useEffect(() => {
    if (llm.data?.budget?.budget) {
      setBudget({
        monthly_budget_usd: llm.data.budget.budget.monthly_budget_usd,
        max_calls_per_day: llm.data.budget.budget.max_calls_per_day,
        allow_paid: llm.data.budget.budget.allow_paid,
      });
    }
  }, [llm.data]);

  useEffect(() => {
    void bridge()?.getAutoLaunch().then(setAutoLaunch).catch(() => undefined);
  }, []);

  const selected = llm.data?.providers?.find((p: any) => p.id === provider);

  return (
    <div className="page">
      <div className="two-col">
        <Card title="Modelos de IA" subtitle="Cada provedor tem seu proprio adaptador e limites">
          <div className="provider-grid">
            {llm.data?.providers?.map((p: any) => (
              <button key={p.id} className={`provider-card ${provider === p.id ? "active" : ""}`} onClick={() => { setProvider(p.id); setModel(p.model || ""); setBaseUrl(p.base_url || ""); setApiKey(""); }}>
                <div className="row between"><strong>{p.label}</strong><Badge tone={p.status === "ready" ? "good" : "warn"}>{p.status}</Badge></div>
                <span className="muted small">{p.kind} · {p.has_key ? "credencial presente" : p.requires_key ? "credencial ausente" : "sem chave"}</span>
              </button>
            ))}
          </div>
          <Field label="Modelo"><input value={model} onChange={(e) => setModel(e.target.value)} placeholder={selected?.models?.[0] || "modelo"} /></Field>
          {["openai", "anthropic", "gemini"].includes(provider) && <Field label="API key" hint="Guardada no cofre; nunca retornada pela API."><input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></Field>}
          {["ollama", "openai"].includes(provider) && <Field label="Base URL (opcional)"><input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} /></Field>}
          <div className="row gap-sm">
            <Button variant="primary" icon="check" onClick={async () => {
              const result = await api("/api/llm/configure", { method: "POST", body: { provider, api_key: apiKey || undefined, model: model || undefined, base_url: baseUrl || undefined, enabled: true } });
              notify(result.ok ? "Provedor configurado." : result.error || "Falha", result.ok ? "good" : "bad");
              if (result.ok) { setApiKey(""); await llm.refresh(); }
            }}>Salvar</Button>
            <Button icon="x" onClick={async () => {
              await api("/api/llm/configure", { method: "POST", body: { provider, enabled: false } });
              await llm.refresh();
              notify("Provedor desativado.", "warn");
            }}>Desativar</Button>
          </div>
          <p className="muted small">Sem provedor configurado, o JARVIS responde com regras locais e declara isso. Nao simulamos um modelo.</p>
        </Card>
        <Card title="Custo e limites" subtitle="Padrao seguro: nenhum gasto sem autorizacao">
          <div className="grid-2">
            <Field label="Orcamento mensal (US$)" hint="0 = desativado"><input type="number" value={budget.monthly_budget_usd} onChange={(e) => setBudget({ ...budget, monthly_budget_usd: Number(e.target.value) })} /></Field>
            <Field label="Maximo de chamadas/dia"><input type="number" value={budget.max_calls_per_day} onChange={(e) => setBudget({ ...budget, max_calls_per_day: Number(e.target.value) })} /></Field>
          </div>
          <Toggle checked={budget.allow_paid} onChange={(value) => setBudget({ ...budget, allow_paid: value })} label="Autorizo uso de provedores pagos dentro do limite" />
          <Button variant="primary" icon="wallet" onClick={async () => {
            const result = await api("/api/llm/budget", { method: "POST", body: budget });
            notify(result.ok ? "Limites de IA salvos." : result.error || "Falha", result.ok ? "good" : "bad");
            await llm.refresh();
          }}>Salvar limites</Button>
          <div className="metric-grid compact">
            <Metric label="Gasto no mes (US$)" value={(llm.data?.budget?.cost_usd_month ?? 0).toFixed(4)} hint={`fonte: ${llm.data?.budget?.cost_source}`} />
            <Metric label="Chamadas hoje" value={llm.data?.budget?.calls_today ?? 0} />
            <Metric label="Tokens no mes" value={llm.data?.budget?.tokens_month ?? 0} />
            <Metric label="Modo de roteamento" value={llm.data?.routing_mode || "auto"} />
          </div>
          <p className="muted small">Precos por modelo sao configurados por voce (Configuracoes Avancadas). Sem tabela de precos, o custo fica “nao disponivel”, nunca inventado.</p>
        </Card>
      </div>

      <div className="two-col">
        <Card title="Aplicativo" subtitle="Comportamento do desktop">
          <div className="row wrap gap-sm">
            <Toggle checked={autoLaunch} onChange={async (value) => { setAutoLaunch(value); await bridge()?.setAutoLaunch(value); notify(value ? "Inicializacao com Windows ativada." : "Inicializacao desativada.", "info"); }} label="Iniciar com o Windows" />
            <Toggle checked={alwaysOnTop} onChange={async (value) => { setAlwaysOnTop(value); await bridge()?.setAlwaysOnTop(value); }} label="Sempre no topo" />
          </div>
          <div className="row wrap gap-sm">
            <Button icon="computer" onClick={() => void bridge()?.setFloating(true)}>Modo flutuante</Button>
            <Button icon="refresh" onClick={async () => { const result = await bridge()?.restartBackend(); notify(result?.ok ? "Backend reiniciado." : result?.error || "Sem IPC Electron; backend gerenciado externamente.", result?.ok ? "good" : "warn"); refreshStatus(); }}>Reiniciar backend</Button>
            <Button icon="download" onClick={async () => { const result = await bridge()?.checkUpdates(); setUpdate(result || { error: "IPC indisponivel no navegador" }); }}>Verificar atualizacoes</Button>
          </div>
          {update && <div className="result-box"><Badge tone={update.updateAvailable ? "good" : "neutral"}>{update.updateAvailable ? `Atualizacao ${update.latest}` : "Sem atualizacao"}</Badge>{update.error && <span className="muted small">{update.error}</span>}{update.url && <button className="link" onClick={() => void bridge()?.openExternal(update.url)}>Abrir releases</button>}<p className="muted small">Assinatura digital: {update.signature}. Atualizacoes nao sao instaladas silenciosamente.</p></div>}
          <p className="muted small">Electron: contextIsolation={String(info?.secure?.contextIsolation)} · nodeIntegration={String(info?.secure?.nodeIntegration)} · sandbox={String(info?.secure?.sandbox)}</p>
          <p className="muted small">Dados: <code>{info?.dataDir || status?.data_dir}</code></p>
        </Card>
        <Card title="Seguranca e ambiente" subtitle="Estado atual">
          <div className="check-row"><span>Cofre de credenciais</span><Badge tone={status?.vault_available ? "good" : "bad"}>{status?.vault_backend}</Badge></div>
          <div className="check-row"><span>PIN local</span><Badge tone={status?.pin_configured ? "good" : "warn"}>{status?.pin_configured ? "configurado" : "pendente"}</Badge></div>
          <div className="check-row"><span>Parada de emergencia</span><Badge tone={status?.kill_switch ? "bad" : "good"}>{status?.kill_switch ? "ativa" : "inativa"}</Badge></div>
          <div className="check-row"><span>Godot</span><Badge tone={status?.capabilities?.godot ? "good" : "warn"}>{status?.capabilities?.godot ? "instalado" : "ausente"}</Badge></div>
          <div className="check-row"><span>Automacao Windows</span><Badge tone={status?.capabilities?.windows_automation ? "good" : "warn"}>{status?.capabilities?.windows_automation ? "nativa" : "nao disponivel"}</Badge></div>
          <div className="row wrap gap-sm">
            <a className="link" href="https://docs.cakto.com.br" target="_blank" rel="noreferrer">Documentacao Cakto</a>
            <a className="link" href="https://platform.openai.com/docs" target="_blank" rel="noreferrer">OpenAI</a>
            <a className="link" href="https://docs.anthropic.com" target="_blank" rel="noreferrer">Anthropic</a>
          </div>
          <CodeBlock value={`Diagnostico rapido:\nGET ${status?.host || "127.0.0.1"}:${status?.port || 8765}/health\nDados: ${status?.data_dir || "-"}`} />
        </Card>
      </div>
    </div>
  );
}
