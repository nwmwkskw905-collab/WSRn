import { useEffect, useRef, useState } from "react";
import { api, bridge, formatDate, usePolling } from "./lib/api";
import { DEFAULT_VOICE, SpeechListener, speak, stopSpeaking } from "./lib/voice";
import type { VoiceSettings } from "./lib/voice";
import { Badge, Button, Icon, Logo, Orb, StatusBadge, ToastProvider, useToast } from "./components/ui";
import { HomePage, ChatPage, VoicePage } from "./pages/HomeChatVoice";
import { TasksPage, AgentsPage, SecurityPage } from "./pages/TasksAgentsSecurity";
import { BusinessPage, SalesPage, CaktoPage, AdsPage, CrmPage } from "./pages/Commerce";
import { ResearchPage, DevelopmentPage, GameStudioPage, ProjectsPage, MemoryPage } from "./pages/KnowledgeBuild";
import { ComputerPage, DevicesPage, LogsPage, SettingsPage } from "./pages/System";
import type { PageProps } from "./pages/types";
import type { AppInfo } from "../shared/contracts";

const NAV = [
  { group: "Nucleo", items: [
    { id: "home", label: "Home", icon: "home" },
    { id: "chat", label: "Conversa", icon: "chat" },
    { id: "voice", label: "Voz", icon: "voice" },
    { id: "computer", label: "Computador", icon: "computer" },
    { id: "tasks", label: "Tarefas", icon: "tasks" },
    { id: "agents", label: "Agentes", icon: "agents" },
  ]},
  { group: "Inteligencia", items: [
    { id: "research", label: "Internet e pesquisa", icon: "research" },
  ]},
  { group: "Comercial", items: [
    { id: "business", label: "Negocios", icon: "business" },
    { id: "sales", label: "Vendas", icon: "sales" },
    { id: "cakto", label: "Cakto", icon: "cakto" },
    { id: "ads", label: "Anuncios", icon: "ads" },
    { id: "crm", label: "CRM", icon: "crm" },
  ]},
  { group: "Criacao", items: [
    { id: "development", label: "Desenvolvimento", icon: "dev" },
    { id: "gamestudio", label: "Game Studio", icon: "game" },
    { id: "projects", label: "Projetos", icon: "projects" },
    { id: "memory", label: "Memoria", icon: "memory" },
  ]},
  { group: "Sistema", items: [
    { id: "devices", label: "Dispositivos", icon: "devices" },
    { id: "security", label: "Seguranca", icon: "security" },
    { id: "logs", label: "Logs", icon: "logs" },
    { id: "settings", label: "Configuracoes", icon: "settings" },
  ]},
];

