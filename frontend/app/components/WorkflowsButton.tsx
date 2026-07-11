"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Plus, Trash2, Workflow, X } from "lucide-react";
import type { WorkflowSpec } from "@/app/lib/types";

type View = "list" | "edit" | "new";

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function WorkflowsButton() {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>("list");
  const [specs, setSpecs] = useState<WorkflowSpec[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [activeName, setActiveName] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [newName, setNewName] = useState("");
  const [newText, setNewText] = useState("");

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      if (cancelled) return;
      setError(null);
      try {
        const res = await fetch("/api/workflow-specs");
        if (!res.ok) throw new Error(`Failed to load workflows (${res.status})`);
        const data = (await res.json()) as WorkflowSpec[];
        if (!cancelled) setSpecs(data);
      } catch {
        if (!cancelled) setError("Could not load saved workflows.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  function close() {
    setOpen(false);
    setView("list");
    setActiveName(null);
    setError(null);
  }

  function openEdit(spec: WorkflowSpec) {
    setActiveName(spec.name);
    setEditText(spec.spec);
    setView("edit");
  }

  function openNew() {
    setNewName("");
    setNewText("");
    setView("new");
  }

  async function saveEdit() {
    if (activeName === null) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/workflow-specs/${encodeURIComponent(activeName)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec: editText }),
      });
      if (!res.ok) throw new Error(`Save failed (${res.status})`);
      const updated = (await res.json()) as WorkflowSpec;
      setSpecs((prev) => (prev ? prev.map((s) => (s.name === updated.name ? updated : s)) : prev));
      setView("list");
      setActiveName(null);
    } catch {
      setError("Could not save that workflow.");
    } finally {
      setBusy(false);
    }
  }

  async function createNew() {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/workflow-specs/${encodeURIComponent(name)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec: newText }),
      });
      if (!res.ok) throw new Error(`Create failed (${res.status})`);
      const created = (await res.json()) as WorkflowSpec;
      setSpecs((prev) => (prev ? [created, ...prev.filter((s) => s.name !== created.name)] : [created]));
      setView("list");
    } catch {
      setError("Could not create that workflow.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteSpec(name: string) {
    if (!window.confirm(`Delete workflow "${name}"? This cannot be undone.`)) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/workflow-specs/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      setSpecs((prev) => (prev ? prev.filter((s) => s.name !== name) : prev));
      if (activeName === name) {
        setView("list");
        setActiveName(null);
      }
    } catch {
      setError("Could not delete that workflow.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Workflows"
        title="Workflows"
        className="flex h-9 w-9 items-center justify-center rounded-lg border border-border text-foreground/70 transition-colors hover:bg-foreground/5"
      >
        <Workflow size={18} />
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={close}
        >
          <div
            className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-xl border border-border bg-surface shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div className="flex items-center gap-2">
                {view !== "list" && (
                  <button
                    type="button"
                    onClick={() => {
                      setView("list");
                      setActiveName(null);
                    }}
                    aria-label="Back to workflow list"
                    className="rounded-lg p-1 text-foreground/50 hover:bg-foreground/5 hover:text-foreground"
                  >
                    <ArrowLeft size={16} />
                  </button>
                )}
                <Workflow size={16} className="text-accent" />
                <h2 className="text-sm font-semibold text-foreground">
                  {view === "list" ? "Workflows" : view === "new" ? "New workflow" : activeName}
                </h2>
              </div>
              <button
                type="button"
                onClick={close}
                aria-label="Close"
                className="rounded-lg p-1 text-foreground/50 hover:bg-foreground/5 hover:text-foreground"
              >
                <X size={16} />
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {error && <p className="mb-3 text-sm text-red-500">{error}</p>}

              {view === "list" && (
                <div className="flex flex-col gap-2">
                  <button
                    type="button"
                    onClick={openNew}
                    className="flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-2 text-sm font-medium text-foreground/70 hover:bg-foreground/5"
                  >
                    <Plus size={14} /> New workflow
                  </button>
                  {specs === null && (
                    <p className="py-4 text-center text-sm text-foreground/50">Loading…</p>
                  )}
                  {specs !== null && specs.length === 0 && (
                    <p className="py-4 text-center text-sm text-foreground/50">
                      No saved workflows yet. The agent saves one automatically once you settle
                      on how to handle a source, or you can write one yourself.
                    </p>
                  )}
                  {specs?.map((spec) => (
                    <div
                      key={spec.name}
                      className="group flex items-start justify-between gap-2 rounded-lg border border-border px-3 py-2 hover:bg-foreground/5"
                    >
                      <button
                        type="button"
                        onClick={() => openEdit(spec)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <p className="truncate text-sm font-medium text-foreground">{spec.name}</p>
                        <p className="text-xs text-foreground/40">
                          Updated {formatDate(spec.updated_at)}
                        </p>
                        <p className="mt-1 line-clamp-2 text-xs text-foreground/60">{spec.spec}</p>
                      </button>
                      <button
                        type="button"
                        onClick={() => deleteSpec(spec.name)}
                        disabled={busy}
                        aria-label={`Delete ${spec.name}`}
                        className="shrink-0 rounded-lg p-1.5 text-foreground/40 opacity-0 hover:bg-foreground/10 hover:text-red-500 group-hover:opacity-100 disabled:opacity-50"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {view === "edit" && (
                <div className="flex flex-col gap-3">
                  <textarea
                    value={editText}
                    onChange={(event) => setEditText(event.target.value)}
                    rows={12}
                    className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs text-foreground"
                  />
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => activeName && deleteSpec(activeName)}
                      disabled={busy}
                      className="rounded-lg border border-border px-3 py-1.5 text-sm text-red-500 hover:bg-red-500/10 disabled:opacity-50"
                    >
                      Delete
                    </button>
                    <button
                      type="button"
                      onClick={saveEdit}
                      disabled={busy}
                      className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground disabled:opacity-50"
                    >
                      Save
                    </button>
                  </div>
                </div>
              )}

              {view === "new" && (
                <div className="flex flex-col gap-3">
                  <input
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                    placeholder="Workflow name"
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground"
                  />
                  <textarea
                    value={newText}
                    onChange={(event) => setNewText(event.target.value)}
                    placeholder="Describe the workflow…"
                    rows={12}
                    className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs text-foreground"
                  />
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={createNew}
                      disabled={busy || !newName.trim()}
                      className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground disabled:opacity-50"
                    >
                      Create
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
