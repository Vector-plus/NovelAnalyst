import { useState } from 'react';
import { X } from 'lucide-react';

interface CreateSpaceDialogProps {
  open: boolean;
  submitting: boolean;
  onSubmit: (input: { name: string; description: string }) => void;
  onClose: () => void;
}

export function CreateSpaceDialog({ open, submitting, onSubmit, onClose }: CreateSpaceDialogProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  if (!open) return null;

  const submit = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    onSubmit({ name: trimmed, description: description.trim() });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">新建小说空间</h2>
          <button
            type="button"
            aria-label="关闭"
            onClick={onClose}
            className="rounded-md p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
          >
            <X className="size-5" />
          </button>
        </div>

        <div className="mt-5 space-y-4">
          <div>
            <label htmlFor="space-name" className="mb-1.5 block text-sm font-medium text-stone-700">
              小说名称
            </label>
            <input
              id="space-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：遮天"
              autoFocus
              className="w-full rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm outline-none transition-colors focus:border-brand-400 focus:ring-2 focus:ring-brand-500/20"
            />
          </div>

          <div>
            <label
              htmlFor="space-description"
              className="mb-1.5 block text-sm font-medium text-stone-700"
            >
              描述
            </label>
            <textarea
              id="space-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="简单介绍一下这部小说..."
              rows={3}
              className="w-full resize-none rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm outline-none transition-colors focus:border-brand-400 focus:ring-2 focus:ring-brand-500/20"
            />
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-stone-200 px-4 py-2 text-sm font-medium text-stone-600 transition-colors hover:bg-stone-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!name.trim() || submitting}
            className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? '创建中...' : '创建'}
          </button>
        </div>
      </div>
    </div>
  );
}
