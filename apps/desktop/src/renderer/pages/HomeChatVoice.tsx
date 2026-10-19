import { useEffect, useMemo, useRef, useState } from "react";
import { api, formatDate, formatMoney, useApi, usePolling } from "../lib/api";
import { SpeechListener, extractCommand, listVoices, speak, stopSpeaking } from "../lib/voice";
import type { VoiceSettings } from "../lib/voice";
import { Badge, Button, Card, Empty, Field, Icon, Metric, Orb, Spinner, StatusBadge, Toggle, useToast } from "../components/ui";
import type { PageProps } from "./types";

const QUICK = [
  { label: "Organizar arquivos", command: "Jarvis, organize meus arquivos da pasta Downloads", icon: "folder" },
  { label: "Criar site", command: "Jarvis, crie uma aplicação web de cadastro de produtos", icon: "dev" },
  { label: "Preparar campanha", command: "Jarvis, prepare uma campanha de Meta Ads para meu produto", icon: "ads" },
  { label: "Vendas 7 dias", command: "Jarvis, mostre o resultado das vendas dos últimos sete dias", icon: "sales" },
  { label: "Criar jogo", command: "Jarvis, crie um jogo de corrida de motos", icon: "game" },
  { label: "Pesquisar mercado", command: "Jarvis, pesquise oportunidades de negócios digitais para pequenas empresas brasileiras", icon: "research" },
];

export function HomePage({ status, refreshStatus, navigate }: PageProps) {
  const tasks = usePolling("/api/tasks?limit=6", 4000);
  const approvals = usePolling("/api/approvals?status=pending", 5000);
  const diagnostics = usePolling("/api/diagnostics", 20000);
  const running = Object.entries(status?.tasks || {}).filter(([key]) => ["running", "planning", "queued"].includes(key)).reduce((sum: number, [, value]: any) => sum + value, 0);
  const checks = diagnostics.data?.checks || [];
  const goodChecks = checks.filter((c: any) => c.status === "ok").length;
  return (
    <div className="page home">
      <div className="hero">
        <div className="hero-orb">
          <Orb size={340} active={running > 0} listening={false} />
          <div className="orb-caption">
            <span className="eyebrow">NUCLEO OPERACIONAL</span>
            <strong>{status?.kill_switch ? "AUTOMACOES SUSPENSAS" : running ? "EXECUTANDO TAREFAS" : "EM ESPERA"}</strong>
            <span className="muted">{status?.kill_switch ? "Parada de emergencia ativa" : "Sistemas monitorados em tempo real"}</span>
          </div>
        </div>
        <div className="hero-copy">
          <span className="eyebrow">JARVIS AI · v{status?.version || "0.9.0"}</span>
          <h1>Seu centro de comando para executar, verificar e reportar.</h1>
          <p className="muted">
            Agentes especializados, ferramentas reais e permissoes explicitas. O JARVIS prepara acoes,
            pausa para aprovacao quando necessario e nunca inventa resultados.
          </p>
          <div className="row wrap gap-sm">
            <Button variant="primary" icon="chat" onClick={() => navigate("chat")}>Conversar</Button>
            <Button icon="tasks" onClick={() => navigate("tasks")}>Nova tarefa</Button>
            <Button icon="shield" onClick={() => navigate("security")}>Permissoes</Button>
          </div>
          <div className="status-chips">
            <Badge tone={status?.kill_switch ? "bad" : "good"}>{status?.kill_switch ? "PARADO" : "OPERACIONAL"}</Badge>
            <Badge tone={status?.vault_available ? "good" : "bad"}>Cofre: {status?.vault_backend || "-"}</Badge>
            <Badge tone={status?.pin_configured ? "good" : "warn"}>{status?.pin_configured ? "PIN configurado" : "PIN pendente"}</Badge>
            <Badge tone={status?.capabilities?.windows_automation ? "good" : "warn"}>{status?.capabilities?.windows_automation ? "Windows nativo" : "Somente leitura de automacao"}</Badge>
          </div>
        </div>
      </div>

      <div className="metric-grid">
        <Metric label="Tarefas em andamento" value={running} hint="execucao com checkpoints" tone={running ? "info" : "neutral"} />
        <Metric label="Aprovacoes pendentes" value={approvals.data?.approvals?.length ?? 0} hint="acoes de alto impacto" tone={(approvals.data?.approvals?.length ?? 0) > 0 ? "warn" : "good"} />
        <Metric label="Permissoes ativas" value={`${status?.permissions_granted ?? 0}/${status?.permissions_total ?? 0}`} hint="escopos explicitos" />
        <Metric label="Diagnostico" value={`${goodChecks}/${checks.length || "-"}`} hint="checagens locais OK" tone={checks.length && goodChecks === checks.length ? "good" : "warn"} />
      </div>

      <div className="two-col">
        <Card title="Tarefas recentes" subtitle="Estado real persistido no banco local" actions={<Button variant="ghost" icon="refresh" onClick={() => { void tasks.refresh(); refreshStatus(); }}>Atualizar</Button>}>
          {tasks.loading && !tasks.data ? <Spinner label="Consultando tarefas" /> : null}
          {tasks.data?.tasks?.length ? (
            <div className="task-list">
              {tasks.data.tasks.map((task: any) => (
                <button key={task.id} className="task-row" onClick={() => navigate("tasks")}>
                  <div className="task-row-main">
                    <strong>{task.objective}</strong>
                    <span className="muted">{formatDate(task.created_at)} · nivel {task.autonomy_level}</span>
                  </div>
                  <StatusBadge status={task.status} />
                </button>
              ))}
            </div>
          ) : <Empty title="Nenhuma tarefa ainda" hint="Use o campo de comando ou um atalho abaixo." />}
        </Card>
        <Card title="Prontidao do sistema" subtitle="Checagens executadas agora">
          <div className="check-list">
            {checks.map((check: any) => (
              <div key={check.name} className="check-row">
                <Icon name={check.status === "ok" ? "check" : check.status === "warning" ? "alert" : "x"} size={15} />
                <span>{check.name.replaceAll("_", " ")}</span>
                <StatusBadge status={check.status} />
              </div>
            ))}
            {!checks.length && <Spinner label="Executando diagnostico" />}
          </div>
        </Card>
      </div>

      <Card title="Comandos rapidos" subtitle="Cada botao cria uma tarefa real no motor de execucao">
        <div className="quick-grid">
          {QUICK.map((item) => (
            <button key={item.label} className="quick" onClick={async () => {
              await api("/api/chat", { method: "POST", body: { message: item.command, conversation_id: "main" } });
              navigate("tasks");
            }}>
              <Icon name={item.icon} size={20} />
              <span>{item.label}</span>
              <small className="muted">{item.command.replace("Jarvis, ", "")}</small>
            </button>
          ))}
        </div>
      </Card>
    </div>
  );
}

