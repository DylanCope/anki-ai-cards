"use client";

import { useEffect } from "react";
import { X } from "lucide-react";

interface Props {
  src: string;
  alt?: string;
  onClose: () => void;
}

export default function ImageLightbox({ src, alt = "", onClose }: Props) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6 backdrop-blur-md"
      onClick={onClose}
    >
      <div className="relative" onClick={(event) => event.stopPropagation()}>
        {/* eslint-disable-next-line @next/next/no-img-element -- variable-format data URI/blob URL, not a fit for next/image */}
        <img
          src={src}
          alt={alt}
          className="block max-h-[88vh] max-w-[92vw] rounded-xl object-contain shadow-2xl"
        />
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute -top-3 -right-3 rounded-full border border-border bg-surface p-1.5 text-foreground/70 shadow-lg hover:text-foreground"
        >
          <X size={18} />
        </button>
      </div>
    </div>
  );
}
