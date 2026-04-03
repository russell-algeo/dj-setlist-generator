import type { SubmissionRunWorkflowStepDto } from "@/lib/jobs/public";

type RunWorkflowTimelineProps = {
  steps: SubmissionRunWorkflowStepDto[];
};

const stateColors: Record<SubmissionRunWorkflowStepDto["state"], string> = {
  pending: "#2a2a2a",
  active: "#8f8a47",
  complete: "#2f7a42",
  failed: "#8a3a3a",
  cancelled: "#666",
};

const progressFillColors: Record<SubmissionRunWorkflowStepDto["state"], string> = {
  pending: "#2a2a2a",
  active: "#8f8a47",
  complete: "#2f7a42",
  failed: "#8a3a3a",
  cancelled: "#666",
};

const getStateLabel = (state: SubmissionRunWorkflowStepDto["state"]) => {
  switch (state) {
    case "active":
      return "In progress";
    case "complete":
      return "Done";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return "Pending";
  }
};

export function RunWorkflowTimeline({ steps }: RunWorkflowTimelineProps) {
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {steps.map((step, index) => {
        const color = stateColors[step.state];
        const progressRatio =
          step.progress && step.progress.total > 0
            ? Math.max(0, Math.min(1, step.progress.current / step.progress.total))
            : 0;

        return (
          <div
            key={step.key}
            style={{
              display: "grid",
              gridTemplateColumns: "18px minmax(0, 1fr)",
              columnGap: 12,
              alignItems: "flex-start",
            }}
          >
            <div style={{ display: "grid", justifyItems: "center", height: "100%" }}>
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  marginTop: 4,
                  background: step.state === "pending" ? "transparent" : color,
                  border: `1px solid ${color}`,
                  boxShadow: step.state === "active" ? `0 0 0 3px ${color}22` : "none",
                }}
              />
              {index < steps.length - 1 ? (
                <span
                  style={{
                    width: 1,
                    minHeight: 36,
                    marginTop: 4,
                    background: step.state === "pending" ? "#1f1f1f" : `${color}66`,
                  }}
                />
              ) : null}
            </div>

            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  flexWrap: "wrap",
                  alignItems: "baseline",
                }}
              >
                <span
                  style={{
                    color: step.state === "pending" ? "#666" : "#b5b5b5",
                    fontSize: 10,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                  }}
                >
                  {step.label}
                </span>
                <span style={{ color, fontSize: 9, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  {getStateLabel(step.state)}
                </span>
              </div>

              {step.detail ? (
                <div style={{ marginTop: 4, color: "#6e6e6e", fontSize: 10, lineHeight: 1.5 }}>
                  {step.detail}
                </div>
              ) : null}

              {step.progress ? (
                <div style={{ marginTop: 8 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 12,
                      color: "#5e5e5e",
                      fontSize: 9,
                      marginBottom: 4,
                    }}
                  >
                    <span style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {step.progress.label}
                    </span>
                    <span>
                      {step.progress.current}/{step.progress.total}
                    </span>
                  </div>
                  <div
                    style={{
                      height: 5,
                      borderRadius: 999,
                      background: "#151515",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        width: `${progressRatio * 100}%`,
                        height: "100%",
                        borderRadius: 999,
                        background: progressFillColors[step.state],
                      }}
                    />
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
