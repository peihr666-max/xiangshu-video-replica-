import type { PendingPairing } from "./useCustomerSession";

/** A pairing approval card (FE-03 / T30) for the first bound device to approve pending pairings.
 * Displays masked device fingerprint, slot number, and pending status — never plaintext secrets.
 * Requires explicit user confirmation before approving; no silent approval.
 */
export function PairingApprovalCard({
  pairing,
  onApprove,
  onReject,
}: {
  pairing: PendingPairing;
  onApprove: (pairingId: string) => void;
  onReject: () => void;
}): JSX.Element {
  return (
    <article className="pairing-approval-card" aria-labelledby={`pairing-title-${pairing.id}`}>
      <header>
        <h3 id={`pairing-title-${pairing.id}`}>
          New Device Pairing Request - Pending Approval
        </h3>
        <span className="status-badge pending">Pending</span>
      </header>

      <div className="card-body">
        <p className="pairing-device-info">
          The following device is requesting to be paired as your <strong>Slot #{pairing.slotNo}</strong> device:
        </p>
        
        <p className="device-fingerprint">
          <strong>Device:</strong> {pairing.deviceFingerprint}
        </p>
        
        <p className="pairing-timestamp">
          Request created: {new Date(pairing.createdAt).toLocaleString()}
        </p>
        
        <p className="pairing-status-info">
          Pending approval — waiting for your confirmation before the pairing becomes active.
        </p>
        
        <p className="pairing-instructions">
          This will create a second device binding under the same customer identity.
          The new device must be approved by the first bound device's account holder.
        </p>
      </div>

      <footer className="card-actions">
        <button 
          type="button" 
          className="btn-secondary"
          onClick={onReject}
        >
          Reject
        </button>
        
        <button 
          type="button" 
          className="btn-primary"
          onClick={() => onApprove(pairing.id)}
        >
          Approve Pairing
        </button>
      </footer>
    </article>
  );
}
