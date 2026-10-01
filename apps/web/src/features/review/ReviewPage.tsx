import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Col, Empty, Row, Space, Spin, Typography } from "antd";
import { useMemo, useState } from "react";
import { useParams } from "react-router";

import { EvidenceViewer, type Highlight } from "../../components/EvidenceViewer";
import { TaskStatusTag } from "../../components/StatusTag";
import { api, download, unwrap, type CandidateEnvelope } from "../../lib/api";
import { errorText } from "../../lib/i18n";
import { hasRole, useProject } from "../../lib/session";
import { CandidateCard } from "./CandidateCard";
import { CommitDialog } from "./CommitDialog";
import { canApprove } from "./rules";

async function allCandidates(taskId: string): Promise<CandidateEnvelope[]> {
  const items: CandidateEnvelope[] = [];
  let cursor: string | undefined;
  do {
    const page = await unwrap(
      api.GET("/v1/jobs/{task_id}/candidates", {
        params: { path: { task_id: taskId }, query: { cursor, limit: 200 } },
      }),
    );
    items.push(...page.items);
    cursor = page.next_cursor ?? undefined;
  } while (cursor);
  return items;
}

export function ReviewPage() {
  const { taskId = "" } = useParams();
  const { project } = useProject();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [committing, setCommitting] = useState(false);
  const [approving, setApproving] = useState(false);

  const task = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => unwrap(api.GET("/v1/jobs/{task_id}", { params: { path: { task_id: taskId } } })),
  });
  const candidates = useQuery({
    queryKey: ["candidates", taskId],
    queryFn: () => allCandidates(taskId),
  });
  const document = useQuery({
    queryKey: ["document", taskId, task.data?.run_id],
    enabled: !!task.data?.run_id,
    queryFn: () =>
      unwrap(api.GET("/v1/jobs/{task_id}/document", { params: { path: { task_id: taskId } } })),
  });

  const items = useMemo(() => candidates.data ?? [], [candidates.data]);
  const visible = items.filter((e) => e.candidate.status !== "SUPERSEDED");
  const approvedSelected = visible.filter(
    (e) => e.candidate.status === "APPROVED" && selected.has(e.candidate.candidate_id),
  );
  const approvable = visible.filter(canApprove);
  const canEdit = hasRole(project, "uploader", "reviewer");
  const canReview = hasRole(project, "reviewer");

  async function approveAll() {
    setApproving(true);
    let done = 0;
    for (const envelope of approvable) {
      try {
        await unwrap(
          api.POST("/v1/reviews", {
            body: {
              candidate_id: envelope.candidate.candidate_id,
              revision: envelope.candidate.revision,
              decision: "approved",
            },
          }),
        );
        done += 1;
      } catch (error) {
        message.error(`${envelope.candidate.name?.value ?? ""}：${errorText(error)}`);
      }
    }
    setApproving(false);
    message.success(`已批准 ${done} 条`);
    await queryClient.invalidateQueries({ queryKey: ["candidates", taskId] });
  }

  if (task.error) return <Alert type="error" message={errorText(task.error)} />;
  if (task.isLoading || candidates.isLoading) return <Spin />;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card size="small">
        <Space wrap>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {task.data?.file_name}
          </Typography.Title>
          {task.data && <TaskStatusTag status={task.data.status} />}
          <Typography.Text type="secondary">共 {visible.length} 条候选</Typography.Text>
          {document.data?.run && (
            <Typography.Text type="secondary">
              解析器 {document.data.run.parser_version} · 编码 {document.data.run.source_encoding} ·
              质控 {document.data.run.qc_version}
            </Typography.Text>
          )}
          <Button
            onClick={() =>
              void download(`/v1/files/${task.data?.file_id}/content`).catch((e) =>
                message.error(errorText(e)),
              )
            }
          >
            下载原文件
          </Button>
        </Space>
        {(document.data?.run?.coverage?.warnings as string[] | undefined)?.map((warning) => (
          <Alert key={warning} type="warning" showIcon message={warning} style={{ marginTop: 8 }} />
        ))}
      </Card>
      <Row gutter={16}>
        <Col xs={24} lg={10}>
          <Card size="small" title="原文证据" className="sv-sticky">
            <EvidenceViewer
              blocks={document.data?.blocks ?? []}
              highlights={highlights}
              focus={focus}
            />
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Space direction="vertical" style={{ width: "100%" }}>
            {canReview && (
              <Card size="small" className="sv-actionbar">
                <Space wrap>
                  <Button disabled={!approvable.length} loading={approving} onClick={approveAll}>
                    批量批准（{approvable.length} 条无待处理问题）
                  </Button>
                  <Button
                    type="primary"
                    disabled={!approvedSelected.length}
                    onClick={() => setCommitting(true)}
                  >
                    提交入库（已选 {approvedSelected.length}）
                  </Button>
                  <Button
                    onClick={() =>
                      setSelected(
                        new Set(
                          visible
                            .filter((e) => e.candidate.status === "APPROVED")
                            .map((e) => e.candidate.candidate_id),
                        ),
                      )
                    }
                  >
                    全选已批准
                  </Button>
                </Space>
              </Card>
            )}
            {visible.length === 0 && (
              <Empty description="未发现序列。文件可能只有名称或其他内容，可补充资料后重新提取。" />
            )}
            {visible.map((envelope) => (
              <CandidateCard
                key={`${envelope.candidate.candidate_id}-${envelope.candidate.revision}`}
                envelope={envelope}
                taskId={taskId}
                canEdit={canEdit}
                canReview={canReview}
                selected={selected.has(envelope.candidate.candidate_id)}
                onSelect={(on) => {
                  const next = new Set(selected);
                  if (on) next.add(envelope.candidate.candidate_id);
                  else next.delete(envelope.candidate.candidate_id);
                  setSelected(next);
                }}
                onFocus={(marks, block) => {
                  setHighlights(marks);
                  setFocus(block);
                }}
              />
            ))}
          </Space>
        </Col>
      </Row>
      {committing && (
        <CommitDialog
          items={approvedSelected}
          taskId={taskId}
          onClose={() => {
            setCommitting(false);
            setSelected(new Set());
          }}
        />
      )}
    </Space>
  );
}
