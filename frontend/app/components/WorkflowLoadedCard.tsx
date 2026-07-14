"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Workflow } from "lucide-react";
import type { WorkflowLoadedPayload } from "@/app/lib/types";

interface Props {
  payload: WorkflowLoadedPayload;
}

export default function WorkflowLoadedCard({ payload }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mt-2 rounded-xl border border-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm">
          <Workflow size={14} className="shrink-0 text-accent" />
          <span className="text-foreground/70">
            Workflow loaded: <span className="font-medium text-foreground">{payload.name}</span>
          </span>
        </div>
        {payload.spec && (
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-foreground/60 hover:bg-foreground/5"
          >
            {expanded ? "Hide" : "Show"} spec
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        )}
      </div>
      {expanded && payload.spec && (
        <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-black/10 p-2 text-xs text-foreground/80 dark:bg-white/10">
          {payload.spec}
        </pre>
      )}
    </div>
  );
}
