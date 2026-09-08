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
      <fieldset aria-label={ariaLabel} className="admin-page-tabs__items">
        {items.map((item) => (
          <button
            aria-pressed={active === item.id}
            className={
              active === item.id ? "admin-page-tab is-active" : "admin-page-tab"
            }
            key={item.id}
            type="button"
            onClick={() => onChange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </fieldset>
      {actions ? (
        <div className="admin-page-tabs__actions">{actions}</div>
      ) : null}
    </div>
  );
}
