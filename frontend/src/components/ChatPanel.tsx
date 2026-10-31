import { useEffect, useRef, useState } from 'react';
import { Bot, Loader2, Send, Square, Terminal, User, Wrench } from 'lucide-react';
import type { Space, StreamEvent } from '../types';
import { useStreamTask } from '../hooks/useStreamTask';
import { truncate } from '../lib/utils';

interface ChatPanelProps {
  space: Space;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  reasoning?: string;
  tools?: StreamEvent[];
  status?: 'done' | 'error' | 'cancelled';
}

const reasoningOf = (events: StreamEvent[]) =>
  events
    .filter((e) => e.type === 'reasoning')
    .map((e) => e.content ?? '')
    .join('');

const toolsOf = (events: StreamEvent[]) =>
  events.filter((e) => e.type === 'tool_call' || e.type === 'tool_result');

const textOf = (events: StreamEvent[]) =>
  events
    .filter((e) => e.type === 'message')
    .map((e) => e.content ?? '')
    .join('');

function ToolTrace({ tools }: { tools: StreamEvent[] }) {
  if (!tools.length) return null;
  return (
    <details className="mt-2">
      <summary className="cursor-pointer list-none text-xs text-stone-400 transition-colors hover:text-stone-600">
        查看执行过程 · {Math.max(1, Math.floor(tools.length / 2))} 次工具调用
      </summary>
      <div className="mt-2 space-y-1.5 rounded-md bg-stone-50 p-2">
        {tools.map((ev, i) =>
          ev.type === 'tool_call' ? (
            <div key={i} className="flex items-center gap-1.5 text-xs text-stone-600">
              <Wrench className="size-3 shrink-0 text-brand-500" />
              <span className="font-medium">调用工具</span>
              <span className="truncate text-stone-500">{ev.name || 'unknown'}</span>
            </div>
          ) : (
            <div key={i} className="flex items-center gap-1.5 text-xs text-stone-500">
              <Terminal className="size-3 shrink-0 text-stone-400" />
              <span className="truncate">{ev.name || 'unknown'} 返回</span>
            </div>
          ),
        )}
      </div>
    </details>
  );
}

function AssistantBubble({ message }: { message: ChatMessage }) {
  return (
    <div className="flex gap-2.5">
      <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-100 text-brand-700">
        <Bot className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        {message.status === 'error' && (
          <p className="mb-1 text-xs font-medium text-red-600">生成失败</p>
        )}
        {message.status === 'cancelled' && (
          <p className="mb-1 text-xs font-medium text-stone-400">已取消</p>
        )}
        {message.reasoning && (
          <details className="mb-1.5">
            <summary className="cursor-pointer list-none text-xs text-stone-400 hover:text-stone-600">
              思考过程
            </summary>
            <p className="mt-1.5 whitespace-pre-wrap rounded-md bg-stone-100 p-2 text-xs leading-relaxed text-stone-600">
              {truncate(message.reasoning, 1000)}
            </p>
          </details>
        )}
        {message.tools && <ToolTrace tools={message.tools} />}
        <div className="mt-1.5 whitespace-pre-wrap rounded-xl rounded-tl-sm bg-white px-3.5 py-2.5 text-sm leading-relaxed text-stone-800 shadow-sm ring-1 ring-stone-100">
          {message.content}
        </div>
      </div>
    </div>
  );
}

export function ChatPanel({ space }: ChatPanelProps) {
  const threadId = `chat-${space.id}`;
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const committedRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { events, status, result, error, start, cancel } = useStreamTask(threadId, space.id);

  const send = () => {
    const text = input.trim();
    if (!text || status === 'running') return;
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', content: text }]);
    setInput('');
    committedRef.current = false;
    void start(text);
  };

  useEffect(() => {
    if (status !== 'running' && status !== 'idle') {
      if (committedRef.current) return;
      committedRef.current = true;
      const content = result ?? textOf(events);
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: content || error || '（无输出）',
          reasoning: reasoningOf(events),
          tools: toolsOf(events),
          status:
            status === 'finished' ? 'done' : status === 'error' ? 'error' : 'cancelled',
        },
      ]);
    }
  }, [status, events, result, error]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, events, status]);

  const liveReasoning = reasoningOf(events);
  const liveTools = toolsOf(events);
  const liveText = textOf(events);

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="border-b border-stone-100 px-6 py-4">
        <h2 className="text-sm font-semibold">AI 写作助手</h2>
        <p className="mt-0.5 text-xs text-stone-400">输入需求，AI 将基于小说空间为您提供帮助</p>
      </div>

      <div className="scrollbar-thin flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-4 px-4 py-4">
        {messages.length === 0 && status === 'idle' && (
          <div className="flex min-h-[50vh] flex-col items-center justify-center text-center">
            <Bot className="size-8 text-stone-300" />
            <p className="mt-2 text-sm text-stone-400">和 AI 聊聊你的小说吧</p>
            <p className="mt-1 text-xs text-stone-300">例如：主角在第五章遇到了谁？</p>
          </div>
        )}

        {messages.map((m) =>
          m.role === 'user' ? (
            <div key={m.id} className="flex justify-end gap-2.5">
              <div className="max-w-[85%] whitespace-pre-wrap rounded-xl rounded-tr-sm bg-brand-500 px-3.5 py-2.5 text-sm leading-relaxed text-white">
                {m.content}
              </div>
              <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-stone-200 text-stone-600">
                <User className="size-4" />
              </div>
            </div>
          ) : (
            <AssistantBubble key={m.id} message={m} />
          ),
        )}

        {status === 'running' && (
          <div className="flex gap-2.5">
            <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-100 text-brand-700">
              <Bot className="size-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="mb-1.5 flex items-center gap-1.5 text-xs text-stone-400">
                <Loader2 className="size-3.5 animate-spin" />
                正在生成...
              </div>
              {liveReasoning && (
                <details className="mb-1.5">
                  <summary className="cursor-pointer list-none text-xs text-stone-400">
                    思考过程
                  </summary>
                  <p className="mt-1.5 whitespace-pre-wrap rounded-md bg-stone-100 p-2 text-xs leading-relaxed text-stone-600">
                    {truncate(liveReasoning, 1000)}
                  </p>
                </details>
              )}
              {liveTools.length > 0 && <ToolTrace tools={liveTools} />}
              {liveText && (
                <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-stone-700">
                  {liveText}
                </p>
              )}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
        </div>
      </div>

      <div className="border-t border-stone-100 p-3">
        <div className="mx-auto flex w-full max-w-3xl items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={1}
            placeholder="输入需求..."
            aria-label="输入需求"
            className="max-h-32 min-h-[38px] flex-1 resize-none rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm outline-none transition-colors focus:border-brand-400 focus:ring-2 focus:ring-brand-500/20"
          />
          {status === 'running' ? (
            <button
              type="button"
              aria-label="停止生成"
              onClick={cancel}
              className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-red-200 text-red-500 transition-colors hover:bg-red-50"
            >
              <Square className="size-4" />
            </button>
          ) : (
            <button
              type="button"
              aria-label="发送"
              onClick={send}
              disabled={!input.trim()}
              className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-500 text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Send className="size-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
