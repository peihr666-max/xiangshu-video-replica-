import { CustomersPage } from "./CustomersPage";

export function CustomersManagementPage({
  operatorId = "standalone-admin",
  readOnly = false,
}: {
  operatorId?: string;
  readOnly?: boolean;
}) {
  return <CustomersPage embedded operatorId={operatorId} readOnly={readOnly} />;
}
