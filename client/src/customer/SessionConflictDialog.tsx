import type { JSX } from "react";
import type { CustomerSessionConflict } from "./useCustomerSession";

/** A read-only conflict dialog (FE-03 / T30) for when the server returns 409 OTHER_DEVICE_ONLINE.
 * Displays masked device name, lease expiry time, and slot number — never plaintext secrets.
 * Requires explicit user confirmation before switching; no auto-navigation or silent takeover.
 */
export function SessionConflictDialog({
  conflict,
  onCancel,
  onSwitch,
}: {
  conflict: CustomerSessionConflict;
  onCancel: () => void;
  onSwitch: () => void;
}): JSX.Element {
  const leaseDate = new Date(conflict.leaseExpiresAt);
  const formattedExpiry = leaseDate.toLocaleString(undefined, {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div
      className="session-conflict-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="conflict-title"
    >
      <div className="session-conflict-dialog">
        <h2 id="conflict-title">Another Device Is Online</h2>

        <p className="conflict-device-name">
          Detected: <strong>{conflict.deviceNameMasked}</strong>
        </p>

        <p className="conflict-details">
          This is your <strong>Slot #{conflict.slotNo}</strong> device.
        </p>

        <p className="conflict-lease-info">
          Lease expires at:{" "}
          <time dateTime={conflict.leaseExpiresAt}>{formattedExpiry}</time>
        </p>

        <p className="conflict-message">
          To continue using this device, you must confirm that you want to sign
          out from the other device first.
        </p>

        <div className="dialog-actions">
          <button type="button" className="btn-secondary" onClick={onCancel}>
            Cancel
          </button>

          <button type="button" className="btn-primary" onClick={onSwitch}>
            Switch to This Device
          </button>
        </div>
      </div>
    </div>
  );
}
