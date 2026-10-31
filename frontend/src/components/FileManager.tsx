import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Download,
  Eye,
  FilePlus,
  Files,
  FileText,
  Loader2,
  Pencil,
  Save,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import type { Space } from '../types';
import {
  deleteResult,
  deleteSource,
  listResults,
  readResult,
  readSource,
  uploadSource,
  writeResult,
} from '../api';
import { formatBytes } from '../lib/utils';

interface FileManagerProps {
  space: Space;
}

type SelectedFile = { kind: 'source' } | { kind: 'result'; filename: string } | null;

type ViewMode = 'preview' | 'edit';

export function FileManager({ space }: FileManagerProps) {
  const [sourceExists, setSourceExists] = useState(false);
  const [sourceLoading, setSourceLoading] = useState(true);
  const [sourceSize, setSourceSize] = useState(0);

  const [resultFiles, setResultFiles] = useState<string[]>([]);
  const [resultLoading, setResultLoading] = useState(true);

  const [selected, setSelected] = useState<SelectedFile>(null);
  const [previewContent, setPreviewContent] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);

  const [viewMode, setViewMode] = useState<ViewMode>('preview');
  const [editContent, setEditContent] = useState('');
  const [dirty, setDirty] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [newFilename, setNewFilename] = useState('');
  const [newContent, setNewContent] = useState('');

  const sourceInputRef = useRef<HTMLInputElement>(null);

  const loadSource = useCallback(async () => {
    setSourceLoading(true);
    try {
      const res = await readSource(space.id);
      setSourceExists(true);
      setSourceSize(new TextEncoder().encode(res.content).length);
    } catch {
      setSourceExists(false);
      setSourceSize(0);
    } finally {
      setSourceLoading(false);
    }
  }, [space.id]);

  const loadResults = useCallback(async () => {
    setResultLoading(true);
    try {
      setResultFiles(await listResults(space.id));
    } catch {
      setResultFiles([]);
    } finally {
      setResultLoading(false);
    }
  }, [space.id]);

  useEffect(() => {
    loadSource();
    loadResults();
  }, [loadSource, loadResults]);

  // 选中文件后自动加载预览内容，并重置编辑状态
  useEffect(() => {
    if (!selected) {
      setPreviewContent('');
      setEditContent('');
      setViewMode('preview');
      setDirty(false);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    setViewMode('preview');
    setDirty(false);
    (async () => {
      try {
        const content =
          selected.kind === 'source'
            ? (await readSource(space.id)).content
            : (await readResult(space.id, selected.filename)).content;
        if (!cancelled) {
          setPreviewContent(content);
          setEditContent(content);
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setPreviewLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected, space.id]);

  const downloadText = (filename: string, content: string) => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleUploadSource = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      await uploadSource(space.id, file);
      await loadSource();
      setSelected({ kind: 'source' });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleDownloadSource = async () => {
    try {
      downloadText('novel.txt', (await readSource(space.id)).content);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const handleDeleteSource = async () => {
    if (!window.confirm('确定删除原文文件吗？此操作不可恢复。')) return;
    setBusy(true);
    setError(null);
    try {
      await deleteSource(space.id);
      await loadSource();
      if (selected?.kind === 'source') setSelected(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleDownloadResult = async (filename: string) => {
    try {
      const res = await readResult(space.id, filename);
      downloadText(filename, res.content);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const handleDeleteResult = async (filename: string) => {
    if (!window.confirm(`确定删除结果文件「${filename}」吗？此操作不可恢复。`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteResult(space.id, filename);
      await loadResults();
      if (selected?.kind === 'result' && selected.filename === filename) {
        setSelected(null);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleCreateResult = async () => {
    const filename = newFilename.trim();
    if (!filename) return;
    setBusy(true);
    setError(null);
    try {
      await writeResult(space.id, filename, newContent);
      setCreateOpen(false);
      setNewFilename('');
      setNewContent('');
      await loadResults();
      setSelected({ kind: 'result', filename });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleSaveResult = async () => {
    if (selected?.kind !== 'result') return;
    setBusy(true);
    setError(null);
    try {
      await writeResult(space.id, selected.filename, editContent);
      setPreviewContent(editContent);
      setDirty(false);
      setViewMode('preview');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleCancelEdit = () => {
    if (dirty && !window.confirm('放弃未保存的修改？')) return;
    setEditContent(previewContent);
    setDirty(false);
    setViewMode('preview');
  };

  // result 文件统一按 Markdown 处理；source 为纯文本
  const isResult = selected?.kind === 'result';

  const previewTitle =
    selected?.kind === 'source'
      ? 'novel.txt'
      : selected?.kind === 'result'
        ? selected.filename
        : '预览页面';

  return (
    <section className="flex h-full overflow-hidden rounded-xl border border-stone-200 bg-white">
      {/* 左侧文件列表 */}
      <aside className="flex w-72 shrink-0 flex-col border-r border-stone-200">
        <div className="flex items-center gap-2 border-b border-stone-100 px-4 py-3">
          <Files className="size-4 text-stone-400" />
          <span className="text-sm font-semibold">文件管理</span>
        </div>

        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
          {error && (
            <p className="mx-3 mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-600">
              {error}
            </p>
          )}

          {/* 小说原文 */}
          <div className="border-b border-stone-100 px-3 py-3">
            <div className="flex items-center justify-between px-1 pb-2">
              <span className="text-xs font-medium text-stone-400">小说原文</span>
              <input
                ref={sourceInputRef}
                type="file"
                accept=".txt,.md,text/plain,text/markdown"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleUploadSource(file);
                  e.target.value = '';
                }}
              />
              <button
                type="button"
                disabled={busy}
                onClick={() => sourceInputRef.current?.click()}
                className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium text-brand-600 transition-colors hover:bg-brand-50 disabled:opacity-50"
              >
                <Upload className="size-3.5" />
                上传
              </button>
            </div>

            {sourceLoading ? (
              <p className="px-1 py-2 text-xs text-stone-400">加载中...</p>
            ) : sourceExists ? (
              <button
                type="button"
                onClick={() => setSelected({ kind: 'source' })}
                className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors ${
                  selected?.kind === 'source' ? 'bg-brand-50' : 'hover:bg-stone-100'
                }`}
              >
                <FileText className="size-4 shrink-0 text-stone-400" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-stone-800">novel.txt</p>
                  <p className="text-xs text-stone-400">{formatBytes(sourceSize)}</p>
                </div>
              </button>
            ) : (
              <p className="px-1 py-2 text-xs text-stone-300">暂无原文文件</p>
            )}
          </div>

          {/* 生成结果 */}
          <div className="px-3 py-3">
            <div className="flex items-center justify-between px-1 pb-2">
              <span className="text-xs font-medium text-stone-400">生成结果</span>
              <button
                type="button"
                onClick={() => setCreateOpen(true)}
                className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium text-brand-600 transition-colors hover:bg-brand-50"
              >
                <FilePlus className="size-3.5" />
                新建
              </button>
            </div>

            {resultLoading ? (
              <p className="px-1 py-2 text-xs text-stone-400">加载中...</p>
            ) : resultFiles.length === 0 ? (
              <p className="px-1 py-2 text-xs text-stone-300">暂无生成结果</p>
            ) : (
              <ul className="space-y-0.5">
                {resultFiles.map((filename) => (
                  <li key={filename}>
                    <button
                      type="button"
                      onClick={() => setSelected({ kind: 'result', filename })}
                      className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors ${
                        selected?.kind === 'result' && selected.filename === filename
                          ? 'bg-brand-50'
                          : 'hover:bg-stone-100'
                      }`}
                    >
                      <FileText className="size-4 shrink-0 text-stone-400" />
                      <span className="truncate text-sm text-stone-700">{filename}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </aside>

      {/* 右侧预览 */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-stone-100 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <FileText className="size-4 shrink-0 text-stone-400" />
            <span className="truncate text-sm font-medium text-stone-700">{previewTitle}</span>
            {isResult && dirty && (
              <span className="shrink-0 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-600">
                未保存
              </span>
            )}
          </div>
          {selected && (
            <div className="flex shrink-0 items-center gap-1">
              {/* Markdown 编辑 / 预览切换 */}
              {isResult && viewMode === 'preview' && (
                <button
                  type="button"
                  onClick={() => setViewMode('edit')}
                  className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-100"
                >
                  <Pencil className="size-4" />
                  编辑
                </button>
              )}
              {isResult && viewMode === 'edit' && (
                <>
                  <button
                    type="button"
                    onClick={handleSaveResult}
                    disabled={busy || !dirty}
                    className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-brand-600 transition-colors hover:bg-brand-50 disabled:opacity-50"
                  >
                    <Save className="size-4" />
                    保存
                  </button>
                  <button
                    type="button"
                    onClick={handleCancelEdit}
                    className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-100"
                  >
                    <Eye className="size-4" />
                    预览
                  </button>
                </>
              )}

              {selected.kind === 'source' ? (
                <>
                  <button
                    type="button"
                    aria-label="下载"
                    onClick={handleDownloadSource}
                    className="rounded-md p-1.5 text-stone-400 transition-colors hover:bg-stone-200 hover:text-stone-700"
                  >
                    <Download className="size-4" />
                  </button>
                  <button
                    type="button"
                    aria-label="删除"
                    onClick={handleDeleteSource}
                    className="rounded-md p-1.5 text-stone-400 transition-colors hover:bg-red-50 hover:text-red-500"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    aria-label="下载"
                    onClick={() => handleDownloadResult(selected.filename)}
                    className="rounded-md p-1.5 text-stone-400 transition-colors hover:bg-stone-200 hover:text-stone-700"
                  >
                    <Download className="size-4" />
                  </button>
                  <button
                    type="button"
                    aria-label="删除"
                    onClick={() => handleDeleteResult(selected.filename)}
                    className="rounded-md p-1.5 text-stone-400 transition-colors hover:bg-red-50 hover:text-red-500"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-5">
          {!selected ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <FileText className="size-8 text-stone-300" />
              <p className="mt-2 text-sm text-stone-400">预览页面</p>
              <p className="mt-1 text-xs text-stone-300">从左侧选择文件以预览内容</p>
            </div>
          ) : previewLoading ? (
            <div className="flex h-full items-center justify-center text-stone-400">
              <Loader2 className="size-5 animate-spin" />
            </div>
          ) : isResult && viewMode === 'edit' ? (
            <textarea
              value={editContent}
              onChange={(e) => {
                setEditContent(e.target.value);
                setDirty(true);
              }}
              spellCheck={false}
              aria-label="编辑 Markdown 内容"
              className="h-full min-h-[400px] w-full resize-none rounded-lg border border-stone-200 bg-stone-50 p-4 font-mono text-sm leading-relaxed text-stone-700 outline-none transition-colors focus:border-brand-400 focus:ring-2 focus:ring-brand-500/20"
            />
          ) : isResult ? (
            <article className="prose prose-stone max-w-none prose-headings:scroll-mt-4 prose-pre:bg-stone-900 prose-pre:text-stone-100">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {previewContent || '（空文件）'}
              </ReactMarkdown>
            </article>
          ) : (
            <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed text-stone-700">
              {previewContent || '（空文件）'}
            </pre>
          )}
        </div>
      </div>

      {/* 新建结果文件对话框 */}
      {createOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setCreateOpen(false);
          }}
        >
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">新建结果文件</h2>
              <button
                type="button"
                aria-label="关闭"
                onClick={() => setCreateOpen(false)}
                className="rounded-md p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
              >
                <X className="size-5" />
              </button>
            </div>

            <div className="mt-5 space-y-4">
              <div>
                <label
                  htmlFor="result-filename"
                  className="mb-1.5 block text-sm font-medium text-stone-700"
                >
                  文件名
                </label>
                <input
                  id="result-filename"
                  value={newFilename}
                  onChange={(e) => setNewFilename(e.target.value)}
                  placeholder="例如：chapter-01.md"
                  autoFocus
                  className="w-full rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm outline-none transition-colors focus:border-brand-400 focus:ring-2 focus:ring-brand-500/20"
                />
              </div>
              <div>
                <label
                  htmlFor="result-content"
                  className="mb-1.5 block text-sm font-medium text-stone-700"
                >
                  内容
                </label>
                <textarea
                  id="result-content"
                  value={newContent}
                  onChange={(e) => setNewContent(e.target.value)}
                  placeholder="输入 Markdown 内容..."
                  rows={8}
                  className="w-full resize-none rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm outline-none transition-colors focus:border-brand-400 focus:ring-2 focus:ring-brand-500/20"
                />
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                className="rounded-lg border border-stone-200 px-4 py-2 text-sm font-medium text-stone-600 transition-colors hover:bg-stone-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleCreateResult}
                disabled={!newFilename.trim() || busy}
                className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? '创建中...' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
