import type { JSX } from "react";

/** A session displaced notice (FE-03 / T30) for when a user's session is replaced by another device.
 * Provides clear messaging about what happened and how to view the current session on the new device.
 */
export function SessionDisplacedNotice({
  onRestart,
}: {
  onRestart: () => void;
}): JSX.Element {
  return (
    <div className="session-displaced-overlay" role="alert" aria-live="polite">
      <div className="session-displaced-dialog">
        <h2>Session Replaced</h2>

        <p className="displaced-message">
          Your session was replaced by another device signing in at the same
          time.
        </p>

        <p className="displaced-info">
          <strong>Another device is now active</strong>.
        </p>

        <p className="displaced-instructions">
          To see your current session and workspace, please navigate back to the
          device where you logged in most recently.
        </p>

        <button type="button" className="btn-primary" onClick={onRestart}>
          View My Session
        </button>
      </div>
    </div>
  );
}
