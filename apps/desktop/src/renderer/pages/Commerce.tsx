import { useMemo, useState } from "react";
import { api, formatDate, formatMoney, usePolling } from "../lib/api";
import { Badge, Button, Card, CopyButton, Empty, Field, Metric, Modal, Spinner, StatusBadge, Toggle, useToast } from "../components/ui";
import type { PageProps } from "./types";

function ApprovalBox({ action, summary, data, onApproved, label }: {
  action: string; summary: string; data?: any; onApproved: (approvalId: string) => void; label: string;
}) {
  const { notify } = useToast();
  const [approval, setApproval] = useState<any>(null);
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="approval-box">
      {!approval ? (
        <Button icon="lock" onClick={async () => {
          setBusy(true);
          const result = await api("/api/approvals/request", { method: "POST", body: { action, summary, data } });
          setBusy(false);
          if (!result.ok) { notify(result.error || "Falha ao solicitar aprovacao", "bad"); return; }
          setApproval(result.data);
          notify("Aprovacao solicitada. Revise e informe o PIN local.", "info");
        }} disabled={busy}>{label}</Button>
      ) : approval.status === "pending" ? (
        <div className="approval-inline">
          <Badge tone="warn">pendente · {approval.risk}</Badge>
          <input type="password" inputMode="numeric" placeholder="PIN local" value={pin} onChange={(e) => setPin(e.target.value)} />
          <Button variant="primary" icon="check" onClick={async () => {
            const result = await api(`/api/approvals/${approval.id}/resolve`, { method: "POST", body: { approve: true, pin, note: "aprovado na interface" } });
            if (!result.ok) { notify(result.error || "Falha", "bad"); return; }
            setApproval(result.data);
            notify("Aprovado. Executando acao.", "good");
            onApproved(approval.id);
          }}>Aprovar</Button>
          <Button variant="danger" icon="x" onClick={async () => {
            await api(`/api/approvals/${approval.id}/resolve`, { method: "POST", body: { approve: false, pin } });
            setApproval(null);
            notify("Aprovacao rejeitada.", "warn");
          }}>Rejeitar</Button>
        </div>
      ) : <Badge tone={approval.status === "approved" ? "good" : "warn"}>aprovacao {approval.status}</Badge>}
    </div>
  );
}

