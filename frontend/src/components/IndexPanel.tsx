import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Check,
  CheckCircle2,
  CircleDashed,
  History,
  Loader2,
  Play,
  RotateCcw,
  SkipForward,
  Sparkles,
  Square,
  XCircle,
} from 'lucide-react';
import type { BuildMode, ReviewDecision, Space, StreamEvent, Task, TaskStatus } from '../types';
import { cancelTask, createTask, getTask, listTasks, resumeTask } from '../api';
import { useTaskStream } from '../hooks/useTaskStream';
import { StreamEventsView } from './StreamEventsView';
import { formatDate } from '../lib/utils';

interface IndexPanelProps {
  space: Space;
}

const PHASES = [
  'skeleton',
  'prescan',
  'review_plan',
  'deepread',
  'audit',
  'review_issues',
  'done',
] as const;

const PHASE_LABELS: Record<string, string> = {
  skeleton: '初始化骨架',
  prescan: '预扫描',
  review_plan: '计划审核',
  deepread: '精读解析',
  audit: '质量审计',
  review_issues: '问题审核',
  done: '完成',
};

const STATUS_META: Record<TaskStatus, { label: string; className: string }> = {
  pending: { label: '待执行', className: 'bg-stone-100 text-stone-600' },
  running: { label: '执行中', className: 'bg-brand-50 text-brand-700' },
  paused: { label: '待审核', className: 'bg-amber-50 text-amber-700' },
  done: { label: '已完成', className: 'bg-emerald-50 text-emerald-700' },
  failed: { label: '失败', className: 'bg-red-50 text-red-700' },
  cancelled: { label: '已取消', className: 'bg-stone-100 text-stone-500' },
};

const ACTIVE_STATUSES: TaskStatus[] = ['pending', 'running', 'paused'];
const FINAL_STATUSES: TaskStatus[] = ['done', 'failed', 'cancelled'];

function isActive(status: TaskStatus | null | undefined): boolean {
  return !!status && ACTIVE_STATUSES.includes(status);
}

function isFinal(status: TaskStatus | null | undefined): boolean {
  return !!status && FINAL_STATUSES.includes(status);
}

