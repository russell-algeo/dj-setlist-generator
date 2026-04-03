type StatusPillProps = {
  status: string;
  align?: "left" | "right";
};

const statusColors: Record<string, string> = {
  queued: "#555",
  running: "#7a7a3a",
  partial: "#7a5a3a",
  dispatched: "#7a7a3a",
  resolving: "#7a7a3a",
  recognizing: "#7a7a3a",
  aggregating: "#7a7a3a",
  enriching: "#7a7a3a",
  publishing: "#7a7a3a",
  cancelling: "#7a5a3a",
  completed: "#3a7a3a",
  failed: "#8a3a3a",
  cancelled: "#555",
  claimed: "#7a7a3a",
};

export const getStatusColor = (status: string) => statusColors[status] ?? "#555";

export function StatusPill({ status, align = "left" }: StatusPillProps) {
  const color = getStatusColor(status);

  return (
    <div style={{ display: "flex", justifyContent: align === "right" ? "flex-end" : "flex-start" }}>
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          minWidth: 0,
          padding: "2px 8px",
          borderRadius: 3,
          border: `1px solid ${color}`,
          background: `${color}18`,
          color,
          fontSize: 9,
          letterSpacing: "0.08em",
          lineHeight: 1.2,
          textTransform: "uppercase",
          whiteSpace: "nowrap",
        }}
      >
        {status}
      </span>
    </div>
  );
}
