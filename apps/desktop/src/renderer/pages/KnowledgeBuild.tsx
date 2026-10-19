import { useEffect, useState } from "react";
import { api, formatDate, formatMoney, shortId, usePolling } from "../lib/api";
import { Badge, Button, Card, Empty, Field, Modal, Spinner, StatusBadge, useToast } from "../components/ui";
import type { PageProps } from "./types";

export function ResearchPage(_props: PageProps) {
  const { notify } = useToast();
  const config = usePolling("/api/research/config", 15000);
  const tasks = usePolling("/api/tasks?limit=40", 4000);
  const [provider, setProvider] = useState("none");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (config.data) {
      setProvider(config.data.provider || "none");
      setBaseUrl(config.data.base_url || "");
    }
  }, [config.data]);

  const researchTasks = (tasks.data?.tasks || []).filter((task: any) => task.plan?.intent === "research");

  const openDetail = async (taskId: string) => {
    const result = await api(`/api/tasks/${taskId}`);
    if (result.ok) setSelected(result.data);
  };

  return (
    <div className="page">
      <div className="two-col">
        <Card title="Pesquisa global" subtitle="Fontes publicas, links e deteccao de prompt injection">
          <Field label="Pergunta de pesquisa"><textarea rows={3} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ex.: oportunidades de negocios digitais para pequenas empresas brasileiras" /></Field>
          <div className="row gap-sm">
            <Button variant="primary" icon="search" disabled={busy || query.trim().length < 5} onClick={async () => {
              setBusy(true);
              const result = await api("/api/chat", { method: "POST", body: { message: `Jarvis, pesquise: ${query}`, conversation_id: "research" } });
              setBusy(false);
              if (!result.ok) { notify(result.error || "Falha", "bad"); return; }
              notify("Tarefa de pesquisa criada. Fontes serao registradas com URL.", "good");
              await tasks.refresh();
            }}>{busy ? "Criando" : "Pesquisar"}</Button>
            <Button icon="folder" onClick={() => notify("Os relatorios sao salvos em workspace/reports quando a pesquisa conclui.", "info")}>Onde ficam</Button>
          </div>
          <p className="muted small">Nao inventamos dados de mercado. Sem provedor configurado, a pesquisa falha com instrucao clara em vez de simular resultados.</p>
        </Card>
        <Card title="Provedor de busca" subtitle="Necessario para pesquisa aberta">
          <Field label="Provedor"><select value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="none">Nenhum (apenas URLs informadas)</option>
            <option value="searxng">SearXNG (auto-hospedado)</option>
            <option value="brave">Brave Search API</option>
            <option value="serper">Serper (Google)</option>
          </select></Field>
          {provider === "searxng" && <Field label="URL base do SearXNG"><input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://searx.exemplo.com" /></Field>}
          {["brave", "serper"].includes(provider) && <Field label="API key" hint="Guardada no cofre local."><input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></Field>}
          <Button variant="primary" icon="check" onClick={async () => {
            const result = await api("/api/research/config", { method: "POST", body: { provider, base_url: baseUrl, api_key: apiKey || undefined } });
            notify(result.ok ? "Configuracao de pesquisa salva." : result.error || "Falha", result.ok ? "good" : "bad");
            if (result.ok) { setApiKey(""); await config.refresh(); }
          }}>Salvar</Button>
          <div className="row wrap gap-sm">
            <Badge tone={config.data?.has_key ? "good" : "neutral"}>{config.data?.has_key ? "credencial no cofre" : "sem credencial"}</Badge>
            <Badge tone={config.data?.provider === "none" ? "warn" : "good"}>{config.data?.provider}</Badge>
          </div>
        </Card>
      </div>
      <Card title="Pesquisas recentes" subtitle="Clique para ver fontes, riscos e resultados">
        {researchTasks.length ? researchTasks.map((task: any) => (
          <button key={task.id} className="task-row" onClick={() => void openDetail(task.id)}>
            <div className="task-row-main"><strong>{task.objective}</strong><span className="muted small">{formatDate(task.created_at)}</span></div>
            <StatusBadge status={task.status} />
          </button>
        )) : <Empty title="Nenhuma pesquisa executada" hint="A pesquisa exige provedor configurado ou URLs explicitas." />}
      </Card>
      {selected && (
        <Modal title="Resultado da pesquisa" onClose={() => setSelected(null)} wide>
          <StatusBadge status={selected.status} />
          <pre className="codeblock report">{JSON.stringify(selected.steps?.map((s: any) => s.output), null, 2).slice(0, 20000)}</pre>
        </Modal>
      )}
    </div>
  );
}

