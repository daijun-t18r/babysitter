"use client";

import { useState } from "react";

export function Composer({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");

  function submit() {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  }

  return (
    <div className="flex items-end gap-2 px-4 pt-2">
      <label htmlFor="composer" className="sr-only">
        Message
      </label>
      <textarea
        id="composer"
        rows={1}
        placeholder="What's going on?"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        className="max-h-32 min-h-14 flex-1 resize-none rounded-2xl border border-border-soft bg-surface px-4 py-4 placeholder:text-muted focus:border-accent focus:outline-none"
      />
      <button
        type="button"
        onClick={submit}
        disabled={disabled || !text.trim()}
        aria-label="Send"
        className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-accent text-background disabled:opacity-40"
      >
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden
        >
          <path d="M3.4 20.6l17.8-8.6L3.4 3.4l2.4 7.2 9.2 1.4-9.2 1.4-2.4 7.2z" />
        </svg>
      </button>
    </div>
  );
}
