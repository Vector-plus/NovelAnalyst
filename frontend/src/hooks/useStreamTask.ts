import { useCallback, useRef, useState } from 'react';
import type { StreamEvent, StreamTaskStatus } from '../types';
import { cancelRun } from '../api';

interface StreamRunBody {
  message: string;
  thread_id: string;
  session_id: string;
  novel_id?: string;
  multitask_strategy?: 'reject' | 'interrupt' | 'rollback';
}

/**
 * 管理一次 AI 任务的 SSE 流式执行：
 * - start：发起 /api/runs/stream，逐事件累积 events 与最终 result；
 * - cancel：调用后端 cancel 接口 + 前端 abort；
 * - pause/resume：前端侧暂停渲染（缓冲事件），后端继续执行。
 */
export function useStreamTask(threadId: string, novelId?: string, sessionId?: string) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<StreamTaskStatus>('idle');
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [tokens, setTokens] = useState(0);
  const [toolCalls, setToolCalls] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const pausedRef = useRef(false);
  const bufferRef = useRef<StreamEvent[]>([]);
  const threadRef = useRef(threadId);
  const novelRef = useRef(novelId);
  const sessionRef = useRef(sessionId);
  const runIdRef = useRef<string | null>(null);
  const statusRef = useRef<StreamTaskStatus>('idle');

  threadRef.current = threadId;
  novelRef.current = novelId;
  sessionRef.current = sessionId;

  const setStatusBoth = useCallback((s: StreamTaskStatus) => {
    statusRef.current = s;
    setStatus(s);
  }, []);

  const flushBuffer = useCallback(() => {
    if (bufferRef.current.length) {
      setEvents((prev) => [...prev, ...bufferRef.current]);
      bufferRef.current = [];
    }
  }, []);

  const pushEvent = useCallback((ev: StreamEvent) => {
    if (pausedRef.current) {
      bufferRef.current.push(ev);
    } else {
      setEvents((prev) => [...prev, ev]);
    }
  }, []);

  const start = useCallback(
    async (message: string, opts?: { multitask_strategy?: StreamRunBody['multitask_strategy'] }) => {
      setEvents([]);
      setResult(null);
      setError(null);
      setRunId(null);
      setTokens(0);
      setToolCalls(0);
      runIdRef.current = null;
      bufferRef.current = [];
      pausedRef.current = false;
      setPaused(false);
      setStatusBoth('running');

      const controller = new AbortController();
      abortRef.current = controller;

      const processLine = (line: string) => {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) return;
        const payload = trimmed.slice(5).trim();
        if (payload === '[DONE]') return;

        let parsed: { event: string; data: unknown };
        try {
          parsed = JSON.parse(payload);
        } catch {
          return;
        }

        if (parsed.event === 'run.created') {
          const d = parsed.data as { run_id: string; thread_id: string };
          runIdRef.current = d.run_id;
          setRunId(d.run_id);
        } else if (parsed.event === 'event') {
          pushEvent(parsed.data as StreamEvent);
        } else if (parsed.event === 'run.finished') {
          const d = parsed.data as {
            status: string;
            result: string | null;
            error: string | null;
            tokens?: number;
            tool_calls?: number;
          };
          setResult(d.result ?? null);
          setTokens(d.tokens ?? 0);
          setToolCalls(d.tool_calls ?? 0);
          if (d.error) setError(d.error);
          if (d.status === 'success') setStatusBoth('finished');
          else if (d.status === 'interrupted') setStatusBoth('cancelled');
          else setStatusBoth('error');
        }
      };

      try {
        const res = await fetch('/api/runs/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message,
            thread_id: threadRef.current,
            session_id: sessionRef.current ?? '',
            novel_id: novelRef.current,
            multitask_strategy: opts?.multitask_strategy ?? 'reject',
          } satisfies StreamRunBody),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          const text = await res.text().catch(() => '');
          throw new Error(`请求失败 (${res.status}): ${text}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf('\n\n')) >= 0) {
            const chunk = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            chunk.split('\n').forEach(processLine);
          }
        }
        if (buffer.trim()) buffer.split('\n').forEach(processLine);

        if (statusRef.current === 'running') {
          setStatusBoth('finished');
        }
      } catch (e) {
        const err = e as Error;
        if (err.name === 'AbortError') {
          if (statusRef.current === 'running') setStatusBoth('cancelled');
        } else {
          setError(err.message);
          setStatusBoth('error');
        }
      }
    },
    [pushEvent, setStatusBoth],
  );

  const cancel = useCallback(async () => {
    const rid = runIdRef.current;
    if (rid) {
      try {
        await cancelRun(threadRef.current, rid);
      } catch {
        // 后端 cancel 失败不阻塞前端停止
      }
    }
    abortRef.current?.abort();
    setStatusBoth('cancelled');
  }, [setStatusBoth]);

  const togglePause = useCallback(() => {
    if (pausedRef.current) {
      pausedRef.current = false;
      setPaused(false);
      flushBuffer();
    } else {
      pausedRef.current = true;
      setPaused(true);
    }
  }, [flushBuffer]);

  return { events, status, result, error, paused, runId, tokens, toolCalls, start, cancel, togglePause };
}