import { useCallback, useEffect, useState } from 'react';
import { History, Loader2, MessageSquare, Plus, Trash2, X } from 'lucide-react';
import type { Session, Space } from '../types';
import { createSession, deleteSession, getSession, listSessions } from '../api';
import { ChatPanel } from './ChatPanel';

interface ChatWorkspaceProps {
  space: Space;
}

interface OpenWindow {
  sessionId: string;
  threadId: string;
  title: string;
}

export function ChatWorkspace({ space }: ChatWorkspaceProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [windows, setWindows] = useState<OpenWindow[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshSessions = useCallback(async () => {
    const all = await listSessions();
    setSessions(all.filter((s) => s.novel_id === space.id));
  }, [space.id]);

  // 初始化：加载该 space 的会话，若有历史则默认打开最近一个
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const all = await listSessions();
        const mine = all.filter((s) => s.novel_id === space.id);
        if (cancelled) return;
        setSessions(mine);
        if (mine.length > 0) {
          const latest = mine[0];
          const detail = await getSession(latest.session_id);
          const thread = detail.threads[0];
          setWindows([
            {
              sessionId: latest.session_id,
              threadId: thread?.thread_id ?? '',
              title: latest.title || '对话',
            },
          ]);
          setActiveId(latest.session_id);
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [space.id]);

  const handleNew = async () => {
    setError(null);
    try {
      const created = await createSession({ novel_id: space.id, title: '新对话' });
      const win: OpenWindow = {
        sessionId: created.session_id,
        threadId: created.thread_id,
        title: created.title || '新对话',
      };
      setWindows((prev) => [...prev, win]);
      setActiveId(created.session_id);
      await refreshSessions();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const handleOpenSession = async (sessionId: string) => {
    if (windows.some((w) => w.sessionId === sessionId)) {
      setActiveId(sessionId);
      setHistoryOpen(false);
      return;
    }
    setError(null);
    try {
      const detail = await getSession(sessionId);
      const thread = detail.threads[0];
      const win: OpenWindow = {
        sessionId,
        threadId: thread?.thread_id ?? '',
        title: detail.title || '对话',
      };
      setWindows((prev) => [...prev, win]);
      setActiveId(sessionId);
      setHistoryOpen(false);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const handleClose = (sessionId: string) => {
    const idx = windows.findIndex((w) => w.sessionId === sessionId);
    const next = windows.filter((w) => w.sessionId !== sessionId);
    setWindows(next);
    if (activeId === sessionId) {
      setActiveId(next.length ? next[Math.max(0, idx - 1)].sessionId : null);
    }
  };

  const handleDelete = async (sessionId: string) => {
    if (!window.confirm('确定删除该会话吗？将同时删除其对话记录。')) return;
    setError(null);
    try {
      await deleteSession(sessionId);
      handleClose(sessionId);
      await refreshSessions();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const activeWindow = windows.find((w) => w.sessionId === activeId) ?? null;

  return (
    <div className="flex h-full flex-col bg-white">
      {/* 窗口标签栏 */}
      <div className="flex items-center gap-2 border-b border-stone-100 px-3 py-2">
        <button
          type="button"
          onClick={handleNew}
          className="flex shrink-0 items-center gap-1 rounded-lg bg-brand-500 px-2.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-brand-600"
        >
          <Plus className="size-3.5" />
          新建对话
        </button>

        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {windows.map((w) => {
            const active = w.sessionId === activeId;
            return (
              <div
                key={w.sessionId}
                className={`flex shrink-0 items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
                  active
                    ? 'border-brand-200 bg-brand-50 text-brand-700'
                    : 'border-stone-200 text-stone-600 hover:bg-stone-50'
                }`}
              >
                <button
                  type="button"
                  onClick={() => setActiveId(w.sessionId)}
                  className="max-w-40 truncate"
                  title={w.title}
                >
                  {w.title}
                </button>
                <button
                  type="button"
                  aria-label={`关闭 ${w.title}`}
                  onClick={() => handleClose(w.sessionId)}
                  className="rounded p-0.5 text-stone-400 hover:bg-stone-200 hover:text-stone-600"
                >
                  <X className="size-3" />
                </button>
              </div>
            );
          })}
        </div>

        <div className="relative shrink-0">
          <button
            type="button"
            onClick={() => setHistoryOpen((v) => !v)}
            className="flex items-center gap-1 rounded-lg border border-stone-200 px-2.5 py-1.5 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-50"
          >
            <History className="size-3.5" />
            历史
          </button>

          {historyOpen && (
            <div className="absolute right-0 top-full z-20 mt-1 w-64 rounded-lg border border-stone-200 bg-white shadow-lg">
              <div className="max-h-72 overflow-y-auto p-1">
                {sessions.length === 0 ? (
                  <p className="px-3 py-6 text-center text-xs text-stone-400">暂无历史会话</p>
                ) : (
                  sessions.map((s) => (
                    <div
                      key={s.session_id}
                      className="group flex items-center gap-1 rounded-md px-2 py-1.5 hover:bg-stone-50"
                    >
                      <button
                        type="button"
                        onClick={() => handleOpenSession(s.session_id)}
                        className="min-w-0 flex-1 truncate text-left text-xs text-stone-700"
                        title={s.title}
                      >
                        {s.title || '未命名会话'}
                      </button>
                      <button
                        type="button"
                        aria-label={`删除 ${s.title}`}
                        onClick={() => handleDelete(s.session_id)}
                        className="shrink-0 rounded p-1 text-stone-400 opacity-0 hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {error && (
        <p className="border-b border-red-100 bg-red-50 px-4 py-1.5 text-xs text-red-600">{error}</p>
      )}

      {/* 当前窗口内容 */}
      <div className="min-h-0 flex-1">
        {loading ? (
          <div className="flex h-full items-center justify-center gap-2 text-stone-400">
            <Loader2 className="size-5 animate-spin" />
            <span className="text-sm">加载中...</span>
          </div>
        ) : activeWindow ? (
          <ChatPanel
            key={activeWindow.sessionId}
            sessionId={activeWindow.sessionId}
            threadId={activeWindow.threadId}
            novelId={space.id}
            title={activeWindow.title}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <MessageSquare className="size-10 text-stone-300" />
            <p className="mt-3 text-sm text-stone-500">还没有打开的对话</p>
            <button
              type="button"
              onClick={handleNew}
              className="mt-4 rounded-lg bg-brand-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-600"
            >
              新建对话
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
