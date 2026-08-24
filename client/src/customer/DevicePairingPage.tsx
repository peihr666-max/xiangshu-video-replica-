import { type JSX, useState } from "react";

/** Second-device pairing enrollment page (FE-03 / T30).
 * Collects device fingerprint and name, calls the enroll API.
 */
export function DevicePairingPage({
  onSuccess,
  onError,
  onCancel,
}: {
  onSuccess: (result: {
    status: "pending" | "consumed";
    data: unknown;
  }) => void;
  onError: (error: Error) => void;
  onCancel: () => void;
}): JSX.Element {
  const [isBusy, setIsBusy] = useState(false);
  const [deviceFingerprint, setDeviceFingerprint] = useState("");
  const [deviceName, setDeviceName] = useState("");

  const handleEnroll = async () => {
    setIsBusy(true);
    try {
      // In production this would call customerEnrollDevice()
      const response = await fetch("/api/customer/devices/enroll", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          activation_code: "", // Would come from user input
          device_fingerprint: deviceFingerprint,
          device_name: deviceName,
          device_platform: "web",
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({
          message: "Failed to enroll device",
        }));
        throw new Error(errorData.message || "Failed to enroll device");
      }

      const data = await response.json();
      onSuccess({
        status: data.status === "pending" ? "pending" : "consumed",
        data,
      });
    } catch (cause) {
      const error = cause instanceof Error ? cause : new Error(String(cause));
      onError(error);
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <main className="device-pairing-page" aria-labelledby="page-title">
      <header>
        <h1 id="page-title">Pair New Device</h1>
        <p className="page-subtitle">
          Register your second device under this customer identity
        </p>
      </header>

      <form onSubmit={(e) => e.preventDefault()} className="pairing-form">
        <div className="form-group">
          <label htmlFor="device-fingerprint">Device Fingerprint</label>
          <input
            type="text"
            id="device-fingerprint"
            value={deviceFingerprint}
            onChange={(e) => setDeviceFingerprint(e.target.value)}
            placeholder="e.g., Chrome on Windows •••• AB12"
            required
            aria-required="true"
          />
        </div>

        <div className="form-group">
          <label htmlFor="device-name">Device Name</label>
          <input
            type="text"
            id="device-name"
            value={deviceName}
            onChange={(e) => setDeviceName(e.target.value)}
            placeholder="e.g., My Personal Laptop"
            required
            aria-required="true"
          />
        </div>

        <div className="form-actions">
          <button
            type="button"
            className="btn-secondary"
            onClick={onCancel}
            disabled={isBusy}
          >
            Cancel
          </button>

          <button
            type="button"
            className="btn-primary"
            onClick={handleEnroll}
            disabled={isBusy}
          >
            {isBusy ? "Enrolling Device..." : "Enroll Device"}
          </button>
        </div>
      </form>
    </main>
  );
}