export function BusinessPage(_props: PageProps) {
  const { notify } = useToast();
  const businesses = usePolling("/api/businesses", 15000);
  const [name, setName] = useState("");
  const [niche, setNiche] = useState("");
  const [target, setTarget] = useState(10000);
  const [price, setPrice] = useState(97);
  const [conversion, setConversion] = useState(2);
  const [adCost, setAdCost] = useState(0.8);
  const [feePercent, setFeePercent] = useState(4.99);
  const [refund, setRefund] = useState(5);
  const [recurring, setRecurring] = useState(false);
  const [churn, setChurn] = useState(5);
  const [plan, setPlan] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const calculate = async () => {
    setBusy(true);
    const result = await api("/api/businesses/plan", { method: "POST", body: {
      target_monthly: target, price, conversion_rate: conversion / 100, monthly_investment: 0,
    } });
    setBusy(false);
    if (!result.ok) { notify(result.error || "Falha no calculo", "bad"); return; }
    setPlan(result.data);
  };

  return (
    <div className="page">
      <Card title="Business Intelligence" subtitle="Calculos com premissas explicitas; nenhum dado de mercado inventado">
        <div className="two-col inner">
          <div>
            <h4>Novo negocio</h4>
            <div className="grid-2">
              <Field label="Nome"><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Estudio Digital" /></Field>
              <Field label="Nicho"><input value={niche} onChange={(e) => setNiche(e.target.value)} placeholder="Ex.: educacao financeira" /></Field>
            </div>
            <Button variant="primary" icon="plus" onClick={async () => {
              if (!name.trim()) return;
              const result = await api("/api/businesses", { method: "POST", body: { name, niche } });
              notify(result.ok ? "Negocio cadastrado." : result.error || "Falha", result.ok ? "good" : "bad");
              if (result.ok) { setName(""); await businesses.refresh(); }
            }}>Cadastrar negocio</Button>
            <div className="business-list">
              {businesses.data?.businesses?.map((item: any) => (
                <div key={item.id} className="business-row"><div><strong>{item.name}</strong><span className="muted small">{item.niche || "sem nicho"} · {item.id}</span></div><Badge tone="neutral">negocio</Badge></div>
              ))}
            </div>
          </div>
          <div>
            <h4>Meta e economia unitaria</h4>
            <div className="grid-2">
              <Field label="Meta mensal (R$)"><input type="number" value={target} onChange={(e) => setTarget(Number(e.target.value))} /></Field>
              <Field label="Preco (R$)"><input type="number" value={price} onChange={(e) => setPrice(Number(e.target.value))} /></Field>
              <Field label="Conversao (%)"><input type="number" step="0.1" value={conversion} onChange={(e) => setConversion(Number(e.target.value))} /></Field>
              <Field label="CPC (R$)"><input type="number" step="0.1" value={adCost} onChange={(e) => setAdCost(Number(e.target.value))} /></Field>
              <Field label="Taxa pagamento (%)"><input type="number" step="0.1" value={feePercent} onChange={(e) => setFeePercent(Number(e.target.value))} /></Field>
              <Field label="Reembolso (%)"><input type="number" step="0.5" value={refund} onChange={(e) => setRefund(Number(e.target.value))} /></Field>
            </div>
            <Toggle checked={recurring} onChange={setRecurring} label="Receita recorrente" />
            {recurring && <Field label="Churn mensal (%)"><input type="number" value={churn} onChange={(e) => setChurn(Number(e.target.value))} /></Field>}
            <Button variant="primary" icon="spark" onClick={calculate} disabled={busy}>Calcular cenarios</Button>
            <Button icon="chat" onClick={async () => {
              await api("/api/chat", { method: "POST", body: { message: `Jarvis, analise um negocio digital com preco de R$ ${price} e meta de R$ ${target} por mes`, conversation_id: "business" } });
              notify("Tarefa de analise criada. Veja a Central de Tarefas.", "info");
            }}>Analisar com agentes</Button>
          </div>
        </div>
        {plan && (
          <div className="plan-output">
            <h4>Cenarios calculados</h4>
            <div className="metric-grid">
              {Object.entries(plan.scenarios || {}).map(([key, value]: any) => (
                <Metric key={key} label={key} value={Math.round(value.customers_needed)} hint={`${Math.round(value.traffic_needed)} visitas @ ${(value.conversion_rate * 100).toFixed(2)}%`} />
              ))}
            </div>
            <div className="row wrap gap-sm">
              <Badge tone="info">Clientes necessarios: {plan.unit_economics?.math?.customers_needed_for_target}</Badge>
              <Badge tone="info">Receita liquida/venda: {formatMoney(plan.unit_economics?.math?.net_revenue_per_sale)}</Badge>
              <Badge tone="warn">CAC: {plan.unit_economics?.math?.cac_estimate ?? "nao informado"}</Badge>
            </div>
            <div className="alert alert-warn">
              {plan.unit_economics?.disclaimer} Nao ha garantia de receita. As premissas acima precisam ser validadas com dados reais.
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

export function SalesPage(_props: PageProps) {
  const { notify } = useToast();
  const [days, setDays] = useState(7);
  const report = usePolling(`/api/sales/report?days=${days}`, 8000, [days]);
  const dashboard = usePolling("/api/sales/dashboard", 15000);
  const [syncing, setSyncing] = useState(false);
  const data = report.data;

  return (
    <div className="page">
      <div className="row wrap gap-sm page-head">
        <div><h2>Vendas e faturamento</h2><p className="muted">Somente pedidos pagos entram como receita confirmada.</p></div>
        <div className="row gap-sm">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>7 dias</option><option value={30}>30 dias</option><option value={90}>90 dias</option>
          </select>
          <Button icon="refresh" onClick={async () => {
            setSyncing(true);
            const result = await api("/api/integrations/cakto/sync", { method: "POST" });
            setSyncing(false);
            notify(result.ok ? `Sincronizacao: ${result.data.fetched} pedidos recebidos.` : result.error || "Falha ao sincronizar", result.ok ? "good" : "bad");
            await report.refresh();
            await dashboard.refresh();
          }} disabled={syncing}>{syncing ? "Sincronizando" : "Sincronizar Cakto"}</Button>
        </div>
      </div>
      {data?.is_empty ? (
        <Card><Empty title="Nenhum pedido sincronizado" hint="Isso nao significa zero vendas: conecte a Cakto e sincronize para consultar dados reais." /></Card>
      ) : (
        <>
          <div className="metric-grid">
            <Metric label="Receita bruta confirmada" value={formatMoney(data?.gross_revenue_brl)} hint={`${data?.paid_orders || 0} pedidos pagos`} tone="good" />
            <Metric label="Receita liquida estimada" value={formatMoney(data?.net_revenue_estimate_brl)} hint={`taxas ${formatMoney(data?.fees_brl)}`} />
            <Metric label="Pendentes" value={data?.pending_orders ?? 0} hint="Pix/boleto gerado nao e venda" tone="warn" />
            <Metric label="Reembolsos" value={formatMoney(data?.refunds_brl)} hint={`${data?.refunded_orders || 0} pedidos`} tone="bad" />
          </div>
          <div className="two-col">
            <Card title="Receita por dia" subtitle={data?.data_source}>
              <div className="bars">
                {Object.entries(data?.daily_revenue || {}).map(([day, value]: any) => {
                  const max = Math.max(...Object.values(data?.daily_revenue || { a: 1 }) as number[]);
                  return <div key={day} className="bar-row"><span className="muted small">{day.slice(5)}</span><div className="bar"><span style={{ width: `${Math.max(4, (value / max) * 100)}%` }} /></div><strong>{formatMoney(value)}</strong></div>;
                })}
                {!Object.keys(data?.daily_revenue || {}).length && <Empty title="Sem vendas pagas no periodo" />}
              </div>
            </Card>
            <Card title="Qualidade do dado" subtitle="Transparencia obrigatoria">
              <ul className="notes">{data?.notes?.filter(Boolean).map((note: string, i: number) => <li key={i}>{note}</li>)}</ul>
              <div className="row wrap gap-sm">
                <Badge tone="info">Ticket medio {formatMoney(data?.average_ticket_brl)}</Badge>
                <Badge tone="neutral">Pedidos no periodo: {data?.orders_considered}</Badge>
              </div>
              <p className="muted small">Relatorios de campanha sao separados e nao atribuem vendas sem rastreamento confiavel.</p>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

export function CaktoPage({ status }: PageProps) {
  const { notify } = useToast();
  const cakto = usePolling("/api/integrations/cakto/status", 15000);
  const products = usePolling("/api/cakto/products", 20000);
  const local = usePolling("/api/products", 20000);
  const events = usePolling("/api/cakto/webhook-events", 15000);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [environment, setEnvironment] = useState("production");
  const [form, setForm] = useState({ name: "", description: "", price: 97, type: "unique", sales_page: "" });
  const [creating, setCreating] = useState(false);
  const [result, setResult] = useState<any>(null);

  const connect = async () => {
    const response = await api("/api/integrations/cakto/connect", { method: "POST", body: { client_id: clientId, client_secret: clientSecret, environment } });
    notify(response.ok ? "Credenciais armazenadas no cofre local." : response.error || "Falha", response.ok ? "good" : "bad");
    if (response.ok) { setClientSecret(""); await cakto.refresh(); }
  };

  const createProduct = async (approvalId: string) => {
    setCreating(true);
    const response = await api("/api/cakto/products", { method: "POST", body: { ...form, confirm_create: true, approval_id: approvalId } });
    setCreating(false);
    if (!response.ok) { notify(response.error || "Falha ao criar produto", "bad"); return; }
    setResult(response.data);
    notify("Produto criado e checkout resolvido.", "good");
    await products.refresh();
    await local.refresh();
  };

  const stored = cakto.data?.connected;
  return (
    <div className="page">
      <div className="row wrap gap-sm page-head">
        <div><h2>Cakto</h2><p className="muted">Integracao baseada apenas em endpoints documentados (out/2026).</p></div>
        <div className="row gap-sm">
          <Button icon="refresh" onClick={async () => { const r = await api("/api/integrations/cakto/status?verify=true"); await cakto.refresh(); notify(r.data?.status === "authenticated" ? "Autenticado na API Cakto." : r.data?.last_error || "Nao autenticado", r.data?.status === "authenticated" ? "good" : "warn"); }}>Verificar conexao</Button>
          {stored && <Button variant="danger" icon="x" onClick={async () => { await api("/api/integrations/cakto", { method: "DELETE" }); await cakto.refresh(); notify("Credenciais removidas.", "warn"); }}>Desconectar</Button>}
        </div>
      </div>

      <div className="two-col">
        <Card title="Credenciais" subtitle="client_id e client_secret da sua chave Cakto">
          <div className="row wrap gap-sm">
            <Badge tone={cakto.data?.status === "authenticated" ? "good" : stored ? "warn" : "bad"}>{cakto.data?.status || "nao conectado"}</Badge>
            <Badge tone="neutral">cofre: {status?.vault_backend}</Badge>
            {cakto.data?.environment && <Badge tone="neutral">{cakto.data.environment}</Badge>}
          </div>
          <Field label="client_id"><input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="Sua chave publica" /></Field>
          <Field label="client_secret" hint="Armazenado no cofre local; nunca aparece em logs ou no Git."><input type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} /></Field>
          <Field label="Ambiente"><select value={environment} onChange={(e) => setEnvironment(e.target.value)}><option value="production">Producao</option><option value="demo">Demonstracao</option></select></Field>
          <Button variant="primary" icon="lock" onClick={connect} disabled={!clientId || !clientSecret}>Salvar e conectar</Button>
          <p className="muted small">Escopos necessarios: read/write products, read offers, read orders. Crie a chave em app.cakto.com.br/dashboard/cakto-api.</p>
        </Card>
        <Card title="Produtos retornados" subtitle={products.data?.mode === "demonstracao" ? "DADOS FICTICIOS DE DEMONSTRACAO" : "Consulta real a API quando autenticado"}>
          {products.data?.warning && <div className="alert alert-warn">{products.data.warning}</div>}
          <div className="list">
            {products.data?.results?.map((product: any) => (
              <div key={product.id} className="list-row">
                <div><strong>{product.name}</strong><span className="muted small">{product.id} · {product.type || "-"}</span></div>
                <Badge tone={product._demo ? "warn" : "good"}>{product._demo ? "demo" : formatMoney(Number(product.price || 0))}</Badge>
              </div>
            ))}
            {!products.data?.results?.length && <Empty title="Nenhum produto retornado" />}
          </div>
        </Card>
      </div>

      <Card title="Criar produto + checkout" subtitle="POST /public_api/products/ · a criacao ja gera oferta, checkout e link">
        <div className="grid-2">
          <Field label="Nome"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Preco (R$)"><input type="number" value={form.price} onChange={(e) => setForm({ ...form, price: Number(e.target.value) })} /></Field>
          <Field label="Tipo"><select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}><option value="unique">Venda unica</option><option value="subscription">Assinatura</option></select></Field>
          <Field label="Pagina de vendas (URL real)"><input value={form.sales_page} onChange={(e) => setForm({ ...form, sales_page: e.target.value })} placeholder="https://..." /></Field>
        </div>
        <Field label="Descricao"><textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <div className="alert alert-warn">A criacao real exige credenciais, permissao cakto.write e aprovacao com PIN. Revise preco, descricao e URL: o produto sera criado na sua conta.</div>
        <ApprovalBox action="cakto.create_product" summary={`Criar produto ${form.name} por R$ ${form.price}`} data={form} label="Solicitar aprovacao" onApproved={(id) => void createProduct(id)} />
        {creating && <Spinner label="Criando produto e resolvendo checkout" />}
        {result && (
          <div className="result-box">
            <StatusBadge status={result.verification?.status} />
            <p>Produto: <code>{result.product?.provider_id}</code> · oferta: <code>{result.product?.offer_id}</code> · checkout: <code>{result.product?.checkout_id}</code></p>
            {result.product?.checkout_url && <div className="row gap-sm"><a className="link" href={result.product.checkout_url} target="_blank" rel="noreferrer">{result.product.checkout_url}</a><CopyButton value={result.product.checkout_url} /></div>}
            {result.deduplicated && <Badge tone="warn">requisicao idempotente: produto ja existia</Badge>}
          </div>
        )}
      </Card>

      <div className="two-col">
        <Card title="Produtos locais" subtitle="Registro do que foi criado por este aplicativo">
          {local.data?.products?.length ? local.data.products.map((p: any) => (
            <div key={p.id} className="list-row"><div><strong>{p.name}</strong><span className="muted small">{p.provider_id}</span></div><StatusBadge status={p.status} /></div>
          )) : <Empty title="Nenhum produto local" />}
        </Card>
        <Card title="Webhooks recebidos" subtitle="Recebidos via relay autenticado ou endpoint local">
          {events.data?.events?.length ? events.data.events.slice(0, 8).map((e: any) => (
            <div key={e.id} className="event-row"><code>{e.event}</code><span className="muted small">{formatDate(e.received_at)}</span><StatusBadge status={e.status} /></div>
          )) : <Empty title="Nenhum evento" hint="Configure o relay HTTPS para receber eventos com o PC desligado." />}
          <p className="muted small">Endpoint local: POST /api/webhooks/cakto (Bearer do runtime). Relay: services/webhook-relay com HMAC e idempotencia.</p>
        </Card>
      </div>
    </div>
  );
}

export function AdsPage(_props: PageProps) {
  const { notify } = useToast();
  const config = usePolling("/api/ads/config", 15000);
  const campaigns = usePolling("/api/ads/campaigns", 8000);
  const [metricsInput, setMetricsInput] = useState('[{"campaign_id":"cmp_1","spend":100,"impressions":10000,"clicks":200,"conversions":5,"revenue":500}]');
  const [analysis, setAnalysis] = useState<any>(null);
  const [form, setForm] = useState({ objective: "Vender meu produto digital", daily_budget: 0, monthly_limit: 0, audience: "" });
  const [plan, setPlan] = useState<any>(null);
  const [meta, setMeta] = useState({ ad_account_id: "", page_id: "", access_token: "" });
  const [budget, setBudget] = useState({ daily_limit: 0, monthly_limit: 0, ad_account: "", expires_in_days: 7 });

  const saveBudget = async (approvalId: string) => {
    const result = await api("/api/ads/budget", { method: "POST", body: { ...budget, approval_id: approvalId } });
    notify(result.ok ? "Limites de orcamento atualizados." : result.error || "Falha", result.ok ? "good" : "bad");
    await config.refresh();
  };

  const prepare = async () => {
    const result = await api("/api/ads/prepare", { method: "POST", body: { ...form, provider: "meta" } });
    if (!result.ok) { notify(result.error || "Falha", "bad"); return; }
    setPlan(result.data);
    await campaigns.refresh();
  };

  return (
    <div className="page">
      <div className="alert alert-warn">
        Investimento automatico padrao: <strong>R$ 0,00</strong>. Preparar campanhas nao gasta dinheiro. Publicacao exige conta Meta autorizada, revisao de app e aprovacao com PIN.
        {" "}Status dos conectores: <strong>VALIDACAO REAL PENDENTE</strong>.
      </div>
      <div className="metric-grid">
        <Metric label="Orcamento diario autorizado" value={formatMoney(config.data?.budget_policy?.daily_limit_brl)} hint={config.data?.budget_policy?.enabled ? "ativo" : "desativado"} tone={config.data?.budget_policy?.enabled ? "good" : "warn"} />
        <Metric label="Limite mensal" value={formatMoney(config.data?.budget_policy?.monthly_limit_brl)} hint={config.data?.budget_policy?.expires_at ? `expira ${formatDate(config.data.budget_policy.expires_at)}` : "sem autorizacao"} />
        <Metric label="Conta Meta" value={config.data?.meta?.ad_account_id ? "configurada" : "nao conectada"} hint={config.data?.meta?.has_token ? "token no cofre" : "token ausente"} />
        <Metric label="Gasto local registrado" value={formatMoney(campaigns.data?.campaigns?.reduce((sum: number, c: any) => sum + (c.spent_cents || 0), 0) / 100)} hint="somente campanhas lancadas" />
      </div>

      <div className="two-col">
        <Card title="Conectar Meta Ads" subtitle="Graph API v21.0, campanhas sempre criadas pausadas">
          <div className="grid-2">
            <Field label="Ad Account ID"><input value={meta.ad_account_id} onChange={(e) => setMeta({ ...meta, ad_account_id: e.target.value })} placeholder="act_..." /></Field>
            <Field label="Page ID"><input value={meta.page_id} onChange={(e) => setMeta({ ...meta, page_id: e.target.value })} /></Field>
          </div>
          <Field label="Access token" hint="Armazenado no cofre local. Requer permissoes de anuncios aprovadas pela Meta."><input type="password" value={meta.access_token} onChange={(e) => setMeta({ ...meta, access_token: e.target.value })} /></Field>
          <Button variant="primary" icon="lock" onClick={async () => {
            const result = await api("/api/ads/config", { method: "POST", body: meta });
            notify(result.ok ? "Configuracao Meta salva." : result.error || "Falha", result.ok ? "good" : "bad");
            if (result.ok) { setMeta({ ...meta, access_token: "" }); await config.refresh(); }
          }}>Salvar conexao</Button>
          <p className="muted small">Google Ads e TikTok Ads exigem OAuth e aprovacao propria; os adaptadores informam indisponibilidade em vez de simular sucesso.</p>
        </Card>
        <Card title="Autorizar orcamento" subtitle="Requer aprovacao critica com PIN">
          <div className="grid-2">
            <Field label="Limite diario (R$)"><input type="number" value={budget.daily_limit} onChange={(e) => setBudget({ ...budget, daily_limit: Number(e.target.value) })} /></Field>
            <Field label="Limite mensal (R$)"><input type="number" value={budget.monthly_limit} onChange={(e) => setBudget({ ...budget, monthly_limit: Number(e.target.value) })} /></Field>
            <Field label="Conta autorizada"><input value={budget.ad_account} onChange={(e) => setBudget({ ...budget, ad_account: e.target.value })} /></Field>
            <Field label="Validade (dias)"><input type="number" value={budget.expires_in_days} onChange={(e) => setBudget({ ...budget, expires_in_days: Number(e.target.value) })} /></Field>
          </div>
          <ApprovalBox action="ads.budget_policy" summary={`Autorizar R$ ${budget.daily_limit}/dia e R$ ${budget.monthly_limit}/mes`} data={budget} label="Solicitar aprovacao de orcamento" onApproved={(id) => void saveBudget(id)} />
          <p className="muted small">Aumentos acima do limite exigem nova aprovacao. A autorizacao expira e pode ser revogada.</p>
        </Card>
      </div>

      <Card title="Preparar campanha" subtitle="Nenhum gasto nesta etapa">
        <div className="grid-3">
          <Field label="Objetivo"><input value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} /></Field>
          <Field label="Orcamento diario (R$)"><input type="number" value={form.daily_budget} onChange={(e) => setForm({ ...form, daily_budget: Number(e.target.value) })} /></Field>
          <Field label="Limite mensal (R$)"><input type="number" value={form.monthly_limit} onChange={(e) => setForm({ ...form, monthly_limit: Number(e.target.value) })} /></Field>
        </div>
        <Button variant="primary" icon="spark" onClick={prepare}>Gerar rascunho</Button>
        {plan && (
          <div className="result-box">
            <div className="row wrap gap-sm"><StatusBadge status={plan.plan?.status} /><Badge tone="good">gasto: R$ 0,00</Badge><Badge tone="neutral">campanha {plan.campaign_id}</Badge></div>
            {plan.plan?.budget?.guard_errors?.length > 0 && <div className="alert alert-warn">{plan.plan.budget.guard_errors.join(" ")}</div>}
            <h4>Estrutura</h4>
            <pre className="codeblock">{JSON.stringify(plan.plan?.structure, null, 2)}</pre>
            <h4>Variacoes de texto</h4>
            {plan.plan?.copy_drafts?.map((copy: any, i: number) => <div key={i} className="copy-row"><strong>{copy.headline}</strong><span>{copy.body}</span><Badge tone="info">{copy.cta}</Badge></div>)}
          </div>
        )}
      </Card>

      <div className="two-col">
        <Card title="Campanhas registradas" subtitle="Nada e publicado sem aprovacao">
          {campaigns.data?.campaigns?.length ? campaigns.data.campaigns.map((c: any) => (
            <div key={c.id} className="list-row"><div><strong>{c.name}</strong><span className="muted small">{c.provider} · {c.external_id || "sem id externo"}</span></div><StatusBadge status={c.status} /></div>
          )) : <Empty title="Nenhuma campanha" />}
        </Card>
        <Card title="Analise de metricas" subtitle="Cole metricas reais exportadas da plataforma">
          <textarea rows={5} value={metricsInput} onChange={(e) => setMetricsInput(e.target.value)} />
          <Button icon="spark" onClick={async () => {
            try {
              const parsed = JSON.parse(metricsInput);
              const result = await api("/api/ads/analyze", { method: "POST", body: { metrics: parsed, target_cpa: 30 } });
              if (!result.ok) throw new Error(result.error);
              setAnalysis(result.data);
            } catch (error) { notify(`Metricas invalidas: ${String(error)}`, "bad"); }
          }}>Analisar</Button>
          {analysis && (
            <table>
              <thead><tr><th>Campanha</th><th>CTR</th><th>CPC</th><th>CPA</th><th>ROAS</th><th>Amostra</th></tr></thead>
              <tbody>{analysis.campaigns.map((row: any) => <tr key={row.campaign_id}><td>{row.campaign_id}</td><td>{row.ctr ?? "-"}</td><td>{formatMoney(row.cpc_brl)}</td><td>{formatMoney(row.cpa_brl)}</td><td>{row.roas ?? "-"}</td><td><Badge tone={row.confidence === "insuficiente" ? "warn" : "good"}>{row.confidence}</Badge></td></tr>)}</tbody>
            </table>
          )}
          <p className="muted small">{analysis?.caveats?.join(" ")}</p>
        </Card>
      </div>
    </div>
  );
}

export function CrmPage(_props: PageProps) {
  const { notify } = useToast();
  const leads = usePolling("/api/leads", 8000);
  const [form, setForm] = useState({ name: "", email: "", phone: "", source: "manual", consent: false, notes: "" });
  const funnel = useMemo(() => leads.data?.leads ? leads.data.leads.reduce((acc: Record<string, number>, lead: any) => ({ ...acc, [lead.stage]: (acc[lead.stage] || 0) + 1 }), {}) : {}, [leads.data]);
  return (
    <div className="page">
      <div className="metric-grid">
        {["new", "qualified", "proposal", "won", "lost"].map((stage) => <Metric key={stage} label={stage} value={funnel[stage] || 0} hint="leads reais no CRM" />)}
      </div>
      <div className="two-col">
        <Card title="Novo contato" subtitle="Somente contatos com consentimento podem receber contato">
          <div className="grid-2">
            <Field label="Nome"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Email"><input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="Telefone"><input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
            <Field label="Origem"><input value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} /></Field>
          </div>
          <Field label="Observacoes"><textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
          <Toggle checked={form.consent} onChange={(value) => setForm({ ...form, consent: value })} label="Contato autorizou comunicacao" />
          <Button variant="primary" icon="plus" onClick={async () => {
            if (!form.name.trim()) return;
            const result = await api("/api/leads", { method: "POST", body: form });
            notify(result.ok ? "Lead cadastrado." : result.error || "Falha", result.ok ? "good" : "bad");
            if (result.ok) { setForm({ ...form, name: "", email: "", phone: "", notes: "" }); await leads.refresh(); }
          }}>Cadastrar</Button>
        </Card>
        <Card title="Leads" subtitle={`${leads.data?.eligible_for_contact?.length || 0} elegiveis para contato`}>
          {leads.data?.leads?.length ? leads.data.leads.map((lead: any) => (
            <div key={lead.id} className="list-row">
              <div><strong>{lead.name}</strong><span className="muted small">{lead.email || "sem email"} · {lead.source || "-"}</span></div>
              <div className="row gap-sm">
                <select value={lead.stage} onChange={async (e) => { await api(`/api/leads/${lead.id}`, { method: "PUT", body: { stage: e.target.value } }); await leads.refresh(); }}>
                  {["new", "qualified", "proposal", "won", "lost"].map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
                <Badge tone={lead.consent ? "good" : "warn"}>{lead.consent ? "consentido" : "sem consentimento"}</Badge>
              </div>
            </div>
          )) : <Empty title="Nenhum lead" />}
          <p className="muted small">Nao ha envio automatico de mensagens. Disparos em massa, contas falsas e depoimentos ficticios sao bloqueados por politica.</p>
        </Card>
      </div>
    </div>
  );
}