export function DevelopmentPage(_props: PageProps) {
  const { notify } = useToast();
  const projects = usePolling("/api/projects", 8000);
  const [form, setForm] = useState({ kind: "web-app", name: "", objective: "", run_tests: true });
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const build = async () => {
    if (!form.name.trim() || form.objective.trim().length < 5) return;
    setBusy(true);
    setResult(null);
    const response = await api("/api/development/build", { method: "POST", body: form });
    setBusy(false);
    if (!response.ok) { notify(response.error || "Falha no build", "bad"); return; }
    setResult(response.data);
    notify(response.data.status === "validated" ? "Projeto gerado e testes aprovados." : "Projeto gerado; veja o status dos testes.", "good");
    await projects.refresh();
  };

  return (
    <div className="page">
      <Card title="Development Studio" subtitle="Projetos reais no workspace, testes executados com resultado registrado">
        <div className="grid-2">
          <Field label="Tipo de projeto"><select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            <option value="web-app">Aplicacao web (FastAPI + SQLite)</option>
            <option value="inventory-system">Sistema de estoque, vendas e caixa (Python/Tkinter)</option>
          </select></Field>
          <Field label="Nome"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Ex.: Cadastro de Produtos" /></Field>
        </div>
        <Field label="Objetivo e requisitos"><textarea rows={3} value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} placeholder="Descreva o que o software deve fazer" /></Field>
        <div className="row gap-sm">
          <label className="toggle"><input type="checkbox" checked={form.run_tests} onChange={(e) => setForm({ ...form, run_tests: e.target.checked })} /><span className="track"><span className="thumb" /></span><span>Executar testes automaticamente</span></label>
          <Button variant="primary" icon="terminal" onClick={build} disabled={busy}>{busy ? "Gerando e testando..." : "Construir projeto"}</Button>
          <Button icon="chat" onClick={async () => { await api("/api/chat", { method: "POST", body: { message: `Jarvis, crie um software: ${form.objective}`, conversation_id: "development" } }); notify("Tarefa de desenvolvimento criada.", "info"); }}>Executar como tarefa</Button>
        </div>
        {busy && <Spinner label="Escrevendo arquivos e executando pytest (pode levar alguns segundos)" />}
        {result && (
          <div className="result-box">
            <div className="row wrap gap-sm"><StatusBadge status={result.status} /><Badge tone="neutral">{result.files?.length} arquivos</Badge><Badge tone="neutral">sintaxe: {result.syntax_check?.status}</Badge></div>
            <p className="muted small">Caminho: <code>{result.path}</code></p>
            {result.tests && <pre className="codeblock">{result.tests.stdout?.slice(-2500) || result.tests.stderr?.slice(-2500)}</pre>}
            <ul className="notes">{result.limitations?.map((item: string, i: number) => <li key={i}>{item}</li>)}</ul>
            <div className="row wrap gap-xs">{result.files?.map((file: string) => <code key={file} className="chip">{file}</code>)}</div>
          </div>
        )}
      </Card>
      <Card title="Projetos e artefatos" subtitle="Histórico persistido com hash dos arquivos">
        {projects.data?.projects?.length ? projects.data.projects.map((project: any) => (
          <div key={project.id} className="project-row">
            <div><strong>{project.name}</strong><span className="muted small">{project.kind} · {project.path}</span></div>
            <div className="row gap-sm"><StatusBadge status={project.status} /><Badge tone="neutral">{project.metadata?.files?.length || 0} arquivos</Badge></div>
          </div>
        )) : <Empty title="Nenhum projeto gerado" />}
      </Card>
    </div>
  );
}

export function GameStudioPage(_props: PageProps) {
  const { notify } = useToast();
  const projects = usePolling("/api/projects", 10000);
  const [name, setName] = useState("Moto Racer");
  const [objective, setObjective] = useState("Prototipo 3D de corrida de motos em terceira pessoa com checkpoints e cronometro");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="page">
      <Card title="Game Studio · Godot" subtitle="Projeto Godot 4 valido com cena, script e GDD; exportacao exige Godot instalado">
        <div className="grid-2">
          <Field label="Nome do jogo"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Conceito"><input value={objective} onChange={(e) => setObjective(e.target.value)} /></Field>
        </div>
        <Button variant="primary" icon="game" onClick={async () => {
          setBusy(true);
          const response = await api("/api/gamestudio/build", { method: "POST", body: { kind: "godot-2d-racer", name, objective, run_tests: false } });
          setBusy(false);
          if (!response.ok) { notify(response.error || "Falha", "bad"); return; }
          setResult(response.data);
          notify("Projeto Godot gerado. Validacao do motor: " + response.data.godot_validation?.status, "info");
          await projects.refresh();
        }} disabled={busy}>{busy ? "Gerando projeto" : "Gerar prototipo"}</Button>
        {busy && <Spinner label="Criando cenas, scripts e GDD" />}
        {result && (
          <div className="result-box">
            <div className="row wrap gap-sm"><StatusBadge status={result.status} /><Badge tone="warn">build nao gerado</Badge><Badge tone="neutral">{result.files?.length} arquivos</Badge></div>
            <p className="muted small">Caminho: <code>{result.path}</code> · GDD: <code>{result.gdd}</code></p>
            <ul className="notes">
              <li>Godot instalado: {String(result.godot_validation?.godot_installed)}</li>
              <li>{result.godot_validation?.reason}</li>
              {result.limitations?.map((item: string, i: number) => <li key={i}>{item}</li>)}
            </ul>
            <pre className="codeblock">Controles: W acelerar · S frear · A/D dirigir · R reiniciar{"\n"}Loop: pista circular, checkpoints sequenciais, cronometro e camera em terceira pessoa.</pre>
          </div>
        )}
      </Card>
      <Card title="Projetos de jogo" subtitle="Status real de validacao">
        {projects.data?.projects?.filter((p: any) => p.kind === "godot-2d-racer").map((project: any) => (
          <div key={project.id} className="project-row"><div><strong>{project.name}</strong><span className="muted small">{project.path}</span></div><StatusBadge status={project.status} /></div>
        )) || <Empty title="Nenhum projeto Godot" />}
      </Card>
    </div>
  );
}

