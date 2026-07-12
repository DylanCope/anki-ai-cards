"use client";

import { useState } from "react";
import { Expand } from "lucide-react";
import type { ImageOptionsPayload } from "@/app/lib/types";
import ImageLightbox from "@/app/components/ImageLightbox";

interface Props {
  payload: ImageOptionsPayload;
  onPick: (message: string) => void;
  disabled: boolean;
}

export default function ImageOptionsCard({ payload, onPick, disabled }: Props) {
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);

  const sources = payload.options.map(
    (base64, index) => `data:${payload.content_types[index] ?? "image/jpeg"};base64,${base64}`
  );

  return (
    <div className="mt-2 rounded-xl border border-border bg-surface p-4">
      <p className="mb-3 text-sm font-medium text-foreground/70">
        Image options{payload.query_or_prompt ? ` for "${payload.query_or_prompt}"` : ""}
      </p>
      <div className="flex flex-wrap gap-4">
        {sources.map((src, index) => (
          <div key={index} className="flex flex-col items-center gap-2">
            <button
              type="button"
              onClick={() => setLightboxIndex(index)}
              aria-label={`View option ${index + 1} full size`}
              className="group relative overflow-hidden rounded-lg"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- variable-format base64 data URI, not a fit for next/image */}
              <img
                src={src}
                alt={`Option ${index + 1}`}
                className="h-40 w-40 object-cover [image-rendering:auto] transition-transform group-hover:scale-105"
              />
              <span className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition group-hover:bg-black/20 group-hover:opacity-100">
                <Expand size={20} className="text-white drop-shadow" />
              </span>
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() =>
                onPick(
                  `Use image option ${index + 1} (image_id ${payload.image_ids[index]}).`
                )
              }
              className="rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground disabled:opacity-50"
            >
              Pick
            </button>
          </div>
        ))}
      </div>
      {lightboxIndex !== null && (
        <ImageLightbox
          src={sources[lightboxIndex]}
          alt={`Option ${lightboxIndex + 1}`}
          onClose={() => setLightboxIndex(null)}
        />
      )}
    </div>
  );
}
