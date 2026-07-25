"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Wrench } from "lucide-react";
import type { ToolCallsPayload } from "@/app/lib/types";

interface Props {
  payload: ToolCallsPayload;
}

export default function ToolCallsCard({ payload }: Props) {
  const [expanded, setExpanded] = useState(false);
  const count = payload.calls.length;

  return (
    <div className="mt-2 rounded-xl border border-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm">
          <Wrench size={14} className="shrink-0 text-accent" />
          <span className="text-foreground/70">
            {count} tool {count === 1 ? "call" : "calls"}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-foreground/60 hover:bg-foreground/5"
        >
          {expanded ? "Hide" : "Show"} details
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
      </div>
      {expanded && (
        <div className="mt-2 flex flex-col gap-2">
          {payload.calls.map((call, index) => (
            <div key={index} className="rounded-lg bg-black/10 p-2 dark:bg-white/10">
              <div className="font-mono text-xs font-medium text-foreground/80">{call.name}</div>
              <pre className="mt-1 whitespace-pre-wrap break-words text-xs text-foreground/70">
                {JSON.stringify(call.input, null, 2)}
              </pre>
              <pre className="mt-1 whitespace-pre-wrap break-words text-xs text-foreground/60">
                {"-> "}
                {JSON.stringify(call.result, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