export function ProjectsPage(_props: PageProps) {
  const projects = usePolling("/api/projects", 8000);
  return (
    <div className="page">
      <Card title="Projetos" subtitle="Workspaces isolados por projeto">
        {projects.data?.projects?.length ? projects.data.projects.map((project: any) => (
          <div key={project.id} className="project-row">
            <div><strong>{project.name}</strong><span className="muted small">{project.kind} · criado {formatDate(project.created_at)}</span><span className="muted small">{project.path}</span></div>
            <div className="row gap-sm"><StatusBadge status={project.status} /><Badge tone="neutral">{project.metadata?.tests?.exit_code === 0 ? "testes OK" : project.metadata?.tests ? "testes falharam" : "sem testes"}</Badge></div>
          </div>
        )) : <Empty title="Nenhum projeto" hint="Gere um projeto no Development Studio ou Game Studio." />}
      </Card>
      <Card title="Artefatos recentes" subtitle="Arquivos produzidos com SHA-256">
        <div className="table-wrap"><table><thead><tr><th>Arquivo</th><th>Tipo</th><th>Tamanho</th><th>SHA-256</th><th>Criado</th></tr></thead><tbody>
          {projects.data?.artifacts?.map((artifact: any) => (
            <tr key={artifact.id}><td>{artifact.name}</td><td>{artifact.kind}</td><td>{(artifact.size_bytes / 1024).toFixed(1)} KB</td><td><code className="small">{artifact.sha256?.slice(0, 16)}…</code></td><td className="muted small">{formatDate(artifact.created_at)}</td></tr>
          ))}
        </tbody></table></div>
      </Card>
    </div>
  );
}

export function MemoryPage(_props: PageProps) {
  const { notify } = useToast();
  const memories = usePolling("/api/memories", 8000);
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("preference");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[] | null>(null);
  return (
    <div className="page">
      <div className="two-col">
        <Card title="Adicionar memoria" subtitle="Consultavel, editavel e removivel por voce">
          <Field label="Tipo"><select value={kind} onChange={(e) => setKind(e.target.value)}>
            {["session", "project", "operational", "preference", "commercial", "technical"].map((k) => <option key={k} value={k}>{k}</option>)}
          </select></Field>
          <Field label="Conteudo"><textarea rows={4} value={content} onChange={(e) => setContent(e.target.value)} placeholder="Ex.: Prefiro respostas curtas e relatorios com fontes." /></Field>
          <Button variant="primary" icon="memory" onClick={async () => {
            const result = await api("/api/memories", { method: "POST", body: { content, kind } });
            notify(result.ok ? "Memoria registrada." : result.error || "Falha", result.ok ? "good" : "bad");
            if (result.ok) { setContent(""); await memories.refresh(); }
          }} disabled={content.trim().length < 2}>Salvar</Button>
          <Field label="Busca"><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Busca textual (FTS5)" /></Field>
          <Button icon="search" onClick={async () => {
            const result = await api(`/api/memories/search?q=${encodeURIComponent(query)}`);
            setResults(result.ok ? result.data.results : []);
          }}>Buscar</Button>
        </Card>
        <Card title="Memorias" subtitle="Sem treinamento de pesos; apenas contexto controlado">
          {(results ?? memories.data?.memories ?? []).map((memory: any) => (
            <div key={memory.id} className="memory-row">
              <div><Badge tone="neutral">{memory.kind}</Badge><p>{memory.content}</p><span className="muted small">{memory.source} · {formatDate(memory.updated_at)}</span></div>
              <Button variant="danger" icon="trash" onClick={async () => {
                await api(`/api/memories/${memory.id}`, { method: "DELETE" });
                setResults(null);
                await memories.refresh();
                notify("Memoria removida.", "warn");
              }} />
            </div>
          ))}
          {!(results ?? memories.data?.memories ?? []).length && <Empty title="Nenhuma memoria" />}
        </Card>
      </div>
    </div>
  );
}
