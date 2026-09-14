import { CustomersPage } from "./CustomersPage";

export function CustomersManagementPage({
  readOnly = false,
}: {
  readOnly?: boolean;
}) {
  return <CustomersPage embedded readOnly={readOnly} />;
}
