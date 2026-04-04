import { OperatorStatusBadge } from "@/components/operator/operator-ui";

type StatusPillProps = {
  align?: "left" | "right";
  status: string;
};

export function StatusPill({ status, align = "left" }: StatusPillProps) {
  return <OperatorStatusBadge align={align} status={status} />;
}
