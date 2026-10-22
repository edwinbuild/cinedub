"use client";

import { useEffect, useId, useRef, useState, type ButtonHTMLAttributes } from "react";
import { createPortal } from "react-dom";

/** A short explanation on hover or keyboard focus, outside scrolling panel clips. */
export function TooltipButton({ label, description, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string; description: string;
}) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [active, setActive] = useState(false);
  const [position, setPosition] = useState<{ left: number; top: number; arrow: number; above: boolean } | null>(null);
  function clearTimer() { if (timer.current) clearTimeout(timer.current); timer.current = null; }
  function hide() { clearTimer(); setPosition(null); setActive(false); }
  function show(delay: number) {
    clearTimer(); setActive(true);
    timer.current = setTimeout(() => {
      const element = button.current;
      if (!element?.isConnected || element.closest("[hidden]")) return;
      const box = element.getBoundingClientRect();
      const width = Math.min(240, window.innerWidth - 16);
      const left = Math.max(8, Math.min(window.innerWidth - width - 8, box.x + box.width / 2 - width / 2));
      const above = box.bottom + 110 > window.innerHeight;
      setPosition({ left, top: above ? box.top - 9 : box.bottom + 9, arrow: Math.max(12, Math.min(width - 12, box.x + box.width / 2 - left)), above });
    }, delay);
  }
  function leave() {
    clearTimer();
    if (!button.current?.matches(":focus-visible")) timer.current = setTimeout(hide, 120);
  }
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  useEffect(() => {
    // Dismissal must cover the pending hover delay as well as the visible bubble.
    if (!active) return;
    function dismiss() { if (timer.current) clearTimeout(timer.current); timer.current = null; setPosition(null); setActive(false); }
    function escape(event: globalThis.KeyboardEvent) { if (event.key === "Escape") dismiss(); }
    window.addEventListener("resize", dismiss);
    window.addEventListener("scroll", dismiss, true);
    document.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("resize", dismiss); window.removeEventListener("scroll", dismiss, true);
      document.removeEventListener("keydown", escape);
    };
  }, [active]);

  return <><button {...props} ref={button} type={props.type ?? "button"} aria-label={props["aria-label"] ?? label}
    aria-describedby={[props["aria-describedby"], position ? id : null].filter(Boolean).join(" ") || undefined}
    onPointerEnter={(event) => { if (event.pointerType !== "touch") show(350); props.onPointerEnter?.(event); }}
    onPointerLeave={(event) => { leave(); props.onPointerLeave?.(event); }}
    onPointerDown={(event) => { hide(); props.onPointerDown?.(event); }}
    onFocus={(event) => { if (event.currentTarget.matches(":focus-visible")) show(0); props.onFocus?.(event); }}
    onBlur={(event) => { hide(); props.onBlur?.(event); }}
    onClick={(event) => { hide(); props.onClick?.(event); }}>{children}</button>
    {position && createPortal(<div id={id} role="tooltip" className={`controlTooltip ${position.above ? "above" : ""}`}
      style={{ left: position.left, top: position.top }} onPointerEnter={clearTimer} onPointerLeave={leave}>
      <i aria-hidden="true" style={{ left: position.arrow }} /><strong>{label}</strong><span>{description}</span>
    </div>, document.body)}
  </>;
}
