// 与后端 spaces 模块的 SpaceResponse 对齐
export interface Space {
  id: string;
  name: string;
  description: string;
  author: string;
  created_at: string;
  updated_at: string;
}

export interface CreateSpaceInput {
  name: string;
  description?: string;
  author?: string;
}

// 后端 /api/spaces/{id}/source 返回
export interface SourceReadResult {
  content: string;
}

export interface SourceWriteResult {
  path: string;
  size: number;
  encoding: string;
}

// 后端 /api/spaces/{id}/result/{filename} 返回
export interface ResultReadResult {
  filename: string;
  content: string;
}

export type StreamEventType =
  | 'message'
  | 'reasoning'
  | 'tool_call'
  | 'tool_result'
  | 'node'
  | 'done';

export interface StreamEvent {
  type: StreamEventType;
  content?: string;
  name?: string;
  args?: Record<string, unknown> | string;
  tool_call_id?: string;
  source?: 'lead' | 'narration' | 'index';
  /** node 事件：当前节点名（skeleton/prescan/review_plan/deepread） */
  node?: string;
  status?: string;
  result?: string;
  error?: string;
}

export interface RunCreated {
  run_id: string;
  thread_id: string;
}

export interface RunFinished {
  run_id: string;
  status: string;
  result: string | null;
  error: string | null;
}

export type StreamTaskStatus =
  | 'idle'
  | 'running'
  | 'finished'
  | 'error'
  | 'cancelled';

// ---------------------------------------------------------------------------
// 长任务（索引生成等），对应后端 /api/tasks
// ---------------------------------------------------------------------------

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'paused'
  | 'done'
  | 'failed'
  | 'cancelled';

export type BuildMode = 'full' | 'resume' | 'repair';

export interface Task {
  task_id: string;
  novel_id: string;
  kind: string;
  status: TaskStatus;
  phase: string;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateTaskInput {
  novel_id: string;
  kind?: string;
  source_version?: string;
  build_mode?: BuildMode;
}

/** 人工审核决策：review_plan 用 approve/reject，review_issues 用 fixed/skip/stop */
export type ReviewDecision = 'approve' | 'reject' | 'fixed' | 'skip' | 'stop';
