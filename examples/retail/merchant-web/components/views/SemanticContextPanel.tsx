"use client";

import { Panel } from "web-shared";

type Definition = { id: string; description?: string; label?: string };
type Dependency = { kind: string; id: string; required: boolean; path: string[]; seed_sources: string[] };
export type SemanticSnapshot = {
  turn_id: string;
  is_current?: boolean;
  phase?: string;
  task_revision?: number;
  content_hash: string;
  public: Record<"actions" | "states" | "entities" | "relations" | "properties" | "checks", Definition[]>;
  diagnostics: {
    builder_version: string;
    ontology_hash: string;
    semantic_schema_hash: string;
    seed_action_refs: string[];
    seed_state_refs: string[];
    required_definition_count: number;
    optional_definition_count: number;
    included_bytes: number;
    dependency_paths: Dependency[];
    omitted_optional_refs: { kind: string; id: string; reason: string }[];
    status: string;
  };
};

type Props = {
  locale: string;
  snapshot?: SemanticSnapshot | null;
  mode?: { configured: string; effective: string };
  source?: string;
  events: { event_type: string; error_code?: string }[];
};

export default function SemanticContextPanel({ locale, snapshot, mode, source, events }: Props) {
  const zh = locale === "zh-CN";
  const latestContextEvent = events.filter((event) =>
    event.event_type === "semantic_context_built" || event.event_type === "semantic_context_failed"
  ).at(-1);
  const failed = latestContextEvent?.event_type === "semantic_context_failed" ? latestContextEvent : null;
  const kinds = ["actions", "states", "entities", "relations", "properties", "checks"] as const;
  const labels = zh
    ? { actions: "动作", states: "状态", entities: "对象类型", relations: "关系", properties: "属性", checks: "检查说明" }
    : { actions: "Actions", states: "States", entities: "Entity types", relations: "Relations", properties: "Properties", checks: "Check descriptions" };
  return (
    <Panel><div className="min-w-0 space-y-3 p-4" data-testid="semantic-context-panel">
      <h2 className="font-semibold">{zh ? "本体语义上下文" : "Ontology semantic context"}</h2>
      <p className="text-sm text-(--ink-soft)">
        {zh ? "配置 / 生效模式：" : "Configured / effective mode: "}
        {mode?.configured ?? "legacy"} / {mode?.effective ?? "legacy"}
        {source ? ` · ${source}` : ""}
      </p>
      <p className="text-xs text-(--ink-soft)">{zh ? "只读定义与依赖解释；不是业务事实或审批凭证。" : "Read-only definitions and dependencies, not business facts or approval."}</p>
      {failed ? <p className="text-sm text-(--danger)" role="status" data-testid="semantic-context-failure">
        {zh ? "最近一次语义构造未完成：" : "The latest semantic construction failed: "}
        {failed.error_code ?? "SEMANTIC_CONTEXT_FAILED"}
        {snapshot ? (zh ? "；下方仅保留历史定义。" : "; only historical definitions are retained below.") : ""}
      </p> : null}
      {!snapshot ? <p className="text-sm" role="status">
        {mode?.effective === "closure"
          ? (zh ? "本轮没有可用的语义上下文。" : "No semantic context is available for this round.")
          : (zh ? "当前使用 legacy 路径，不展开完整定义依赖。" : "The legacy path does not expand complete definition dependencies.")}
      </p> : <>
        <p role="status" data-testid="semantic-snapshot-state" className="text-sm font-medium">
          {snapshot.is_current
            ? (zh ? "当前轮上下文（仅定义）" : "Current-round context (definitions only)")
            : (zh ? "历史上下文（非当前轮）" : "Historical context (not the current round)")}
          {snapshot.phase ? ` · ${snapshot.phase}` : ""}
        </p>
        <p className="text-sm">{zh ? "必需 / 可选定义：" : "Required / optional definitions: "}
          {snapshot.diagnostics.required_definition_count} / {snapshot.diagnostics.optional_definition_count}
          {` · ${snapshot.diagnostics.included_bytes} UTF-8 bytes`}
        </p>
        <p className="break-all font-mono text-xs" title={snapshot.content_hash}>{zh ? "内容摘要：" : "Content hash: "}{snapshot.content_hash}</p>
        <details className="text-sm"><summary className="cursor-pointer">{zh ? "动作与状态种子" : "Action and state seeds"}</summary>
          <p className="mt-2 break-all font-mono text-xs">{snapshot.diagnostics.seed_action_refs.join(", ") || "—"}</p>
          <p className="break-all font-mono text-xs">{snapshot.diagnostics.seed_state_refs.join(", ") || "—"}</p>
        </details>
        {kinds.map((kind) => <details key={kind} className="border-t border-(--line) pt-2 text-sm">
          <summary className="cursor-pointer">{labels[kind]} ({snapshot.public[kind].length})</summary>
          <p className="mt-2 text-xs text-(--ink-soft)">{zh ? "以下说明按知识文件原文显示。" : "Descriptions are shown in the knowledge file's source language."}</p>
          {snapshot.public[kind].map((item) => <div key={item.id} className="mt-2">
            <p className="break-all font-mono text-xs">{item.id}</p>
            <p className="text-sm text-(--ink-soft)">{item.description ?? item.label ?? "—"}</p>
          </div>)}
        </details>)}
        <details className="text-sm"><summary className="cursor-pointer">{zh ? "为什么包含这些定义？" : "Why are these definitions included?"}</summary>
          {snapshot.diagnostics.dependency_paths.map((item) => <div key={`${item.kind}:${item.id}`} className="mt-2 border-t border-(--line) pt-2">
            <p className="break-all font-mono text-xs">{item.path.join(" → ")}</p>
            <p className="text-xs text-(--ink-soft)">{item.required ? (zh ? "必需" : "Required") : (zh ? "可选" : "Optional")} · {item.seed_sources.join(", ")}</p>
          </div>)}
        </details>
        {snapshot.diagnostics.omitted_optional_refs.length ? <details className="text-sm"><summary className="cursor-pointer">{zh ? "预算裁剪" : "Budget omissions"}</summary>
          {snapshot.diagnostics.omitted_optional_refs.map((item) => <p key={`${item.kind}:${item.id}`} className="mt-2 break-all font-mono text-xs">{item.kind}:{item.id} · {item.reason}</p>)}
        </details> : null}
      </>}
    </div></Panel>
  );
}
