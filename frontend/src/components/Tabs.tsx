import { useId, useRef, type ReactNode } from "react";

/** Automatic activation with roving focus; only the active panel is mounted. */
export function Tabs({ label, items, value, onChange, children }: {
  label: string; items: string[]; value: string;
  onChange: (value: string) => void; children: ReactNode;
}) {
  const id = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  return <>
    <div className="view-tabs" role="tablist" aria-label={label}>
      {items.map((item, index) => <button type="button" key={item}
        ref={node => { buttons.current[index] = node; }}
        role="tab" id={`${id}-tab-${index}`} aria-controls={`${id}-panel-${index}`}
        aria-selected={value === item} tabIndex={value === item ? 0 : -1}
        onClick={() => onChange(item)}
        onKeyDown={event => {
          let next: number;
          if (event.key === "ArrowRight") next = (index + 1) % items.length;
          else if (event.key === "ArrowLeft") next = (index + items.length - 1) % items.length;
          else if (event.key === "Home") next = 0;
          else if (event.key === "End") next = items.length - 1;
          else return;
          event.preventDefault();
          onChange(items[next]);
          buttons.current[next]?.focus();
        }}>{item}</button>)}
    </div>
    {items.map((item, index) => <div key={item} className="view-panel" role="tabpanel" tabIndex={0}
      hidden={value !== item} id={`${id}-panel-${index}`} aria-labelledby={`${id}-tab-${index}`}>
      {value === item ? children : null}
    </div>)}
  </>;
}
