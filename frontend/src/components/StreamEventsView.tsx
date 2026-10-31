import { useState } from 'react';
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Terminal,
  Wrench,
} from 'lucide-react';
import type { StreamEvent } from '../types';
import { prettyJson, truncate } from '../lib/utils';

interface StreamEventsViewProps {
  events: StreamEvent[];
  /** 是否默认收起工具调用详情 */
  compact?: boolean;
}

/**
 * 统一渲染一次 AI 任务的 SSE 结构化事件：
 * 思考过程（reasoning）、工具调用（tool_call）、工具返回（tool_result）、
 * 以及最终文本（message）。
 */
export function StreamEventsView({ events }: StreamEventsViewProps) {
  const [showReasoning, setShowReasoning] = useState(false);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  const reasoning = events
    .filter((e) => e.type === 'reasoning')
    .map((e) => e.content ?? '')
    .join('');
  const messages = events
    .filter((e) => e.type === 'message')
    .map((e) => e.content ?? '')
    .join('');
  const toolEvents = events.filter((e) => e.type === 'tool_call' || e.type === 'tool_result');

  return (
    <div className="space-y-2">
      {reasoning && (
        <div className="rounded-md bg-stone-100 px-3 py-2">
          <button
            type="button"
            onClick={() => setShowReasoning((v) => !v)}
            className="flex items-center gap-1.5 text-xs font-medium text-stone-500 hover:text-stone-700"
          >
            {showReasoning ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
            <Brain className="size-3.5" />
            思考过程
          </button>
          {showReasoning && (
            <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-stone-600">
              {reasoning}
            </p>
          )}
        </div>
      )}

      {toolEvents.map((ev, i) => {
        const open = !!expanded[i];
        if (ev.type === 'tool_call') {
          return (
            <div
              key={`${ev.tool_call_id ?? i}-call`}
              className="rounded-md border border-stone-200 bg-white px-3 py-2"
            >
              <button
                type="button"
                onClick={() => setExpanded((p) => ({ ...p, [i]: !p[i] }))}
                className="flex w-full items-center gap-1.5 text-xs font-medium text-stone-700"
              >
                {open ? (
                  <ChevronDown className="size-3.5 shrink-0" />
                ) : (
                  <ChevronRight className="size-3.5 shrink-0" />
                )}
                <Wrench className="size-3.5 shrink-0 text-brand-500" />
                调用工具 {ev.name || 'unknown'}
              </button>
              {open && ev.args !== undefined && (
                <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-stone-50 p-2 text-xs text-stone-500">
                  {truncate(prettyJson(ev.args), 600)}
                </pre>
              )}
            </div>
          );
        }
        return (
          <div
            key={`${ev.tool_call_id ?? i}-result`}
            className="rounded-md border border-stone-200 bg-stone-50/70 px-3 py-2"
          >
            <div className="flex items-center gap-1.5 text-xs font-medium text-stone-500">
              <Terminal className="size-3.5" />
              工具返回 {ev.name || 'unknown'}
            </div>
            <p className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-stone-500">
              {truncate(ev.content ?? '', 600)}
            </p>
          </div>
        );
      })}

      {messages && (
        <div className="flex items-start gap-1.5">
          <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-stone-700">{messages}</p>
        </div>
      )}
    </div>
  );
}
