import { useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpen, Files, Loader2, MessageSquare, Sparkles } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { Space } from './types';
import { createSpace, deleteSpace, listSpaces } from './api';
import { Sidebar } from './components/Sidebar';
import { CreateSpaceDialog } from './components/CreateSpaceDialog';
import { FileManager } from './components/FileManager';
import { IndexPanel } from './components/IndexPanel';
import { ChatWorkspace } from './components/ChatWorkspace';

type TabKey = 'index' | 'chat' | 'files';

const TABS: { key: TabKey; label: string; icon: LucideIcon }[] = [
  { key: 'index', label: '索引生成', icon: Sparkles },
  { key: 'chat', label: 'AI 写作助手', icon: MessageSquare },
  { key: 'files', label: '文件管理', icon: Files },
];

export default function App() {
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [activeTab, setActiveTab] = useState<TabKey>('index');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setLoadError(null);
      const data = await listSpaces();
      setSpaces(data);
    } catch (e) {
      setLoadError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // 保证 selectedId 始终有效：无空间时清空；选中项不存在时回退到第一项。
  useEffect(() => {
    if (spaces.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !spaces.some((s) => s.id === selectedId)) {
      setSelectedId(spaces[0].id);
    }
  }, [spaces, selectedId]);

  const selected = useMemo(
    () => spaces.find((s) => s.id === selectedId) ?? null,
    [spaces, selectedId],
  );

  const handleCreate = async (input: { name: string; description: string }) => {
    setSubmitting(true);
    try {
      const created = await createSpace(input);
      await refresh();
      setSelectedId(created.id);
      setActiveTab('index');
      setCreateOpen(false);
    } catch (e) {
      window.alert((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (space: Space) => {
    if (!window.confirm(`确定删除小说空间「${space.name}」吗？将同时删除其文件与索引。`)) return;
    try {
      await deleteSpace(space.id);
      await refresh();
    } catch (e) {
      window.alert((e as Error).message);
    }
  };

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        spaces={spaces}
        selectedId={selectedId}
        search={search}
        onSearchChange={setSearch}
        onSelect={setSelectedId}
        onCreate={() => setCreateOpen(true)}
        onDelete={handleDelete}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {loading ? (
          <div className="flex h-full items-center justify-center gap-2 text-stone-400">
            <Loader2 className="size-5 animate-spin" />
            <span className="text-sm">加载中...</span>
          </div>
        ) : loadError ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <p className="text-sm text-red-600">加载失败：{loadError}</p>
            <button
              type="button"
              onClick={refresh}
              className="rounded-lg border border-stone-200 px-4 py-2 text-sm font-medium text-stone-600 transition-colors hover:bg-stone-50"
            >
              重试
            </button>
          </div>
        ) : selected ? (
          <div key={selected.id} className="flex h-full flex-col">
            <header className="border-b border-stone-200 bg-white px-6 py-4">
              <h2 className="text-xl font-semibold text-stone-900">{selected.name}</h2>
              <p className="mt-1 text-sm leading-relaxed text-stone-500">
                {selected.description || '暂无简介'}
              </p>
            </header>

            <nav className="flex items-center gap-1 border-b border-stone-200 bg-white px-4">
              {TABS.map((tab) => {
                const Icon = tab.icon;
                const active = activeTab === tab.key;
                return (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setActiveTab(tab.key)}
                    className={`relative flex items-center gap-1.5 px-3.5 py-3 text-sm font-medium transition-colors ${
                      active ? 'text-brand-600' : 'text-stone-500 hover:text-stone-700'
                    }`}
                  >
                    <Icon className="size-4" />
                    {tab.label}
                    {active && (
                      <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand-500" />
                    )}
                  </button>
                );
              })}
            </nav>

            <div className="min-h-0 flex-1">
              {activeTab === 'index' && (
                <div className="h-full overflow-hidden p-6">
                  <IndexPanel space={selected} />
                </div>
              )}
              {activeTab === 'files' && (
                <div className="h-full overflow-hidden p-6">
                  <FileManager space={selected} />
                </div>
              )}
              {activeTab === 'chat' && (
                <div className="h-full overflow-hidden">
                  <ChatWorkspace space={selected} />
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <BookOpen className="size-10 text-stone-300" />
            <p className="mt-3 text-sm text-stone-500">选择或创建一个小说空间开始使用</p>
          </div>
        )}
      </main>

      <CreateSpaceDialog
        open={createOpen}
        submitting={submitting}
        onSubmit={handleCreate}
        onClose={() => setCreateOpen(false)}
      />
    </div>
  );
}