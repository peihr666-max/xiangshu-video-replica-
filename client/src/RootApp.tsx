import { AdminApp } from "./AdminApp";
import { App } from "./App";
import { CustomerApp } from "./customer/CustomerApp";

export function RootApp({
  path = window.location.pathname,
}: {
  path?: string;
}) {
  if (path === "/admin" || path.startsWith("/admin/")) {
    return <AdminApp />;
  }
  if (path === "/customer" || path.startsWith("/customer/")) {
    return <CustomerApp />;
  }
  return <App />;
}
