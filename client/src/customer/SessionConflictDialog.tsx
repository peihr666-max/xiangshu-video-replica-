import { useState } from "react";

/** Session conflict dialog (FE-03 / T30).
 * Shows when a user tries to access their session from a device that's not the primary.
 */
export function SessionConflictDialog({
  conflict,
  onCancel,
  onSwitch,
}: {
  conflict: {
    deviceNameMasked: string;
    leaseExpiresAt: string;
    slotNo: number;
  };
  onCancel: () => void;
  onSwitch: () => void;
}): React.JSX.Element {
  const [isProcessing, setIsProcessing] = useState(false);

  const handleSwitch = async () => {
    setIsProcessing(true);
    try {
      await onSwitch();
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div
      className="session-conflict-dialog"
      role="dialog"
      aria-labelledby="conflict-title"
      aria-describedby="conflict-description"
    >
      <header>
        <h1 id="conflict-title">Session Conflict Detected</h1>
      </header>

      <div id="conflict-description">
        <p className="conflict-message">
          Your session is currently active on another device:{" "}
          <strong>{conflict.deviceNameMasked}</strong>
        </p>

        <p className="lease-info">
          Lease expires at: {new Date(conflict.leaseExpiresAt).toLocaleString()}
        </p>

        <p className="slot-info">
          Current slot: <strong>#{conflict.slotNo}</strong>
        </p>

        <p className="action-message">
          Would you like to switch to this session and take over your other
          device?
        </p>
      </div>

      <footer className="dialog-actions">
        <button
          type="button"
          className="btn-secondary"
          onClick={onCancel}
          disabled={isProcessing}
          aria-label="Cancel and stay on current device"
        >
          Cancel
        </button>

        <button
          type="button"
          className="btn-primary"
          onClick={handleSwitch}
          disabled={isProcessing}
          aria-label="Switch to this device"
        >
          {isProcessing ? "Switching..." : "Switch to This Device"}
        </button>
      </footer>
    </div>
  );
}
