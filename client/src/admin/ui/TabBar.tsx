import type { ReactNode } from "react";

export type TabBarItem = { id: string; label: string };

export function TabBar({
  items,
  active,
  onChange,
  actions,
  ariaLabel,
}: {
  items: TabBarItem[];
  active: string;
  onChange: (id: string) => void;
  actions?: ReactNode;
  ariaLabel: string;
}) {
  return (
    <div className="admin-page-tabs">
      <div
        aria-label={ariaLabel}
        className="admin-page-tabs__items"
        role="tablist"
      >
        {items.map((item) => (
          <button
            aria-selected={active === item.id}
            className={
              active === item.id ? "admin-page-tab is-active" : "admin-page-tab"
            }
            key={item.id}
            role="tab"
            type="button"
            onClick={() => onChange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {actions ? (
        <div className="admin-page-tabs__actions">{actions}</div>
      ) : null}
    </div>
  );
}
