"use client";

import { useEffect, useState } from "react";
import { PageHeader, Panel, useLocale } from "web-shared";
import { KNOWLEDGE_EN } from "@/lib/reasoning-copy";
import { api } from "@/lib/api";

type Task = { task_id: string; target: string | null; target_days: number | null; phase: string; revision: number; release_id: string; updated_at: string; unknowns: string[] };
type Node = { id: string; kind: string; label: string; action_ref?: string; state_ref?: string };
type Edge = { id: string; source: string; target: string; condition: string; guidance: string; pitfalls: string; predicate_status?: string };
type Guidance = { immediate_goal: string; recommended_action_refs: string[]; unknowns: string[]; cautions: string[]; stop_or_wait_reason: string | null };
type Event = { event_id: string; event_type: string; timestamp: string; action_ref?: string; status: string; error_code?: string; duration_ms: number; evidence_refs: string[]; input_tokens?: number; output_tokens?: number; role?: string; failure_kind?: string; failure_reason?: string; timeout_s?: number; guidance_output?: Guidance };
type Detail = {
  task: Task; variant: string;
  view: { listing: { kind: string } | null; observations: Record<string, { value: unknown; value_status: string; observation_id: string; source_tool: string; observed_at: string; source_revision: number | null }>; pending_present: boolean | null };
  plan: { stock: number; sales: number; target_days: number; target_stock: number; quantity: number; status: string; note: string } | null;
  guidance: { guidance: Guidance; subgraph: { nodes: Node[]; edges: Edge[]; omitted_count: number } } | null;
  graph: { nodes: Node[]; edges: Edge[]; version: string }; events: Event[];
};

const EN: Record<string, string> = { START: "Start", READ_ALERTS: "Read alerts", READ_LISTING: "Read listing", READ_PENDING: "Read pending changes", ASSESS: "Assess evidence", CALCULATE: "Calculate", STAGE: "Stage change", WAIT_APPROVAL: "Wait for approval", VERIFY: "Verify effect", RECONCILE: "Reconcile", NEED_INPUT: "Needs input", REVIEW_EXISTING: "Review existing", NO_ACTION: "No action", SUCCESS: "Verified", DECLINED: "Discarded" };
const ZH: Record<string, string> = { START: "任务开始", READ_ALERTS: "读取告警", READ_LISTING: "读取商品", READ_PENDING: "核对待处理", ASSESS: "评估证据", CALCULATE: "计算方案", STAGE: "暂存变更", WAIT_APPROVAL: "等待批准", VERIFY: "验证效果", RECONCILE: "核对未知结果", NEED_INPUT: "需要补充信息", REVIEW_EXISTING: "复核已有变更", NO_ACTION: "无需操作", SUCCESS: "已验证", DECLINED: "已丢弃", known: "已知", unknown: "未知", stale: "已过期", invalid: "无效", conflicting: "冲突", consumed: "已使用", valid: "有效", superseded: "已替代" };

