import { BookOpen, Plus, Search, Trash2 } from 'lucide-react';
import type { Space } from '../types';
import { describeSpace } from '../lib/utils';

interface SidebarProps {
  spaces: Space[];
  selectedId: string | null;
  search: string;
  onSearchChange: (value: string) => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (space: Space) => void;
}

export function Sidebar({
  spaces,
  selectedId,
  search,
  onSearchChange,
  onSelect,
  onCreate,
  onDelete,
}: SidebarProps) {
  const filtered = spaces.filter((s) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q);
  });

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-stone-200 bg-white">
      <div className="flex items-center gap-2 px-4 pb-3 pt-5">
        <div className="flex size-8 items-center justify-center rounded-lg bg-brand-500 text-white">
          <BookOpen className="size-4" />
        </div>
        <h1 className="text-base font-semibold">小说空间</h1>
      </div>

      <div className="px-4">
        <button
          type="button"
          onClick={onCreate}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-brand-500 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-600"
        >
          <Plus className="size-4" />
          新建小说空间
        </button>
      </div>

      <div className="px-4 pt-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-stone-400" />
          <input
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="搜索小说空间..."
            aria-label="搜索小说空间"
            className="w-full rounded-lg border border-stone-200 bg-stone-50 py-2 pl-8 pr-3 text-sm outline-none transition-colors focus:border-brand-400 focus:ring-2 focus:ring-brand-500/20"
          />
        </div>
      </div>

      <div className="scrollbar-thin mt-3 flex-1 overflow-y-auto px-2 pb-4">
        {filtered.length === 0 ? (
          <p className="px-3 py-8 text-center text-sm text-stone-400">
            {search ? '未找到匹配的空间' : '还没有小说空间'}
          </p>
        ) : (
          <ul className="space-y-1">
            {filtered.map((space) => {
              const active = space.id === selectedId;
              return (
                <li key={space.id}>
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => onSelect(space.id)}
                    onKeyDown={(e) => e.key === 'Enter' && onSelect(space.id)}
                    className={`group relative cursor-pointer rounded-lg px-3 py-2.5 transition-colors ${
                      active ? 'bg-brand-50' : 'hover:bg-stone-100'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p
                        className={`truncate text-sm font-medium ${
                          active ? 'text-brand-700' : 'text-stone-800'
                        }`}
                      >
                        {space.name}
                      </p>
                      <button
                        type="button"
                        aria-label={`删除 ${space.name}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          onDelete(space);
                        }}
                        className="hidden shrink-0 rounded p-1 text-stone-400 hover:bg-stone-200 hover:text-red-500 group-hover:block"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-stone-400">
                      {describeSpace(space)}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
