"use client";

import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { Pause, Play } from "lucide-react";
import type { AudioOptionsPayload } from "@/app/lib/types";

interface Props {
  payload: AudioOptionsPayload;
  onPick: (message: string) => void;
  disabled: boolean;
}

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds)) return "0:00";
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

function AudioClip({ src }: { src: string }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    const onLoadedMetadata = () => setDuration(audio.duration || 0);
    const onEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
    };
    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("loadedmetadata", onLoadedMetadata);
    audio.addEventListener("ended", onEnded);
    return () => {
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("loadedmetadata", onLoadedMetadata);
      audio.removeEventListener("ended", onEnded);
    };
  }, []);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
    } else {
      void audio.play();
    }
    setIsPlaying(!isPlaying);
  };

  const handleSeek = (event: ChangeEvent<HTMLInputElement>) => {
    const audio = audioRef.current;
    if (!audio) return;
    const time = Number(event.target.value);
    audio.currentTime = time;
    setCurrentTime(time);
  };

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2">
      <audio ref={audioRef} src={src} preload="metadata" className="hidden" />
      <button
        type="button"
        onClick={togglePlay}
        aria-label={isPlaying ? "Pause" : "Play"}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground"
      >
        {isPlaying ? (
          <Pause size={12} fill="currentColor" />
        ) : (
          <Play size={12} fill="currentColor" className="ml-0.5" />
        )}
      </button>
      <input
        type="range"
        aria-label="Seek"
        min={0}
        max={duration || 0}
        step={0.01}
        value={Math.min(currentTime, duration || 0)}
        onChange={handleSeek}
        className="h-1 min-w-0 flex-1 accent-accent"
      />
      <span className="w-8 shrink-0 text-right text-[11px] tabular-nums text-foreground/50">
        {formatTime(duration ? duration - currentTime : 0)}
      </span>
    </div>
  );
}

export default function AudioOptionsCard({ payload, onPick, disabled }: Props) {
  return (
    <div className="mt-2 rounded-xl border border-border bg-surface p-4">
      <p className="mb-3 text-sm font-medium text-foreground/70">
        Audio options{payload.text ? ` for "${payload.text}"` : ""}
      </p>
      <div className="flex flex-col gap-3">
        {payload.options.map((base64, index) => (
          <div key={index} className="flex min-w-0 items-center gap-3">
            <span className="w-14 shrink-0 text-sm text-foreground/60">
              Option {index + 1}
            </span>
            <AudioClip src={`data:audio/mpeg;base64,${base64}`} />
            <button
              type="button"
              disabled={disabled}
              onClick={() =>
                onPick(
                  `Use audio option ${index + 1} (clip_id ${payload.clip_ids[index]}).`
                )
              }
              className="shrink-0 rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground disabled:opacity-50"
            >
              Pick
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