export function GuidancePanel({ detail, locale }: { detail: Detail; locale: string }) {
  const zh = locale === "zh-CN";
  const attempts = detail.events.filter((event) => event.event_type === "guidance_generated" || event.event_type === "guidance_failed");
  const successes = attempts.filter((event) => event.event_type === "guidance_generated");
  const failures = attempts.filter((event) => event.event_type === "guidance_failed");
  const lastSuccess = successes.at(-1);
  const lastAttempt = attempts.at(-1);
  const guidance = detail.guidance?.guidance ?? lastSuccess?.guidance_output;
  const historical = !detail.guidance || ["SUCCESS", "DECLINED", "NO_ACTION"].includes(detail.task.phase);
  const enabled = ["P", "T", "E"].includes(detail.variant);
  const reasons: Record<string, string> = zh ? {
    timeout: "指导请求超过等待上限", json: "模型返回的内容不是有效 JSON", schema: "模型返回的字段类型或长度不符合要求",
    action_ref: "建议引用了不可用的动作", edge_ref: "建议引用了不存在的流程分支", evidence_ref: "建议引用了不存在的证据",
    text_length: "指导文字超过长度限制", instructions: "指导含有改变权限的指令", approval_claim: "指导声称已经批准或执行，但缺少依据",
    context_budget: "指导上下文超过大小限制", provider: "模型服务请求失败",
  } : {};
  const failed = lastAttempt?.event_type === "guidance_failed" ? lastAttempt : null;
  const reason = failed && (zh
    ? reasons[failed.failure_kind ?? ""] ?? (failed.error_code === "GUIDANCE_TIMEOUT" ? reasons.timeout : "指导未通过校验；旧记录没有保存具体原因")
    : failed.failure_reason ?? failed.error_code);
  return (
    <Panel><div className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">{zh ? "PG 指导" : "PG guidance"}</h2><span className="text-xs text-(--ink-soft)">{enabled ? (zh ? "已开启" : "Enabled") : (zh ? "未开启" : "Disabled")}</span></div>
      <p className="mt-2 text-sm text-(--ink-soft)">{zh ? `最近记录：成功 ${successes.length} 次 · 降级 ${failures.length} 次` : `Recent records: ${successes.length} successful · ${failures.length} degraded`}</p>
      {failed ? <p className="mt-3 rounded-lg bg-(--warn-soft) p-3 text-sm" role="status">{zh ? "最近一轮未使用指导：" : "Latest round continued without guidance: "}{reason}{failed.timeout_s && failed.failure_kind === "timeout" ? ` (${failed.timeout_s}s)` : ""}</p> : null}
      {guidance ? <>
        <p className="mt-3 text-xs text-(--ink-soft)">{historical ? (zh ? "最近一次成功指导（历史，仅供回看）" : "Last successful guidance (history only)") : (zh ? "最近一轮指导" : "Latest guidance")}{lastSuccess ? ` · ${new Date(lastSuccess.timestamp).toLocaleTimeString(locale)}` : ""}</p>
        <p className="mt-2 text-sm">{guidance.immediate_goal}</p>
        <p className="mt-2 break-words font-mono text-xs">{guidance.recommended_action_refs.join(" → ")}</p>
        {[...guidance.unknowns, ...guidance.cautions, guidance.stop_or_wait_reason].filter(Boolean).map((line, i) => <p key={i} className="mt-2 text-sm text-(--ink-soft)">{line}</p>)}
      </> : <p className="mt-3 text-sm text-(--ink-soft)">{enabled ? (zh ? "暂未记录到成功指导，执行检查仍然生效。" : "No successful guidance recorded yet. Execution checks remain active.") : (zh ? "当前模式不生成 PG 指导，执行检查仍然生效。" : "This mode does not generate PG guidance. Execution checks remain active.")}</p>}
      {attempts.length > 0 ? <a href="#reasoning-execution-history" className="mt-3 inline-block text-sm underline">{zh ? "查看执行记录中的指导详情" : "View guidance details in execution history"}</a> : null}
    </div></Panel>
  );
}

function ProcedureMap({ detail, selected, onSelect, chinese }: { detail: Detail; selected: string | null; onSelect: (id: string) => void; chinese: boolean }) {
  const labels = chinese ? ZH : EN;
  const positions = Object.fromEntries(detail.graph.nodes.map((node, index) => [node.id, { x: (index % 3) * 190 + 10, y: Math.floor(index / 3) * 94 + 12 }]));
  const local = new Set(detail.guidance?.subgraph.edges.map((edge) => edge.id) ?? []);
  return (
    <div className="overflow-x-auto rounded-lg border border-(--line) bg-(--ground)">
      <svg viewBox={`0 0 580 ${Math.ceil(detail.graph.nodes.length / 3) * 94 + 12}`} role="img" aria-label={chinese ? "过程图，使用下方节点按钮查看定义" : "Procedure graph; use the node buttons below to inspect definitions"} className="min-w-[400px] w-full">
        <defs><marker id="reasoning-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" /></marker></defs>
        {detail.graph.edges.map((edge) => {
          const from = positions[edge.source], to = positions[edge.target];
          if (!from || !to) return null;
          return <path key={edge.id} d={`M${from.x + 85},${from.y + 50} C${from.x + 85},${from.y + 75} ${to.x + 85},${to.y - 20} ${to.x + 85},${to.y}`} fill="none" stroke="currentColor" strokeWidth={local.has(edge.id) ? 2 : 1} opacity={local.has(edge.id) ? 0.7 : 0.15} markerEnd="url(#reasoning-arrow)" />;
        })}
        {detail.graph.nodes.map((node) => {
          const point = positions[node.id], active = node.id === detail.task.phase;
          return <g key={node.id} onClick={() => onSelect(node.id)} className="cursor-pointer">
            <rect x={point.x} y={point.y} width="170" height="50" rx="9" fill={active ? "var(--ink)" : "var(--card)"} stroke={node.id === selected ? "var(--brand)" : "var(--line)"} strokeWidth={node.id === selected ? 3 : 1} />
            <text x={point.x + 85} y={point.y + 22} textAnchor="middle" fontSize="12" fill={active ? "var(--card)" : "var(--ink)"}>{labels[node.id] ?? node.label}</text>
            <text x={point.x + 85} y={point.y + 38} textAnchor="middle" fontSize="9" fill={active ? "var(--card)" : "var(--ink-soft)"}>{node.id}</text>
          </g>;
        })}
      </svg>
      <div className="flex flex-wrap gap-1 border-t border-(--line) p-2" aria-label={chinese ? "选择节点" : "Select a node"}>
        {detail.graph.nodes.map((node) => <button key={node.id} type="button" aria-pressed={node.id === selected} onClick={() => onSelect(node.id)} className="rounded border border-(--line) px-2 py-1 text-xs focus-visible:outline-2">{labels[node.id] ?? node.id}</button>)}
      </div>
    </div>
  );
}