function StatusBadge({ status }: { status: TaskStatus }) {
  const meta = STATUS_META[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${meta.className}`}
    >
      {status === 'running' && <Loader2 className="size-3 animate-spin" />}
      {status === 'paused' && <CircleDashed className="size-3" />}
      {status === 'done' && <CheckCircle2 className="size-3" />}
      {status === 'failed' && <AlertCircle className="size-3" />}
      {status === 'cancelled' && <XCircle className="size-3" />}
      {meta.label}
    </span>
  );
}

function PhaseStepper({
  phase,
  completed,
  status,
}: {
  phase: string;
  completed: Set<string>;
  status: TaskStatus | null;
}) {
  const taskDone = status === 'done';
  const taskActive = isActive(status);
  const taskStopped = status === 'cancelled' || status === 'failed';
  return (
    <div className="flex items-center overflow-x-auto">
      {PHASES.map((p, i) => {
        const done = completed.has(p) || (p === 'done' && taskDone);
        const stopped = taskStopped && phase === p;
        const active = taskActive && phase === p;
        return (
          <Fragment key={p}>
            {i > 0 && (
              <div
                className={`mx-1.5 h-px min-w-4 flex-1 ${
                  completed.has(p) || done ? 'bg-emerald-300' : 'bg-stone-200'
                }`}
              />
            )}
            <div className="flex shrink-0 flex-col items-center gap-1">
              <div
                className={`flex size-6 items-center justify-center rounded-full text-[10px] font-semibold ${
                  done
                    ? 'bg-emerald-500 text-white'
                    : stopped
                      ? 'bg-red-500 text-white'
                      : active
                        ? 'bg-brand-500 text-white'
                        : 'bg-stone-100 text-stone-400'
                }`}
              >
                {done ? (
                  <Check className="size-3.5" />
                ) : stopped ? (
                  <XCircle className="size-3.5" />
                ) : active ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  i + 1
                )}
              </div>
              <span
                className={`whitespace-nowrap text-[11px] leading-none ${
                  done || active ? 'text-stone-700' : stopped ? 'text-red-500' : 'text-stone-400'
                }`}
              >
                {PHASE_LABELS[p]}
              </span>
            </div>
          </Fragment>
        );
      })}
    </div>
  );
}

export function IndexPanel({ space }: IndexPanelProps) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [listLoading, setListLoading] = useState(true);

  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);

  const [buildMode, setBuildMode] = useState<BuildMode>('full');
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [resuming, setResuming] = useState(false);

  const { events, status: streamStatus, phase: streamPhase, error: streamError, subscribe, abort } =
    useTaskStream();

  // 当前正在订阅的任务 id，避免点击同一任务详情时重复发起 SSE 订阅
  const subscribedTaskIdRef = useRef<string | null>(null);

  const startSubscription = useCallback(
    (taskId: string) => {
      subscribedTaskIdRef.current = taskId;
      void subscribe(taskId);
    },
    [subscribe],
  );

  const stopSubscription = useCallback(() => {
    subscribedTaskIdRef.current = null;
    abort();
  }, [abort]);

  const refreshList = useCallback(async () => {
    try {
      const data = await listTasks(space.id);
      // 最新的排前面
      setTasks(data.sort((a, b) => (a.created_at < b.created_at ? 1 : -1)));
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setListLoading(false);
    }
  }, [space.id]);

  useEffect(() => {
    refreshList();
  }, [refreshList]);

  // 订阅中或订阅结束后的实时状态，优先于详情快照
  const displayStatus: TaskStatus | null = streamStatus ?? selectedTask?.status ?? null;
  const displayPhase = streamPhase || selectedTask?.phase || '';
  const displayError = streamError ?? selectedTask?.error ?? null;

  const handleSelect = useCallback(
    async (taskId: string) => {
      setSelectedTaskId(taskId);
      setActionError(null);
      try {
        const task = await getTask(taskId);
        setSelectedTask(task);
        if (isActive(task.status)) {
          // 仅当切换到不同任务时才订阅；重复点击同一任务不重复发起 SSE
          if (subscribedTaskIdRef.current !== taskId) {
            startSubscription(taskId);
          }
        } else {
          stopSubscription();
        }
      } catch (e) {
        setActionError((e as Error).message);
      }
    },
    [startSubscription, stopSubscription],
  );

  const handleCreate = useCallback(async () => {
    setCreating(true);
    setActionError(null);
    try {
      const task = await createTask({
        novel_id: space.id,
        build_mode: buildMode,
      });
      await refreshList();
      setSelectedTaskId(task.task_id);
      setSelectedTask(task);
      startSubscription(task.task_id);
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }, [space.id, buildMode, refreshList, startSubscription]);

  const handleResume = useCallback(
    async (decision: ReviewDecision) => {
      if (!selectedTaskId) return;
      setResuming(true);
      setActionError(null);
      try {
        await resumeTask(selectedTaskId, decision);
        const task = await getTask(selectedTaskId);
        setSelectedTask(task);
        startSubscription(selectedTaskId);
      } catch (e) {
        setActionError((e as Error).message);
      } finally {
        setResuming(false);
      }
    },
    [selectedTaskId, startSubscription],
  );

  const handleCancel = useCallback(async () => {
    if (!selectedTaskId) return;
    setActionError(null);
    try {
      await cancelTask(selectedTaskId);
      stopSubscription();
      const task = await getTask(selectedTaskId);
      setSelectedTask(task);
      await refreshList();
    } catch (e) {
      setActionError((e as Error).message);
    }
  }, [selectedTaskId, stopSubscription, refreshList]);

  // 任务到达终态时，刷新列表并同步详情快照
  useEffect(() => {
    if (isFinal(streamStatus)) {
      subscribedTaskIdRef.current = null;
      void refreshList();
      setSelectedTask((prev) =>
        prev && prev.task_id === selectedTaskId
          ? { ...prev, status: streamStatus!, phase: streamPhase, error: streamError }
          : prev,
      );
    }
  }, [streamStatus, streamPhase, streamError, selectedTaskId, refreshList]);

  // 从事件里提取已完成的阶段（node exit 事件）
  const completedPhases = useMemo(() => {
    const set = new Set<string>();
    for (const ev of events) {
      if (ev.type === 'node' && ev.node && ev.status === 'exit') set.add(ev.node);
    }
    // 历史任务不回放 events，需根据终态与 phase 补全已完成阶段：
    // - done：走完全部流程，done 之前的阶段全部已完成。
    // - cancelled/failed：停止在 displayPhase，该阶段之前的阶段均已完成。
    if (displayStatus === 'done') {
      for (const p of PHASES) {
        if (p !== 'done') set.add(p);
      }
    } else if (displayStatus === 'cancelled' || displayStatus === 'failed') {
      for (const p of PHASES) {
        if (p === displayPhase) break;
        if (p !== 'done') set.add(p);
      }
    }
    return set;
  }, [events, displayStatus, displayPhase]);

  // 从事件里提取非 node 事件交给 StreamEventsView 渲染
  const detailEvents = useMemo<StreamEvent[]>(
    () => events.filter((e) => e.type !== 'node'),
    [events],
  );

  const toolCount = useMemo(
    () => detailEvents.filter((e) => e.type === 'tool_call' || e.type === 'tool_result').length,
    [detailEvents],
  );

  return (
    <section className="flex h-full overflow-hidden rounded-xl border border-stone-200 bg-white">
      {/* 左侧任务列表 + 操作区 */}
      <aside className="flex w-80 shrink-0 flex-col border-r border-stone-200">
        <div className="border-b border-stone-100 px-4 py-3">
          <div className="flex items-center gap-2">
            <Sparkles className="size-4 text-brand-500" />
            <span className="text-sm font-semibold">索引生成</span>
          </div>

          <div className="mt-3 flex items-center gap-2">
            <select
              value={buildMode}
              onChange={(e) => setBuildMode(e.target.value as BuildMode)}
              aria-label="构建模式"
              className="h-9 flex-1 rounded-lg border border-stone-200 bg-stone-50 px-2 text-sm outline-none transition-colors focus:border-brand-400 focus:ring-2 focus:ring-brand-500/20"
            >
              <option value="full">全量构建</option>
              <option value="resume">断点续建</option>
              <option value="repair">修复构建</option>
            </select>
            <button
              type="button"
              onClick={handleCreate}
              disabled={creating}
              className="flex h-9 items-center gap-1.5 rounded-lg bg-brand-500 px-3 text-sm font-medium text-white transition-colors hover:bg-brand-600 disabled:opacity-50"
            >
              {creating ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              创建任务
            </button>
          </div>
        </div>

        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
          {actionError && (
            <p className="mx-3 mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-600">
              {actionError}
            </p>
          )}

          {listLoading ? (
            <div className="flex items-center justify-center gap-2 py-8 text-stone-400">
              <Loader2 className="size-4 animate-spin" />
              <span className="text-xs">加载中...</span>
            </div>
          ) : tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <History className="size-8 text-stone-300" />
              <p className="mt-2 text-sm text-stone-400">暂无索引生成任务</p>
              <p className="mt-1 text-xs text-stone-300">点击「创建任务」开始生成索引</p>
            </div>
          ) : (
            <ul className="space-y-1 p-2">
              {tasks.map((task) => {
                const active = task.task_id === selectedTaskId;
                return (
                  <li key={task.task_id}>
                    <button
                      type="button"
                      onClick={() => handleSelect(task.task_id)}
                      className={`flex w-full flex-col gap-1.5 rounded-lg px-3 py-2.5 text-left transition-colors ${
                        active ? 'bg-brand-50' : 'hover:bg-stone-100'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-mono text-xs text-stone-500">
                          {task.task_id.slice(0, 8)}
                        </span>
                        <StatusBadge status={task.status} />
                      </div>
                      <div className="flex items-center justify-between gap-2 text-xs text-stone-400">
                        <span>{task.phase ? PHASE_LABELS[task.phase] ?? task.phase : '—'}</span>
                        <span>{formatDate(task.created_at)}</span>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </aside>

      {/* 右侧任务详情 */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-100 px-5 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate font-mono text-xs text-stone-400">
              {selectedTask ? selectedTask.task_id : '未选择任务'}
            </span>
            {displayStatus && <StatusBadge status={displayStatus} />}
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {displayStatus === 'paused' && displayPhase === 'review_plan' && (
              <>
                <button
                  type="button"
                  onClick={() => handleResume('approve')}
                  disabled={resuming}
                  className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-600 disabled:opacity-50"
                >
                  <Check className="size-4" />
                  审核通过
                </button>
                <button
                  type="button"
                  onClick={() => handleResume('reject')}
                  disabled={resuming}
                  className="flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50"
                >
                  <XCircle className="size-4" />
                  审核驳回
                </button>
              </>
            )}
            {displayStatus === 'paused' && displayPhase === 'review_issues' && (
              <>
                <button
                  type="button"
                  onClick={() => handleResume('fixed')}
                  disabled={resuming}
                  className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-600 disabled:opacity-50"
                >
                  <RotateCcw className="size-4" />
                  修复重审
                </button>
                <button
                  type="button"
                  onClick={() => handleResume('skip')}
                  disabled={resuming}
                  className="flex items-center gap-1.5 rounded-lg border border-stone-200 px-3 py-1.5 text-sm font-medium text-stone-600 transition-colors hover:bg-stone-50 disabled:opacity-50"
                >
                  <SkipForward className="size-4" />
                  跳过
                </button>
                <button
                  type="button"
                  onClick={() => handleResume('stop')}
                  disabled={resuming}
                  className="flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50"
                >
                  <Square className="size-4" />
                  停止
                </button>
              </>
            )}
            {isActive(displayStatus) && displayStatus !== 'paused' && (
              <button
                type="button"
                onClick={handleCancel}
                className="flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 transition-colors hover:bg-red-50"
              >
                <Square className="size-4" />
                取消任务
              </button>
            )}
            {isFinal(displayStatus) && (
              <button
                type="button"
                onClick={handleCreate}
                disabled={creating}
                className="flex items-center gap-1.5 rounded-lg border border-stone-200 px-3 py-1.5 text-sm font-medium text-stone-600 transition-colors hover:bg-stone-50"
              >
                <RotateCcw className="size-4" />
                重新生成
              </button>
            )}
          </div>
        </div>

        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-5">
          {!selectedTask ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <Sparkles className="size-8 text-stone-300" />
              <p className="mt-2 text-sm text-stone-400">从左侧选择任务查看详情</p>
              <p className="mt-1 text-xs text-stone-300">或点击「创建任务」开始生成索引</p>
            </div>
          ) : (
            <div className="space-y-5">
              {/* 阶段时间线 */}
              <div className="rounded-lg border border-stone-200 bg-stone-50/60 px-5 py-4">
                <p className="mb-3 text-xs font-medium text-stone-400">执行阶段</p>
                <PhaseStepper phase={displayPhase} completed={completedPhases} status={displayStatus} />
              </div>

              {/* 执行详情 */}
              {(events.length > 0 || isActive(displayStatus)) && (
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-medium text-stone-400">执行过程</p>
                    {toolCount > 0 && (
                      <span className="text-xs text-stone-400">
                        {Math.floor(toolCount / 2)} 次工具调用
                      </span>
                    )}
                  </div>
                  {isActive(displayStatus) && (
                    <div className="mb-3 flex items-center gap-2 rounded-md bg-brand-50/60 px-3 py-2 text-xs text-brand-700">
                      <Loader2 className="size-3.5 animate-spin" />
                      {displayStatus === 'paused'
                        ? displayPhase === 'review_issues'
                          ? '等待人工审核（问题审核）...'
                          : '等待人工审核（计划审核）...'
                        : '正在执行...'}
                    </div>
                  )}
                  <StreamEventsView events={detailEvents} />
                </div>
              )}

              {displayError && (
                <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3">
                  <p className="mb-1 text-xs font-medium text-red-700">执行出错</p>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-red-600">
                    {displayError}
                  </p>
                </div>
              )}

              {displayStatus === 'done' && events.length === 0 && (
                <div className="flex items-center gap-2 rounded-md bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
                  <CheckCircle2 className="size-4" />
                  索引生成已完成
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
