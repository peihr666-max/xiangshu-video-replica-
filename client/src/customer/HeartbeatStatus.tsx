/** Heartbeat status indicator (FE-04 / T31).
 * Shows the last heartbeat time, refresh interval, and connection health.
 */
export function HeartbeatStatus({
  lastHeartbeatAt,
  intervalSeconds = 30,
  onRefresh,
}: {
  lastHeartbeatAt: string;
  intervalSeconds?: number;
  onRefresh: () => void;
}): React.JSX.Element {
  const now = new Date();
  const heartbeat = new Date(lastHeartbeatAt);
  const diffMs = now.getTime() - heartbeat.getTime();
  const secondsSinceLast = Math.floor(diffMs / 1_000);

  // Status thresholds
  const isHealthy = secondsSinceLast < intervalSeconds * 0.8; // < 80% of interval
  const isWarning = secondsSinceLast >= intervalSeconds; // overdue
  const isExpired = secondsSinceLast > intervalSeconds * 2; // > 2x interval

  const formattedHeartbeat = heartbeat.toLocaleString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div
      className={`heartbeat-status ${isHealthy ? "healthy" : isWarning ? "warning" : "expired"}`}
      role="status"
      aria-live="polite"
    >
      <p className="label">
        上次心跳：<time dateTime={lastHeartbeatAt}>{formattedHeartbeat}</time>
      </p>

      <p className="interval-info">每 {intervalSeconds} 秒自动续约会话</p>

      {isHealthy && <span className="status-text healthy">✓ 连接正常</span>}

      {isWarning && !isExpired && (
        <span className="status-text warning">⚠️ 心跳已逾期，会话即将失效</span>
      )}

      {isExpired && (
        <span className="status-text expired">✕ 会话已过期，请重新登录</span>
      )}

      <button
        type="button"
        className="btn-refresh"
        onClick={onRefresh}
        disabled={isExpired}
        aria-label="立即发送心跳"
      >
        立即续约
      </button>

      <footer className="help-text">
        会话每 {intervalSeconds} 秒自动续约；长时间失联后需要重新登录。
      </footer>
    </div>
  );
}