export function ChatPage({ voice, setVoice, status }: PageProps) {
  const { notify } = useToast();
  const [conversation] = useState("main");
  const messages = usePolling(`/api/messages?conversation_id=${conversation}`, 4000);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const listener = useRef<SpeechListener | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.data?.messages?.length]);

  useEffect(() => () => listener.current?.stop(), []);

  const send = async (value?: string) => {
    const message = (value ?? text).trim();
    if (!message || sending) return;
    setSending(true);
    setText("");
    stopSpeaking();
    const result = await api("/api/chat", { method: "POST", body: { message, conversation_id: conversation, speak: voice.enabled } });
    setSending(false);
    if (!result.ok) {
      notify(result.error || "Falha ao enviar", "bad");
      return;
    }
    await messages.refresh();
    const reply = result.data?.reply || "";
    if (voice.enabled) void speak(reply, voice);
  };

  const toggleMic = () => {
    if (listening) {
      listener.current?.stop();
      setListening(false);
      return;
    }
    const instance = new SpeechListener(
      (transcript, final) => {
        setInterim(transcript);
        if (final) {
          setInterim("");
          void send(transcript.replace(/^jarvis[,:\s]*/i, ""));
        }
      },
      (state) => setListening(state),
      (message) => notify(message, "warn"),
    );
    listener.current = instance;
    instance.start(false);
  };

  const allMessages = messages.data?.messages || [];
  return (
    <div className="page chat-page">
      <Card className="chat-card" title="Conversa" subtitle="Comandos sao roteados para tarefas verificaveis"
        actions={<>
          <Toggle checked={voice.enabled} onChange={(value) => setVoice({ ...voice, enabled: value })} label="Voz" />
          <Button variant="ghost" icon="stop" onClick={() => { stopSpeaking(); listener.current?.stop(); }} title="Interromper fala/escuta" />
        </>}>
        <div className="chat-log" ref={scrollRef}>
          {!allMessages.length && (
            <div className="chat-empty">
              <Orb size={180} active={sending} />
              <p>Diga <strong>“Jarvis, organize meus Downloads”</strong> ou escolha um comando no painel inicial.</p>
            </div>
          )}
          {allMessages.map((message: any) => (
            <div key={message.id} className={`bubble bubble-${message.role}`}>
              <div className="bubble-head">
                <strong>{message.role === "user" ? "Voce" : "JARVIS"}</strong>
                <span className="muted">{formatDate(message.ts)}</span>
              </div>
              <div className="bubble-body">{message.content}</div>
              {message.meta?.task_id && (
                <div className="bubble-meta">
                  <Badge tone="info">tarefa {message.meta.task_id.slice(0, 10)}</Badge>
                  {message.meta?.provider && <Badge tone={message.meta.provider === "local-rules" ? "warn" : "good"}>{message.meta.provider}</Badge>}
                </div>
              )}
            </div>
          ))}
          {interim && <div className="bubble bubble-user interim"><span>{interim}</span></div>}
        </div>
        <div className="composer">
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Escreva um comando ou pergunta..."
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} rows={2} />
          <div className="composer-actions">
            <button className={`mic-btn ${listening ? "listening" : ""}`} onClick={toggleMic} title="Falar">
              <Icon name="mic" size={20} />
            </button>
            <Button variant="primary" icon="send" onClick={() => void send()} disabled={sending || !text.trim()}>{sending ? "Enviando" : "Enviar"}</Button>
          </div>
        </div>
        {status?.kill_switch && <div className="alert alert-bad">Parada de emergencia ativa: comandos que exigem acao externa serao bloqueados.</div>}
        <p className="muted small">Reconhecimento de voz usa a Web Speech API do Chromium. Sem chave de servico, o Windows pode limitar o reconhecimento; o modo texto permanece funcional.</p>
      </Card>
    </div>
  );
}