function loadVoice(): VoiceSettings {
  try {
    const raw = localStorage.getItem("jarvis.voice");
    if (raw) return { ...DEFAULT_VOICE, ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
  return DEFAULT_VOICE;
}

function FloatingShell({ status, onExpand }: { status: any; onExpand: () => void }) {
  const tasks = usePolling("/api/tasks?limit=5", 3000);
  const messages = usePolling("/api/messages?conversation_id=main&limit=4", 5000);
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const listener = useRef<SpeechListener | null>(null);
  const last = messages.data?.messages?.filter((m: any) => m.role === "assistant").slice(-1)[0];
  const stop = async () => { await api("/api/security/stop", { method: "POST", body: { reason: "Modo flutuante" } }); };

  const send = async (text: string) => {
    if (!text.trim()) return;
    setBusy(true);
    await api("/api/chat", { method: "POST", body: { message: text, conversation_id: "main" } });
    setBusy(false);
    await messages.refresh();
    await tasks.refresh();
  };

  return (
    <div className="floating-shell">
      <header className="floating-head">
        <div className="row gap-sm"><Logo size={26} /><strong>JARVIS</strong></div>
        <div className="row gap-xs">
          <Badge tone={status?.kill_switch ? "bad" : "good"}>{status?.kill_switch ? "PARADO" : "ONLINE"}</Badge>
          <Button variant="ghost" icon="external" onClick={onExpand} title="Expandir" />
        </div>
      </header>
      <div className="floating-body">
        <Orb size={200} listening={listening} active={busy} />
        <p className="floating-reply">{last?.content || "Pronto. Fale ou digite um comando."}</p>
        <div className="row gap-sm">
          <button className={`mic-btn ${listening ? "listening" : ""}`} onClick={() => {
            if (listening) { listener.current?.stop(); setListening(false); return; }
            listener.current = new SpeechListener((text, final) => { if (final) void send(text); }, setListening, () => setListening(false));
            listener.current.start(false);
          }}><Icon name="mic" size={20} /></button>
          <input placeholder="Comando rapido" onKeyDown={(e) => { if (e.key === "Enter") { void send((e.target as HTMLInputElement).value); (e.target as HTMLInputElement).value = ""; } }} />
          <Button variant="danger" icon="stop" onClick={stop} title="Parar tudo" />
        </div>
        <div className="floating-tasks">
          {tasks.data?.tasks?.slice(0, 3).map((task: any) => (
            <div key={task.id} className="floating-task"><span>{task.objective}</span><StatusBadge status={task.status} /></div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Shell() {
  const { notify } = useToast();
  const [page, setPage] = useState("home");
  const [status, setStatus] = useState<any>(null);
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [floating, setFloating] = useState(false);
  const [voice, setVoiceState] = useState<VoiceSettings>(loadVoice);
  const [command, setCommand] = useState("");
  const [online, setOnline] = useState<boolean | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const approvals = usePolling("/api/approvals?status=pending", 6000);
  const activeTasks = usePolling("/api/tasks?limit=30", 5000);

  const refreshStatus = async () => {
    const result = await api("/api/status");
    if (result.ok) { setStatus(result.data); setOnline(true); }
    else setOnline(false);
  };

  useEffect(() => {
    void refreshStatus();
    const timer = window.setInterval(refreshStatus, 5000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    void api("/api/settings").then((result) => {
      const stored = result.data?.voice;
      if (stored) {
        const merged = { ...DEFAULT_VOICE, ...stored };
        setVoiceState(merged);
        localStorage.setItem("jarvis.voice", JSON.stringify(merged));
      }
    });
    void bridge()?.info().then(setInfo).catch(() => undefined);
    const unsubscribe = bridge()?.onFloating((value) => setFloating(value));
    return () => unsubscribe?.();
  }, []);

  const setVoice = (value: VoiceSettings) => {
    setVoiceState(value);
    localStorage.setItem("jarvis.voice", JSON.stringify(value));
  };

  const navigate = (id: string) => { setPage(id); setNavOpen(false); stopSpeaking(); };

  const submitCommand = async () => {
    const message = command.trim();
    if (!message) return;
    setCommand("");
    const result = await api("/api/chat", { method: "POST", body: { message, conversation_id: "main" } });
    if (!result.ok) { notify(result.error || "Falha ao enviar comando", "bad"); return; }
    notify("Comando enviado ao motor de execucao.", "good");
    if (voice.enabled && result.data?.reply) void speak(result.data.reply, voice);
    setPage("tasks");
    await activeTasks.refresh();
  };

  const props: PageProps = { status, refreshStatus, voice, setVoice, navigate, info };
  const pages: Record<string, React.ReactNode> = {
    home: <HomePage {...props} />, chat: <ChatPage {...props} />, voice: <VoicePage {...props} />,
    computer: <ComputerPage {...props} />, tasks: <TasksPage {...props} />, agents: <AgentsPage {...props} />,
    research: <ResearchPage {...props} />, business: <BusinessPage {...props} />, sales: <SalesPage {...props} />,
    cakto: <CaktoPage {...props} />, ads: <AdsPage {...props} />, crm: <CrmPage {...props} />,
    development: <DevelopmentPage {...props} />, gamestudio: <GameStudioPage {...props} />, projects: <ProjectsPage {...props} />,
    memory: <MemoryPage {...props} />, devices: <DevicesPage {...props} />, security: <SecurityPage {...props} />,
    logs: <LogsPage {...props} />, settings: <SettingsPage {...props} />,
  };

  if (floating) {
    return <FloatingShell status={status} onExpand={async () => { await bridge()?.setFloating(false); setFloating(false); }} />;
  }

  const activeCount = activeTasks.data?.tasks?.filter((t: any) => ["running", "planning", "queued", "awaiting_approval"].includes(t.status)).length || 0;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <button className="nav-toggle" onClick={() => setNavOpen(!navOpen)} aria-label="Menu"><Icon name="logs" /></button>
          <Logo size={34} />
          <div><strong>JARVIS <span className="brand-ai">AI</span></strong><span className="muted small">assistente autonomo · v{status?.version || "0.9.0"}</span></div>
        </div>
        <div className="topbar-status">
          <span className={`status-dot ${online ? "online" : "offline"}`} />
          <span className="muted small">{online ? `runtime ${status?.host}:${status?.port}` : "backend offline"}</span>
          <Badge tone={status?.kill_switch ? "bad" : "good"}>{status?.kill_switch ? "PARADO" : "OPERACIONAL"}</Badge>
          <Badge tone="neutral">{status?.mode || "demo"}</Badge>
          {activeCount > 0 && <Badge tone="info">{activeCount} ativas</Badge>}
        </div>
        <div className="topbar-actions">
          <Button variant="ghost" icon="computer" title="Modo flutuante" onClick={() => void bridge()?.setFloating(true)} />
          <Button variant="ghost" icon="minimize" title="Minimizar" onClick={() => void bridge()?.minimize()}><Icon name="pause" size={14} /></Button>
          <Button variant="ghost" icon="x" title="Fechar para bandeja" onClick={() => void bridge()?.close()}><Icon name="x" size={14} /></Button>
        </div>
      </header>

      {online === false && (
        <div className="offline-banner">
          <Icon name="alert" size={18} />
          <span>Runtime local inacessivel. Inicie o backend Python ou use “Reiniciar backend” em Configuracoes.</span>
          <Button icon="refresh" onClick={async () => { await bridge()?.restartBackend(); await refreshStatus(); }}>Reiniciar</Button>
        </div>
      )}

      <div className="shell-body">
        <nav className={`sidenav ${navOpen ? "open" : ""}`} aria-label="Modulos">
          {NAV.map((section) => (
            <div key={section.group} className="nav-section">
              <span className="nav-group">{section.group}</span>
              {section.items.map((item) => (
                <button key={item.id} className={`nav-item ${page === item.id ? "active" : ""}`} onClick={() => navigate(item.id)} title={item.label}>
                  <Icon name={item.icon} size={17} />
                  <span>{item.label}</span>
                  {item.id === "tasks" && activeCount > 0 && <em className="nav-badge">{activeCount}</em>}
                  {item.id === "security" && (approvals.data?.approvals?.length || 0) > 0 && <em className="nav-badge warn">{approvals.data.approvals.length}</em>}
                </button>
              ))}
            </div>
          ))}
          <div className="nav-foot">
            <span className={`status-dot ${online ? "online" : "offline"}`} />
            <span className="small">{status?.platform?.split(" ")[0] || "runtime"} · {status?.vault_backend || "-"}</span>
          </div>
        </nav>

        <main className="main-area">
          <div className="page-scroll">{pages[page] || pages.home}</div>
        </main>

        <aside className="rightrail">
          <section className="rail-card">
            <header><h4>Atividade</h4><span className="status-dot pulse" /></header>
            {activeTasks.data?.tasks?.filter((t: any) => ["running", "planning", "queued", "awaiting_approval"].includes(t.status)).slice(0, 5).map((task: any) => (
              <div key={task.id} className="rail-task"><span>{task.objective}</span><StatusBadge status={task.status} /></div>
            ))}
            {!activeCount && <p className="muted small">Nenhuma tarefa em execucao.</p>}
          </section>
          <section className="rail-card">
            <header><h4>Aprovacoes</h4><Badge tone={approvals.data?.approvals?.length ? "warn" : "good"}>{approvals.data?.approvals?.length || 0}</Badge></header>
            {approvals.data?.approvals?.slice(0, 3).map((approval: any) => (
              <button key={approval.id} className="rail-approval" onClick={() => navigate("security")}>
                <strong>{approval.action}</strong>
                <span className="muted small">{approval.risk} · {formatDate(approval.created_at)}</span>
              </button>
            ))}
            {!approvals.data?.approvals?.length && <p className="muted small">Nada pendente. Acoes rotineiras seguem sem interrupcao.</p>}
          </section>
          <section className="rail-card">
            <header><h4>Estado</h4></header>
            <div className="rail-line"><span>Cofre</span><strong>{status?.vault_backend || "-"}</strong></div>
            <div className="rail-line"><span>Permissoes</span><strong>{status?.permissions_granted || 0}/{status?.permissions_total || 0}</strong></div>
            <div className="rail-line"><span>PIN</span><strong>{status?.pin_configured ? "sim" : "nao"}</strong></div>
            <div className="rail-line"><span>Automacao</span><strong>{status?.capabilities?.windows_automation ? "Windows" : "limitada"}</strong></div>
            <div className="rail-line"><span>Godot</span><strong>{status?.capabilities?.godot ? "ok" : "ausente"}</strong></div>
          </section>
          <section className="rail-card hint-card">
            <Icon name="spark" size={18} />
            <p className="small">Digite <code>Ctrl</code> + <code>Shift</code> + <code>J</code> para abrir o JARVIS. O modo flutuante fica sempre no topo.</p>
          </section>
        </aside>
      </div>

      <footer className="commandbar">
        <div className="command-input">
          <Icon name="terminal" size={18} />
          <input value={command} onChange={(e) => setCommand(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void submitCommand(); }}
            placeholder="Comande o JARVIS… ex.: “organize meus Downloads”, “mostre as vendas dos ultimos 7 dias”" aria-label="Comando" />
        </div>
        <div className="command-actions">
          <button className="mic-btn small" title="Falar" onClick={() => { setPage("chat"); notify("Use o microfone na tela de conversa para enviar comandos de voz.", "info"); }}><Icon name="mic" size={17} /></button>
          <Button variant="primary" icon="send" onClick={submitCommand} disabled={!command.trim()}>Executar</Button>
          <Button variant="danger" icon="stop" title="Parar tudo" onClick={async () => { const result = await api("/api/security/stop", { method: "POST", body: { reason: "Botao inferior" } }); notify(result.ok ? "Parada de emergencia ativada." : result.error || "Falha", result.ok ? "warn" : "bad"); await refreshStatus(); }} />
        </div>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  );
}
