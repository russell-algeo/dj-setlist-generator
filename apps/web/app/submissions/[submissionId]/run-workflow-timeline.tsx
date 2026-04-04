import type { CSSProperties } from "react";

import type { WorkflowStepDto } from "@/lib/jobs/public";

type WorkflowTimelineProps = {
  steps: WorkflowStepDto[];
};

const stateColors: Record<WorkflowStepDto["state"], string> = {
  pending: "#262626",
  active: "#d2ae32",
  complete: "#2f8a4d",
  failed: "#9a3e3e",
  cancelled: "#666",
};

const baseRailColor = "#1c1c1c";

const getStateLabel = (state: WorkflowStepDto["state"]) => {
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

const getSegmentBackground = (leftStep: WorkflowStepDto, rightStep: WorkflowStepDto) => {
  if (leftStep.state === "complete" && rightStep.state === "complete") {
    return stateColors.complete;
  }

  if (leftStep.state === "complete" && rightStep.state === "active") {
    return `linear-gradient(90deg, ${stateColors.complete} 0%, ${stateColors.complete} 42%, ${stateColors.active} 100%)`;
  }

  if (leftStep.state === "active" && rightStep.state === "pending") {
    return baseRailColor;
  }

  if (leftStep.state === "complete" && rightStep.state === "failed") {
    return `linear-gradient(90deg, ${stateColors.complete} 0%, ${stateColors.complete} 42%, ${stateColors.failed} 100%)`;
  }

  if (leftStep.state === "complete" && rightStep.state === "cancelled") {
    return `linear-gradient(90deg, ${stateColors.complete} 0%, ${stateColors.complete} 42%, ${stateColors.cancelled} 100%)`;
  }

  if (leftStep.state === "failed" || rightStep.state === "failed") {
    return stateColors.failed;
  }

  if (leftStep.state === "cancelled" || rightStep.state === "cancelled") {
    return stateColors.cancelled;
  }

  if (leftStep.state === "active" || rightStep.state === "active") {
    return stateColors.active;
  }

  return baseRailColor;
};

export function WorkflowTimeline({ steps }: WorkflowTimelineProps) {
  const nodeCenters = steps.map((_, index) =>
    steps.length === 1 ? 50 : ((index + 0.5) / steps.length) * 100,
  );
  const activeProgressStepIndex = steps.findIndex((step) => step.state === "active" && step.progress);
  const activeProgressStep = activeProgressStepIndex >= 0 ? steps[activeProgressStepIndex] : null;
  const progressRatio =
    activeProgressStep?.progress && activeProgressStep.progress.total > 0
      ? Math.max(
          0,
          Math.min(1, activeProgressStep.progress.current / activeProgressStep.progress.total),
        )
      : 0;
  const connectorLeftPercent =
    activeProgressStepIndex >= 0 ? nodeCenters[activeProgressStepIndex] ?? null : null;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div style={{ overflowX: "auto", paddingBottom: 2 }}>
        <div
          style={{
            minWidth: 680,
            display: "grid",
            gap: 16,
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))`,
              gap: 16,
            }}
          >
            {steps.map((step) => (
              <div key={`${step.key}:label`} style={{ textAlign: "center", minWidth: 0 }}>
                <div
                  style={{
                    color: step.state === "pending" ? "#666" : "#b9b9b9",
                    fontSize: 10,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    whiteSpace: "nowrap",
                  }}
                >
                  {step.label}
                </div>
              </div>
            ))}
          </div>

          <div style={{ position: "relative", height: 22 }}>
            <div
              style={{
                position: "absolute",
                inset: 0,
              }}
            >
              {steps.slice(0, -1).map((step, index) => {
                const left = nodeCenters[index] ?? 0;
                const right = nodeCenters[index + 1] ?? left;
                const nextStep = steps[index + 1];

                if (!nextStep) {
                  return null;
                }

                return (
                  <div
                    key={`${step.key}:${nextStep.key}:segment`}
                    style={{
                      position: "absolute",
                      left: `${left}%`,
                      width: `${Math.max(right - left, 0)}%`,
                      top: 10,
                      height: 2,
                      background: getSegmentBackground(step, nextStep),
                    }}
                  />
                );
              })}
            </div>

            <div
              style={{
                position: "absolute",
                inset: 0,
                display: "grid",
                gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))`,
                gap: 16,
                alignItems: "center",
              }}
            >
              {steps.map((step) => {
                const color = stateColors[step.state];
                const isActive = step.state === "active";

                return (
                  <div
                    key={`${step.key}:node`}
                    style={{
                      display: "flex",
                      justifyContent: "center",
                      alignItems: "center",
                    }}
                  >
                    <span
                      className={isActive ? "timelineNode timelineNodeActive" : "timelineNode"}
                      style={
                        {
                          "--timeline-node-color": color,
                          "--timeline-node-background":
                            step.state === "pending" ? "#0f0f0f" : color,
                        } as CSSProperties
                      }
                    >
                      <span className="timelineNodeInner" />
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))`,
              gap: 16,
              alignItems: "start",
            }}
          >
            {steps.map((step) => (
              <div key={`${step.key}:detail`} style={{ textAlign: "center", minWidth: 0 }}>
                <div
                  style={{
                    color: stateColors[step.state],
                    fontSize: 9,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                  }}
                >
                  {getStateLabel(step.state)}
                </div>
                {step.detail ? (
                  <div
                    style={{
                      marginTop: 5,
                      color: "#6e6e6e",
                      fontSize: 10,
                      lineHeight: 1.45,
                    }}
                  >
                    {step.detail}
                  </div>
                ) : null}
              </div>
            ))}
          </div>

          {activeProgressStep?.progress && connectorLeftPercent !== null ? (
            <div
              style={{
                position: "relative",
                marginTop: 4,
                paddingTop: 14,
              }}
            >
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  left: `${connectorLeftPercent}%`,
                  width: 1,
                  height: 12,
                  background: `${stateColors.active}88`,
                  transform: "translateX(-50%)",
                }}
              />

              <div
                style={{
                  borderRadius: 0,
                  border: `1px solid ${stateColors.active}44`,
                  background: "#131108",
                  padding: "12px 14px",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 12,
                    flexWrap: "wrap",
                    alignItems: "baseline",
                    marginBottom: 8,
                  }}
                >
                  <div style={{ color: "#7d7a66", fontSize: 10, lineHeight: 1.5 }}>
                    {activeProgressStep.detail}
                  </div>
                  <div
                    style={{
                      color: stateColors.active,
                      fontSize: 9,
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                    }}
                  >
                    {activeProgressStep.progress.current}/{activeProgressStep.progress.total}{" "}
                    {activeProgressStep.progress.label} complete
                  </div>
                </div>

                <div
                  style={{
                    height: 6,
                    borderRadius: 999,
                    background: "#1a1a1a",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${progressRatio * 100}%`,
                      height: "100%",
                      borderRadius: 999,
                      background:
                        "linear-gradient(90deg, #d2ae32 0%, #d6b735 28%, #8eb248 68%, #2f8a4d 100%)",
                    }}
                  />
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <style jsx>{`
        .timelineNode {
          position: relative;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 16px;
          height: 16px;
          border-radius: 999px;
          border: 1px solid var(--timeline-node-color);
          background: #0f0f0f;
          box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.35);
          z-index: 1;
        }

        .timelineNodeInner {
          width: 8px;
          height: 8px;
          border-radius: 999px;
          background: var(--timeline-node-background);
        }

        .timelineNodeActive {
          animation: timelinePulse 1.25s ease-in-out infinite;
          box-shadow:
            0 0 0 3px rgba(210, 174, 50, 0.16),
            inset 0 0 0 1px rgba(0, 0, 0, 0.35);
        }

        .timelineNodeActive::before {
          content: "";
          position: absolute;
          inset: -5px;
          border-radius: 999px;
          border: 2px solid rgba(210, 174, 50, 0.55);
          animation: timelineRing 1.25s ease-in-out infinite;
        }

        @keyframes timelinePulse {
          0%,
          100% {
            transform: scale(1);
          }

          50% {
            transform: scale(1.08);
          }
        }

        @keyframes timelineRing {
          0% {
            transform: scale(0.72);
            opacity: 0.85;
          }

          70% {
            transform: scale(1.1);
            opacity: 0.25;
          }

          100% {
            transform: scale(1.18);
            opacity: 0;
          }
        }
      `}</style>
    </div>
  );
}

export const RunWorkflowTimeline = WorkflowTimeline;