export function VoicePage({ voice, setVoice }: PageProps) {
  const { notify } = useToast();
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const listener = useRef<SpeechListener | null>(null);
  const [wake, setWake] = useState(false);
  const [testText, setTestText] = useState("JARVIS operacional. Estou monitorando suas tarefas e permissoes.");

  useEffect(() => {
    const load = () => setVoices(listVoices());
    load();
    window.speechSynthesis?.addEventListener?.("voiceschanged", load);
    return () => window.speechSynthesis?.removeEventListener?.("voiceschanged", load);
  }, []);

  useEffect(() => () => listener.current?.stop(), []);

  const start = () => {
    listener.current = new SpeechListener(
      (text, final) => {
        setTranscript(text);
        if (final && wake) {
          const command = extractCommand(text, true);
          if (command) notify(`Comando detectado: ${command}`, "info");
        }
      },
      setListening,
      (message) => notify(message, "warn"),
    );
    listener.current.start(wake);
  };

  return (
    <div className="page">
      <div className="two-col">
        <Card title="Voz e fala" subtitle="Sintese local do sistema; STT opcional no runtime">
          <div className="voice-panel">
            <Orb size={200} listening={listening} />
            <div>
              <Badge tone={listening ? "good" : "neutral"}>{listening ? "MICROFONE ATIVO" : "MICROFONE INATIVO"}</Badge>
              <p className="muted small">O microfone so e ativado por voce. Nenhum audio e gravado em disco por este aplicativo.</p>
              <div className="row gap-sm">
                <Button variant={listening ? "danger" : "primary"} icon={listening ? "stop" : "mic"} onClick={() => listening ? listener.current?.stop() : start()}>
                  {listening ? "Parar escuta" : "Iniciar escuta"}
                </Button>
                <Toggle checked={wake} onChange={(value) => { setWake(value); if (listening) { listener.current?.stop(); window.setTimeout(start, 300); } }} label="Palavra de ativacao" />
              </div>
            </div>
          </div>
          <div className="transcript-box">{transcript || "A transcricao aparece aqui. Diga “Jarvis, ...”. O modo contínuo depende do suporte do Chromium no Windows; no Electron ele pode exigir STT local (faster-whisper) ou provedor configurado."}</div>
        </Card>
        <Card title="Ajustes de fala" subtitle="Aplicados imediatamente">
          <Field label="Voz"><select value={voice.voiceName} onChange={(e) => setVoice({ ...voice, voiceName: e.target.value })}>
            <option value="">Padrao do sistema</option>
            {voices.map((v) => <option key={v.name} value={v.name}>{v.name} ({v.lang})</option>)}
          </select></Field>
          <div className="grid-2">
            <Field label={`Velocidade (${voice.rate.toFixed(2)})`}><input type="range" min={0.6} max={1.8} step={0.02} value={voice.rate} onChange={(e) => setVoice({ ...voice, rate: Number(e.target.value) })} /></Field>
            <Field label={`Tom (${voice.pitch.toFixed(2)})`}><input type="range" min={0.6} max={1.6} step={0.02} value={voice.pitch} onChange={(e) => setVoice({ ...voice, pitch: Number(e.target.value) })} /></Field>
          </div>
          <Field label={`Volume (${Math.round(voice.volume * 100)}%)`}><input type="range" min={0} max={1} step={0.05} value={voice.volume} onChange={(e) => setVoice({ ...voice, volume: Number(e.target.value) })} /></Field>
          <Field label="Texto de teste"><textarea rows={3} value={testText} onChange={(e) => setTestText(e.target.value)} /></Field>
          <div className="row wrap gap-sm">
            <Button variant="primary" icon="play" onClick={() => void speak(testText, { ...voice, enabled: true })}>Ouvir teste</Button>
            <Button icon="stop" onClick={stopSpeaking}>Interromper</Button>
            <Button icon="check" onClick={async () => {
              const result = await api("/api/settings/voice", { method: "PUT", body: { value: voice } });
              notify(result.ok ? "Preferencias de voz salvas." : result.error || "Falha ao salvar", result.ok ? "good" : "bad");
            }}>Salvar</Button>
          </div>
          <p className="muted small">Vozes listadas sao as instaladas no Windows/browser. Nao imitamos atores ou pessoas reais. Para STT de alta qualidade offline, instale faster-whisper no runtime (nao incluido por padrao).</p>
        </Card>
      </div>
    </div>
  );
}
