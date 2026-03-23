import { formatBytes, formatPercent } from "../lib/format";

export default function MetricBar({ label, percent, caption, bytes }) {
  return (
    <div className="metric-bar">
      <div className="metric-bar-head">
        <span>{label}</span>
        <span>{caption || formatPercent(percent)}</span>
      </div>
      <div className="metric-track">
        <div className="metric-fill" style={{ width: `${Math.min(percent || 0, 100)}%` }} />
      </div>
      {bytes !== undefined ? <small>{formatBytes(bytes)}</small> : null}
    </div>
  );
}
