import { AimOutlined, CheckOutlined } from "@ant-design/icons";
import {
  AutoComplete,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import { CandidateStatusTag, SeverityTag } from "../../components/StatusTag";
import { SequenceView } from "../../components/SequenceView";
import type { Highlight } from "../../components/EvidenceViewer";
import { api, unwrap, type CandidateEnvelope, type Issue } from "../../lib/api";
import {
  completeness,
  nameSource,
  origin,
  resolutions as resolutionLabels,
  rules,
} from "../../lib/i18n";
import { useCandidateAction } from "./actions";
import { canApprove, hasBlock, unresolved } from "./rules";
import { SequenceEditor } from "./SequenceEditor";

export function highlightsFor(envelope: CandidateEnvelope, issue?: Issue): Highlight[] {
  const { candidate } = envelope;
  if (issue) return issue.evidence.map((span) => ({ ...span, mark: "issue" as const }));
  const result: Highlight[] = candidate.sequence_spans.map((span) => ({
    ...span,
    mark: "sequence" as const,
  }));
  if (candidate.name?.evidence) result.push({ ...candidate.name.evidence, mark: "name" });
  return result;
}

interface Props {
  envelope: CandidateEnvelope;
  taskId: string;
  canEdit: boolean;
  canReview: boolean;
  selected: boolean;
  onSelect: (selected: boolean) => void;
  onFocus: (highlights: Highlight[], blockId: string | null) => void;
}

export function CandidateCard({
  envelope,
  taskId,
  canEdit,
  canReview,
  selected,
  onSelect,
  onFocus,
}: Props) {
  const { candidate, review } = envelope;
  const [name, setName] = useState(candidate.name?.value ?? "");
  const [editing, setEditing] = useState(false);
  const id = candidate.candidate_id;
  const revision = candidate.revision;
  const open = ["NEEDS_REVIEW", "BLOCKED", "APPROVED", "PENDING_CONTENT"].includes(
    candidate.status,
  );

  const rename = useCandidateAction(taskId, (value: string) =>
    unwrap(
      api.PATCH("/v1/candidates/{candidate_id}", {
        params: { path: { candidate_id: id }, header: { "if-match": `"${revision}"` } },
        body: { name: value },
      }),
    ),
  );
  const resolve = useCandidateAction(
    taskId,
    ({ rule, resolution }: { rule: string; resolution: string }) =>
      unwrap(
        api.POST("/v1/candidates/{candidate_id}/resolutions", {
          params: { path: { candidate_id: id } },
          body: { revision, rule_id: rule, resolution },
        }),
      ),
  );
  const decide = useCandidateAction(taskId, (decision: "approved" | "rejected") =>
    unwrap(api.POST("/v1/reviews", { body: { candidate_id: id, revision, decision } })),
  );
  const archive = useCandidateAction(taskId, () =>
    unwrap(
      api.POST("/v1/candidates/{candidate_id}/archive", {
        params: { path: { candidate_id: id } },
        body: { revision },
      }),
    ),
  );

  const pending = unresolved(envelope);
  const focusFirst = (highlights: Highlight[]) =>
    onFocus(highlights, highlights[0]?.block_id ?? null);
  const nameOptions = candidate.extracted_names.map((n) => ({ value: n.value }));

  return (
    <Card
      size="small"
      className="sv-candidate"
      data-testid={`candidate-${candidate.extraction_record_index ?? id}`}
      onMouseEnter={() => focusFirst(highlightsFor(envelope))}
      title={
        <Space wrap>
          {candidate.status === "APPROVED" && (
            <Checkbox
              aria-label="选择入库"
              checked={selected}
              onChange={(e) => onSelect(e.target.checked)}
            />
          )}
          <CandidateStatusTag status={candidate.status} />
          <Typography.Text strong>{candidate.name?.value ?? "（未命名）"}</Typography.Text>
          {candidate.name && (
            <Tag>{nameSource[candidate.name.source] ?? candidate.name.source}</Tag>
          )}
        </Space>
      }
      extra={<Typography.Text type="secondary">修订 {revision}</Typography.Text>}
    >
      <Descriptions size="small" column={4}>
        <Descriptions.Item label="类型">
          {candidate.molecule_type === "protein"
            ? "蛋白质"
            : candidate.molecule_type === "uncertain"
              ? "不确定"
              : "核酸"}
        </Descriptions.Item>
        <Descriptions.Item label="长度">
          {Array.from(candidate.normalized_sequence).length}
        </Descriptions.Item>
        <Descriptions.Item label="完整性">{completeness[candidate.completeness]}</Descriptions.Item>
        <Descriptions.Item label="来源">{origin[candidate.origin]}</Descriptions.Item>
      </Descriptions>

      {canEdit && open && (
        <Space.Compact style={{ width: "100%", marginBottom: 12 }}>
          <AutoComplete
            aria-label="名称"
            style={{ flex: 1 }}
            value={name}
            options={nameOptions}
            onChange={setName}
            placeholder="选择或输入名称"
          />
          <Button
            disabled={!name.trim() || name === candidate.name?.value}
            loading={rename.isPending}
            onClick={() => rename.mutate(name)}
          >
            保存名称
          </Button>
        </Space.Compact>
      )}
      {candidate.extracted_names.length > 1 && (
        <Typography.Paragraph type="secondary">
          提取到的名称：
          {candidate.extracted_names
            .map((n) => `${n.value}（${nameSource[n.source] ?? n.source}）`)
            .join("；")}
        </Typography.Paragraph>
      )}

      <SequenceView sequence={candidate.normalized_sequence} />

      {candidate.issues.length > 0 && (
        <ul className="sv-issues">
          {candidate.issues.map((issue) => {
            const resolved = review.resolutions[issue.rule_id];
            const options = (review.allowed_resolutions[issue.rule_id] ?? []).map((value) => ({
              value,
              label: resolutionLabels[value] ?? value,
            }));
            return (
              <li key={issue.rule_id} data-rule={issue.rule_id}>
                <Space wrap>
                  <SeverityTag value={issue.severity} />
                  <Typography.Text strong>{issue.rule_id}</Typography.Text>
                  <Typography.Text>{rules[issue.rule_id] ?? ""}</Typography.Text>
                  {issue.evidence.length > 0 && (
                    <Button
                      size="small"
                      icon={<AimOutlined />}
                      onClick={() => focusFirst(highlightsFor(envelope, issue))}
                    >
                      定位
                    </Button>
                  )}
                </Space>
                <div className="sv-issue-message">{issue.message}</div>
                {issue.severity === "BLOCK" ? (
                  <Typography.Text type="danger">
                    阻断问题不能忽略：请修正序列或证据、补充资料，或登记为片段。
                  </Typography.Text>
                ) : resolved ? (
                  <Tag icon={<CheckOutlined />} color="success">
                    {resolutionLabels[resolved] ?? resolved}
                  </Tag>
                ) : (
                  issue.severity === "REVIEW" &&
                  canReview &&
                  candidate.status === "NEEDS_REVIEW" && (
                    <Select
                      aria-label={`处理 ${issue.rule_id}`}
                      size="small"
                      style={{ minWidth: 200 }}
                      placeholder="选择处理方式"
                      options={options}
                      onChange={(resolution: string) =>
                        resolve.mutate({ rule: issue.rule_id, resolution })
                      }
                    />
                  )
                )}
              </li>
            );
          })}
        </ul>
      )}

      <Space wrap style={{ marginTop: 12 }}>
        {canReview && candidate.status === "NEEDS_REVIEW" && (
          <Button
            type="primary"
            disabled={!canApprove(envelope)}
            loading={decide.isPending}
            onClick={() => decide.mutate("approved")}
            title={pending.length ? `待处理：${pending.join("、")}` : undefined}
          >
            批准
          </Button>
        )}
        {canReview && open && candidate.status !== "PENDING_CONTENT" && (
          <Popconfirm title="确定拒绝这条候选？" onConfirm={() => decide.mutate("rejected")}>
            <Button danger>拒绝</Button>
          </Popconfirm>
        )}
        {canEdit && open && (
          <Button onClick={() => setEditing(true)}>
            {hasBlock(envelope) ? "修正序列" : "编辑序列"}
          </Button>
        )}
        {canEdit && candidate.status === "PENDING_CONTENT" && (
          <Button onClick={() => archive.mutate(undefined)}>归档（待补充资料）</Button>
        )}
        {pending.length > 0 && candidate.status === "NEEDS_REVIEW" && (
          <Typography.Text type="warning">待处理：{pending.join("、")}</Typography.Text>
        )}
      </Space>
      {editing && (
        <SequenceEditor envelope={envelope} taskId={taskId} onClose={() => setEditing(false)} />
      )}
    </Card>
  );
}