export default function ReasoningView({ refreshKey, sessionId }: { refreshKey: number; sessionId: string }) {
  const { locale } = useLocale();
  const zh = locale === "zh-CN", labels = zh ? ZH : EN;
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false, timer: ReturnType<typeof setTimeout>;
    async function read() {
      if (document.visibilityState !== "visible") { timer = setTimeout(read, 2000); return; }
      const list = await api.get<{ tasks: Task[] }>("/reasoning/tasks");
      const id = taskId ?? list?.tasks.at(-1)?.task_id;
      const result = id ? await api.get<Detail>(`/reasoning/tasks/${encodeURIComponent(id)}`) : null;
      if (cancelled) return;
      setFailed(!list || Boolean(id && !result));
      if (list) setTasks(list.tasks);
      if (result) setDetail(result);
      else if (list && !id) setDetail(null);
      timer = setTimeout(read, 2000);
    }
    void read();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [sessionId, taskId, refreshKey, locale, reload]);
  const node = detail?.graph.nodes.find((item) => item.id === (selected ?? detail.task.phase));
  const edges = detail?.graph.edges.filter((edge) => edge.source === node?.id) ?? [];
  const text = (en: string, cn: string) => zh ? cn : en;
  const knowledgeText = (value: string) => zh ? value : KNOWLEDGE_EN[value] ?? value;
  return (
    <div className="space-y-5 p-4 lg:p-6">
      <PageHeader title={text("Reasoning inspector", "推理调试")} subtitle={text("Read-only evidence, guidance, and execution history.", "只读查看证据、过程建议和执行记录。")} />
      {failed ? <div role="alert" className="rounded-lg bg-(--warn-soft) p-3 text-sm">{text("Could not refresh. The last successful snapshot is shown.", "刷新失败，当前显示上次成功读取的快照。")} <button type="button" onClick={() => setReload((n) => n + 1)} className="underline">{text("Retry", "重试")}</button></div> : null}
      {tasks === null && !failed ? <p role="status">{text("Loading tasks…", "正在读取任务…")}</p> : null}
      {tasks?.length === 0 ? <Panel><div className="p-6 text-(--ink-soft)">{text("No tasks yet. Ask the assistant to check one listing and specify the coverage days.", "暂无任务。请在助手中指定一个商品和覆盖天数，开始库存排查。")}</div></Panel> : null}
      {tasks && tasks.length > 0 ? <label className="block text-sm">{text("Task", "任务")} <select value={taskId ?? tasks.at(-1)?.task_id ?? ""} onChange={(event) => { setTaskId(event.target.value); setSelected(null); }} className="ml-2 max-w-full rounded border border-(--line) bg-(--card) p-2">{tasks.map((task) => <option key={task.task_id} value={task.task_id}>{task.target ?? text("Unselected target", "未选择目标")} · {labels[task.phase] ?? task.phase} · {task.task_id.slice(-8)}</option>)}</select></label> : null}
      {detail ? <>
        <div className="grid gap-3 sm:grid-cols-3">
          {[ [text("Current state", "当前状态"), labels[detail.task.phase] ?? detail.task.phase], [text("Coverage", "覆盖天数"), detail.task.target_days === null ? text("Needs clarification", "需要补充") : `${detail.task.target_days} ${text("days", "天")}`], [text("Knowledge", "知识版本"), `${detail.variant} · PG ${detail.graph.version} · r${detail.task.revision}`] ].map(([label, value]) => <Panel key={label}><div className="p-4"><p className="text-xs text-(--ink-soft)">{label}</p><p className="mt-1 font-semibold">{value}</p></div></Panel>)}
        </div>
        <div className="grid gap-5 xl:grid-cols-2">
          <Panel><div className="space-y-3 p-4"><h2 className="font-semibold">{text("Procedure graph", "过程图")}</h2><ProcedureMap detail={detail} selected={node?.id ?? null} onSelect={setSelected} chinese={zh} /><p className="text-sm">{node?.action_ref ?? node?.state_ref}</p>{edges.map((edge) => <details key={edge.id} className="border-t border-(--line) py-2 text-sm"><summary className="cursor-pointer font-mono">{edge.id} → {labels[edge.target] ?? edge.target}</summary><p className="mt-2">{knowledgeText(edge.condition)}</p><p>{knowledgeText(edge.guidance)}</p><p className="text-(--ink-soft)">{knowledgeText(edge.pitfalls)}</p></details>)}</div></Panel>
          <div className="space-y-5">
            <Panel><div className="p-4"><h2 className="mb-3 font-semibold">{text("Evidence", "事实证据")}</h2><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="text-(--ink-soft)"><th className="py-2">{text("Field", "字段")}</th><th>{text("Value", "值")}</th><th>{text("Validity", "有效性")}</th></tr></thead><tbody>{Object.entries(detail.view.observations).map(([key, fact]) => <tr key={key} className="border-t border-(--line)"><td className="py-2 font-mono text-xs" title={`${fact.source_tool} · ${fact.observation_id}`}>{key}</td><td className="max-w-40 break-words">{fact.value === null ? "—" : typeof fact.value === "object" ? JSON.stringify(fact.value) : String(fact.value)}</td><td>{labels[fact.value_status] ?? fact.value_status}</td></tr>)}</tbody></table></div><p className="mt-3 text-sm">{text("Pending conflict: ", "待处理冲突：")}{detail.view.pending_present === null ? text("Unknown", "未知") : detail.view.pending_present ? text("Present", "存在") : text("None in complete snapshot", "完整快照中不存在")}</p></div></Panel>
            {detail.plan ? <Panel><div className="p-4"><h2 className="font-semibold">{text("Restock calculation", "补货计算")}</h2><p className="mt-2 font-mono">max(0, ceil({detail.plan.sales} × {detail.plan.target_days} / 30) − {detail.plan.stock}) = {detail.plan.quantity}</p><p className="mt-2 text-sm text-(--ink-soft)">{labels[detail.plan.status] ?? detail.plan.status} · {text("A plan is not approval.", "计算方案不代表批准。")}</p></div></Panel> : null}
            <GuidancePanel detail={detail} locale={locale} />
          </div>
        </div>
        <Panel><div id="reasoning-execution-history" className="p-4"><h2 className="mb-3 font-semibold">{text("Execution history", "执行记录")}</h2><ol className="divide-y divide-(--line)">{detail.events.filter((event) => event.event_type !== "request_composed").slice(-60).reverse().map((event) => <li key={event.event_id} className="py-2"><button type="button" aria-expanded={expanded === event.event_id} onClick={() => setExpanded(expanded === event.event_id ? null : event.event_id)} className="flex w-full flex-wrap gap-x-3 text-left text-xs"><time className="text-(--ink-soft)">{new Date(event.timestamp).toLocaleTimeString(locale)}</time><span className="font-mono">{event.event_type}</span><span className="font-mono">{event.action_ref}</span><span className="ml-auto">{event.error_code ?? event.status} · {event.duration_ms} ms</span></button>{expanded === event.event_id ? <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-(--ground) p-3 text-xs">{JSON.stringify(event, null, 2)}</pre> : null}</li>)}</ol></div></Panel>
      </> : null}
    </div>
  );
}
