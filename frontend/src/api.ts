import type {
  CreateSpaceInput,
  CreateTaskInput,
  ResultReadResult,
  ReviewDecision,
  SourceReadResult,
  Space,
  Task,
} from './types';

const JSON_HEADERS = { 'Content-Type': 'application/json' };

async function readError(res: Response): Promise<string> {
  const text = await res.text().catch(() => '');
  try {
    const data = JSON.parse(text);
    return data.detail ?? text;
  } catch {
    return text || res.statusText;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) throw new Error(await readError(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// 小说空间
// ---------------------------------------------------------------------------

export async function listSpaces(): Promise<Space[]> {
  return request<Space[]>('/api/spaces');
}

export async function createSpace(input: CreateSpaceInput): Promise<Space> {
  return request<Space>('/api/spaces', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
}

export async function getSpace(id: string): Promise<Space> {
  return request<Space>(`/api/spaces/${id}`);
}

export async function updateSpace(id: string, input: Partial<CreateSpaceInput>): Promise<Space> {
  return request<Space>(`/api/spaces/${id}`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
}

export async function deleteSpace(id: string): Promise<void> {
  await request<void>(`/api/spaces/${id}`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// 原文文件（source/novel.txt，唯一文件）
// ---------------------------------------------------------------------------

export async function readSource(id: string): Promise<SourceReadResult> {
  return request<SourceReadResult>(`/api/spaces/${id}/source`);
}

export async function uploadSource(id: string, file: File): Promise<{ path: string; size: number; encoding: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`/api/spaces/${id}/source`, { method: 'PUT', body: form });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function deleteSource(id: string): Promise<void> {
  await request<void>(`/api/spaces/${id}/source`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// 生成结果文件（result/ 下，多文件，需 filename 定位）
// ---------------------------------------------------------------------------

export async function listResults(id: string): Promise<string[]> {
  const res = await request<{ files: string[] }>(`/api/spaces/${id}/result`);
  return res.files;
}

export async function readResult(id: string, filename: string): Promise<ResultReadResult> {
  return request<ResultReadResult>(
    `/api/spaces/${id}/result/${encodeURIComponent(filename)}`,
  );
}

export async function writeResult(
  id: string,
  filename: string,
  content: string,
): Promise<{ path: string }> {
  return request<{ path: string }>(
    `/api/spaces/${id}/result/${encodeURIComponent(filename)}`,
    {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify({ content }),
    },
  );
}

export async function deleteResult(id: string, filename: string): Promise<void> {
  await request<void>(`/api/spaces/${id}/result/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
  });
}

// ---------------------------------------------------------------------------
// AI 任务（索引生成 / 对话），统一走 /api/runs/stream 的 SSE
// ---------------------------------------------------------------------------

export async function cancelRun(threadId: string, runId: string): Promise<void> {
  await request<void>(`/api/threads/${threadId}/runs/${runId}/cancel`, { method: 'POST' });
}

// ---------------------------------------------------------------------------
// 长任务（索引生成），对应后端 /api/tasks
// ---------------------------------------------------------------------------

export async function createTask(input: CreateTaskInput): Promise<Task> {
  return request<Task>('/api/tasks', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
}

export async function listTasks(novelId?: string): Promise<Task[]> {
  const query = novelId ? `?novel_id=${encodeURIComponent(novelId)}` : '';
  return request<Task[]>(`/api/tasks${query}`);
}

export async function getTask(taskId: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}`);
}

export async function resumeTask(
  taskId: string,
  decision: ReviewDecision,
): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/resume`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ decision: { decision } }),
  });
}

export async function cancelTask(taskId: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/cancel`, { method: 'POST' });
}
