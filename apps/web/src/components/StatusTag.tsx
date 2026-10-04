import { Tag } from "antd";

import { candidateStatus, severity, taskStatus } from "../lib/i18n";

const TASK_COLORS: Record<string, string> = {
  REVIEW_READY: "gold",
  COMPLETED: "green",
  FAILED: "red",
  CANCELLED: "default",
  UNSUPPORTED: "volcano",
};

const CANDIDATE_COLORS: Record<string, string> = {
  NEEDS_REVIEW: "gold",
  BLOCKED: "red",
  APPROVED: "blue",
  COMMITTED: "green",
  REJECTED: "default",
  PENDING_CONTENT: "purple",
  ARCHIVED: "default",
  SUPERSEDED: "default",
};

export function TaskStatusTag({ status }: { status: string }) {
  return <Tag color={TASK_COLORS[status] ?? "processing"}>{taskStatus[status] ?? status}</Tag>;
}

export function CandidateStatusTag({ status }: { status: string }) {
  return (
    <Tag color={CANDIDATE_COLORS[status] ?? "default"}>{candidateStatus[status] ?? status}</Tag>
  );
}

export function SeverityTag({ value }: { value: string }) {
  const color = value === "BLOCK" ? "red" : value === "REVIEW" ? "gold" : "blue";
  return <Tag color={color}>{severity[value] ?? value}</Tag>;
}
