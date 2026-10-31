import { useCallback, useRef, useState } from 'react';
import type { StreamEvent, TaskStatus } from '../types';

interface TaskStatusFrame {
  task_id: string;
  status: TaskStatus;
  phase: string;
}

interface TaskFinishedFrame {
  task_id: string;
  status: TaskStatus;
  phase: string;
  error: string | null;
}

/**
 * 订阅一个长任务的 SSE 事件流（POST /api/tasks/{id}/stream）。
 *
 * 事件序列：
 * - ``task.status``：订阅时的状态快照（status / phase）
 * - ``event``：结构化事件（node / tool_call / tool_result / message / reasoning）
 * - ``task.finished``：终态快照
 * - ``[DONE]``：流结束
 */
export function useTaskStream() {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<TaskStatus | null>(null);
  const [phase, setPhase] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  const abort = useCallback(() => {
    abortRef.current?.abort();
    // 重置流状态：取消/切换终态任务后，避免残留的 running 状态让界面误显示「执行中」。
    // 重置后 displayStatus 会回退到 selectedTask?.status（如 cancelled / done）。
    setStatus(null);
    setPhase('');
    setEvents([]);
    setError(null);
  }, []);

  const subscribe = useCallback(async (taskId: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setEvents([]);
    setStatus(null);
    setPhase('');
    setError(null);
    setStreaming(true);

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

      if (parsed.event === 'task.status') {
        const d = parsed.data as TaskStatusFrame;
        setStatus(d.status);
        setPhase(d.phase);
      } else if (parsed.event === 'event') {
        const ev = parsed.data as StreamEvent;
        setEvents((prev) => [...prev, ev]);
        // node 事件同步推进当前阶段
        if (ev.type === 'node' && ev.node) {
          setPhase(ev.node);
        }
      } else if (parsed.event === 'task.finished') {
        const d = parsed.data as TaskFinishedFrame;
        setStatus(d.status);
        setPhase(d.phase);
        if (d.error) setError(d.error);
      }
    };

    try {
      const res = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/stream`, {
        method: 'POST',
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        const text = await res.text().catch(() => '');
        throw new Error(`订阅失败 (${res.status}): ${text}`);
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
    } catch (e) {
      const err = e as Error;
      if (err.name !== 'AbortError') {
        setError(err.message);
      }
    } finally {
      setStreaming(false);
    }
  }, []);

  return { events, status, phase, error, streaming, subscribe, abort };
}
