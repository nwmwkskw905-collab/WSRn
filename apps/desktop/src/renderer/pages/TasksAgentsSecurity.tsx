import { useEffect, useState } from "react";
import { api, formatDate, shortId, usePolling } from "../lib/api";
import { Badge, Button, Card, Empty, Field, Modal, Spinner, StatusBadge, Toggle, useToast } from "../components/ui";
import type { PageProps } from "./types";

const AUTONOMY = [
  { value: 0, label: "0 · Observacao" },
  { value: 1, label: "1 · Assistencia" },
  { value: 2, label: "2 · Supervisionada" },
  { value: 3, label: "3 · Delimitada" },
  { value: 4, label: "4 · Comercial delegada" },
];

export function TasksPage({ refreshStatus }: PageProps) {
  const { notify } = useToast();
  const [filter, setFilter] = useState("");
  const tasks = usePolling(`/api/tasks${filter ? `?status=${filter}` : ""}`, 3000, [filter]);
  const [objective, setObjective] = useState("");
  const [autonomy, setAutonomy] = useState(1);
  const [mode, setMode] = useState("demo");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!selected) return;
    let active = true;
    const load = async () => {
      const result = await api(`/api/tasks/${selected}`);
      if (active && result.ok) setDetail(result.data);
    };
    void load();
    const timer = window.setInterval(load, 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [selected]);

  const create = async () => {
    if (objective.trim().length < 3) return;
    setBusy(true);
    const result = await api("/api/tasks", { method: "POST", body: { objective, autonomy_level: autonomy, mode } });
    setBusy(false);
    if (result.ok) {
      setObjective("");
      notify("Tarefa criada e enviada ao motor de execucao.", "good");
      await tasks.refresh();
      refreshStatus();
      setSelected(result.data.id);
    } else notify(result.error || "Falha ao criar tarefa", "bad");
  };

  const act = async (taskId: string, action: "cancel" | "pause" | "resume") => {
    const result = await api(`/api/tasks/${taskId}/${action}`, { method: "POST" });
    notify(result.ok ? `Acao ${action} registrada.` : result.error || "Falha", result.ok ? "good" : "bad");
    await tasks.refresh();
    if (selected) {
      const refreshed = await api(`/api/tasks/${selected}`);
      if (refreshed.ok) setDetail(refreshed.data);
    }
    refreshStatus();
  };

  return (
    <div className="page">
      <Card title="Central de tarefas" subtitle="Execucao duravel com checkpoints, retentativas e verificacao" actions={
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">Todos os estados</option>
          {["queued", "planning", "running", "awaiting_approval", "paused", "completed", "partially_completed", "failed", "cancelled"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      }>
        <div className="create-task">
          <textarea rows={2} placeholder="Descreva o objetivo. Ex.: organize os arquivos de Downloads e mostre um resumo" value={objective} onChange={(e) => setObjective(e.target.value)} />
          <div className="row wrap gap-sm">
            <select value={autonomy} onChange={(e) => setAutonomy(Number(e.target.value))}>
              {AUTONOMY.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="demo">Demonstracao (sem acoes externas reais)</option>
              <option value="test">Teste (sem credenciais reais)</option>
              <option value="production">Producao (requer aprovacoes)</option>
            </select>
            <Button variant="primary" icon="play" onClick={create} disabled={busy || objective.trim().length < 3}>{busy ? "Criando" : "Executar"}</Button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Objetivo</th><th>Estado</th><th>Nivel</th><th>Modo</th><th>Criada</th><th /></tr></thead>
            <tbody>
              {tasks.data?.tasks?.map((task: any) => (
                <tr key={task.id} className="clickable" onClick={() => setSelected(task.id)}>
                  <td><strong>{task.objective}</strong><div className="muted small">{shortId(task.id)}</div></td>
                  <td><StatusBadge status={task.status} /></td>
                  <td>{task.autonomy_level}</td>
                  <td><Badge tone={task.mode === "production" ? "warn" : "neutral"}>{task.mode}</Badge></td>
                  <td className="muted small">{formatDate(task.created_at)}</td>
                  <td className="row gap-sm" onClick={(e) => e.stopPropagation()}>
                    <Button variant="ghost" icon="pause" title="Pausar" onClick={() => void act(task.id, "pause")} />
                    <Button variant="danger" icon="stop" title="Cancelar" onClick={() => void act(task.id, "cancel")} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!tasks.data?.tasks?.length && <Empty title="Nenhuma tarefa neste filtro" hint="Crie um objetivo acima ou use a conversa." />}
        </div>
      </Card>

      {selected && detail && (
        <Modal title={`Tarefa ${shortId(detail.id)}`} onClose={() => { setSelected(null); setDetail(null); }} wide>
          <div className="detail-grid">
            <div>
              <p>{detail.objective}</p>
              <div className="row wrap gap-sm">
                <StatusBadge status={detail.status} />
                <Badge tone="neutral">nivel {detail.autonomy_level}</Badge>
                <Badge tone="neutral">{detail.plan?.planner || "sem plano"}</Badge>
                <Badge tone="neutral">{detail.tool_calls} chamadas</Badge>
              </div>
              {detail.error && <div className="alert alert-bad">{detail.error}</div>}
              <div className="row gap-sm">
                <Button icon="pause" onClick={() => void act(detail.id, "pause")}>Pausar</Button>
                <Button icon="play" onClick={() => void act(detail.id, "resume")}>Retomar</Button>
                <Button variant="danger" icon="stop" onClick={() => void act(detail.id, "cancel")}>Cancelar</Button>
              </div>
            </div>
            <div className="metric-grid compact">
              <div className="metric"><span className="metric-label">Etapas</span><strong>{detail.verification?.steps_completed ?? 0}/{detail.verification?.steps_total ?? 0}</strong></div>
              <div className="metric"><span className="metric-label">Progresso</span><strong>{Math.round((detail.progress || 0) * 100)}%</strong></div>
              <div className="metric"><span className="metric-label">Tokens</span><strong>{detail.tokens || 0}</strong></div>
              <div className="metric"><span className="metric-label">Custo</span><strong>US$ {(detail.cost_usd || 0).toFixed(4)}</strong></div>
            </div>
          </div>
          <h4>Etapas</h4>
          <div className="step-list">
            {detail.steps?.map((step: any) => (
              <div key={step.id} className="step-row">
                <span className="step-index">{step.idx + 1}</span>
                <div className="step-main">
                  <strong>{step.title}</strong>
                  <span className="muted small">{step.tool} · tentativas {step.attempts}</span>
                  {step.error && <span className="small danger-text">{step.error}</span>}
                </div>
                <div className="step-side">
                  <StatusBadge status={step.status} />
                  {step.verification?.status && <Badge tone={step.verification.status === "passed" ? "good" : "warn"}>{step.verification.status}</Badge>}
                </div>
              </div>
            ))}
          </div>
          {detail.plan?.risks?.length > 0 && <><h4>Riscos e limites</h4><ul>{detail.plan.risks.map((risk: string, i: number) => <li key={i}>{risk}</li>)}</ul></>}
          {detail.plan?.assumptions?.length > 0 && <><h4>Premissas</h4><ul>{detail.plan.assumptions.map((item: string, i: number) => <li key={i}>{item}</li>)}</ul></>}
          <h4>Eventos</h4>
          <div className="event-log">
            {detail.events?.slice(-25).map((event: any) => (
              <div key={event.id} className="event-row"><span className="muted small">{formatDate(event.ts)}</span><code>{event.kind}</code><span className="muted small">{JSON.stringify(event.payload).slice(0, 180)}</span></div>
            ))}
          </div>
        </Modal>
      )}
    </div>
  );
}

export function AgentsPage(_props: PageProps) {
  const agents = usePolling("/api/agents", 60000);
  return (
    <div className="page">
      <Card title="Equipe de agentes" subtitle="Papeis com ferramentas, limites e contratos de verificacao proprios">
        <div className="agent-grid">
          {agents.data?.agents?.map((agent: any) => (
            <article key={agent.id} className="agent-card">
              <header><Badge tone="info">{agent.id}</Badge><h3>{agent.name}</h3></header>
              <p>{agent.objective}</p>
              <div className="agent-section"><span className="label">Skills permitidas</span><div className="row wrap gap-xs">{agent.allowed_skills.map((s: string) => <code key={s} className="chip">{s}</code>)}</div></div>
              <div className="agent-section"><span className="label">Contrato de verificacao</span><ul>{agent.verification_contract.map((item: string, i: number) => <li key={i}>{item}</li>)}</ul></div>
              {agent.forbidden?.length > 0 && <div className="agent-section"><span className="label danger-text">Proibido</span><ul>{agent.forbidden.map((item: string, i: number) => <li key={i}>{item}</li>)}</ul></div>}
            </article>
          ))}
        </div>
      </Card>
    </div>
  );
}

export function SecurityPage({ status, refreshStatus }: PageProps) {
  const { notify } = useToast();
  const perms = usePolling("/api/permissions", 8000);
  const approvals = usePolling("/api/approvals", 4000);
  const [pin, setPin] = useState("");
  const [currentPin, setCurrentPin] = useState("");
  const [approvalModal, setApprovalModal] = useState<any>(null);
  const [pinForApproval, setPinForApproval] = useState("");
  const [roots, setRoots] = useState<Record<string, string>>({});

  const updatePermission = async (scope: string, granted: boolean, config?: any) => {
    const existing = perms.data?.permissions?.find((p: any) => p.scope === scope);
    const result = await api("/api/permissions", { method: "POST", body: { scope, granted, config: config ?? existing?.config ?? {} } });
    notify(result.ok ? `Permissao ${scope} ${granted ? "concedida" : "revogada"}.` : result.error || "Falha", result.ok ? "good" : "bad");
    await perms.refresh();
    refreshStatus();
  };

  const saveRoots = async (scope: string) => {
    const value = roots[scope];
    if (value === undefined) return;
    const list = value.split(",").map((s) => s.trim()).filter(Boolean);
    await updatePermission(scope, true, { roots: list });
  };

  const stopAll = async () => {
    const result = await api("/api/security/stop", { method: "POST", body: { reason: "Painel de seguranca" } });
    notify(result.ok ? `Parada ativada. ${result.data?.affected_tasks?.length || 0} tarefas suspensas.` : result.error || "Falha", result.ok ? "warn" : "bad");
    refreshStatus();
  };

  const resolve = async (approve: boolean) => {
    if (!approvalModal) return;
    const result = await api(`/api/approvals/${approvalModal.id}/resolve`, {
      method: "POST", body: { approve, pin: pinForApproval, note: approve ? "aprovado no painel" : "rejeitado no painel" },
    });
    if (!result.ok) { notify(result.error || "Falha", "bad"); return; }
    notify(approve ? "Aprovacao concedida." : "Aprovacao rejeitada.", approve ? "good" : "warn");
    setApprovalModal(null);
    setPinForApproval("");
    await approvals.refresh();
    refreshStatus();
  };

  return (
    <div className="page">
      <div className="security-banner">
        <div>
          <span className="eyebrow">CONTROLE DO USUARIO</span>
          <h2>{status?.kill_switch ? "Parada de emergencia ativa" : "Sistema operacional com permissoes explicitas"}</h2>
          <p className="muted">Alto risco exige aprovacao com PIN local. Nenhuma acao externa ocorre sem permissao concedida.</p>
        </div>
        {status?.kill_switch ? (
          <Button variant="primary" icon="play" onClick={async () => { await api("/api/security/release", { method: "POST" }); refreshStatus(); notify("Parada desativada.", "good"); }}>Reativar</Button>
        ) : (
          <Button variant="danger" icon="stop" onClick={stopAll}>PARAR JARVIS</Button>
        )}
      </div>

      <div className="two-col">
        <Card title="PIN local" subtitle="Necessario para acoes sensiveis; uma confirmacao por voz nao basta">
          {status?.pin_configured ? <Badge tone="good">PIN configurado</Badge> : <Badge tone="warn">PIN nao configurado</Badge>}
          <div className="grid-2">
            {status?.pin_configured && <Field label="PIN atual"><input type="password" inputMode="numeric" value={currentPin} onChange={(e) => setCurrentPin(e.target.value)} /></Field>}
            <Field label={status?.pin_configured ? "Novo PIN (6+ digitos)" : "Definir PIN (6+ digitos)"}><input type="password" inputMode="numeric" value={pin} onChange={(e) => setPin(e.target.value)} /></Field>
          </div>
          <Button variant="primary" icon="lock" onClick={async () => {
            const result = await api("/api/security/pin", { method: "POST", body: { pin, current_pin: currentPin || null } });
            notify(result.ok ? "PIN salvo." : result.error || "Falha ao salvar PIN", result.ok ? "good" : "bad");
            if (result.ok) { setPin(""); setCurrentPin(""); refreshStatus(); }
          }}>Salvar PIN</Button>
          <p className="muted small">O PIN e armazenado como hash PBKDF2 local. Nao e enviado a nenhum servico.</p>
        </Card>
        <Card title="Aprovacoes" subtitle="Acoes bloqueadas aguardando decisao humana">
          {approvals.data?.approvals?.length ? approvals.data.approvals.slice(0, 8).map((approval: any) => (
            <div key={approval.id} className="approval-row">
              <div><strong>{approval.action}</strong><div className="muted small">{approval.payload?.label || approval.payload?.summary || ""} · risco {approval.risk}</div></div>
              <StatusBadge status={approval.status} />
              {approval.status === "pending" && <Button variant="primary" icon="lock" onClick={() => setApprovalModal(approval)}>Revisar</Button>}
            </div>
          )) : <Empty title="Nenhuma aprovacao" hint="Acoes rotineiras nao interrompem voce." />}
        </Card>
      </div>

      <Card title="Permissoes" subtitle="Concessoes revogaveis por escopo, com raizes de arquivos">
        <div className="permission-grid">
          {perms.data?.permissions?.map((permission: any) => (
            <div key={permission.scope} className={`permission-row risk-${permission.risk}`}>
              <div>
                <strong>{permission.label}</strong>
                <div className="muted small"><code>{permission.scope}</code> · risco {permission.risk}</div>
              </div>
              <Toggle checked={permission.granted} onChange={(value) => void updatePermission(permission.scope, value)} />
              {permission.scope.startsWith("fs.") && (
                <div className="roots-editor">
                  <input placeholder="Pastas autorizadas separadas por virgula" value={roots[permission.scope] ?? (permission.config?.roots || []).join(", ")} onChange={(e) => setRoots({ ...roots, [permission.scope]: e.target.value })} />
                  <Button variant="ghost" icon="folder" onClick={() => void saveRoots(permission.scope)}>Aplicar</Button>
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>

      {approvalModal && (
        <Modal title="Aprovar acao sensivel" onClose={() => setApprovalModal(null)}>
          <p><strong>{approvalModal.action}</strong></p>
          <p className="muted">{approvalModal.payload?.label || approvalModal.payload?.summary}</p>
          <pre className="codeblock">{JSON.stringify(approvalModal.payload?.data || approvalModal.payload, null, 2).slice(0, 2000)}</pre>
          {!status?.pin_configured && <div className="alert alert-bad">Configure um PIN antes de aprovar. Sem PIN, a aprovacao e bloqueada.</div>}
          <Field label="PIN local"><input type="password" inputMode="numeric" value={pinForApproval} onChange={(e) => setPinForApproval(e.target.value)} /></Field>
          <div className="row gap-sm">
            <Button variant="primary" icon="check" onClick={() => void resolve(true)}>Aprovar</Button>
            <Button variant="danger" icon="x" onClick={() => void resolve(false)}>Rejeitar</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
