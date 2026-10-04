import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Descriptions, Modal, Spin, Table, Tag } from "antd";
import { useState } from "react";

import { api, unwrap, type CandidateEnvelope, type CommitResult } from "../../lib/api";
import { commitReason, commitStatus, errorText } from "../../lib/i18n";

/** Preview counts, commit with one idempotency key, and show per-item results. */
export function CommitDialog({
  items,
  taskId,
  onClose,
}: {
  items: CandidateEnvelope[];
  taskId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [key] = useState(() => crypto.randomUUID());
  // Fixed when the dialog opens: committed items drop out of `items` after the refetch, and
  // the preview and the result names must still describe what was submitted.
  const [snapshot] = useState(items);
  const commit = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/v1/commits", {
          params: { header: { "idempotency-key": key } },
          body: {
            items: snapshot.map((e) => ({
              candidate_id: e.candidate.candidate_id,
              revision: e.candidate.revision,
            })),
          },
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["candidates", taskId] });
      void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
    },
  });
  const ids = snapshot.map((e) => e.candidate.candidate_id);
  // The server plans each item as the commit will, so reuse and new records are not mixed up.
  const preview = useQuery({
    queryKey: ["commit-preview", ids],
    enabled: !commit.data,
    queryFn: () => unwrap(api.POST("/v1/commits/preview", { body: { candidate_ids: ids } })),
  });
  const planned = preview.data?.items ?? [];
  const count = (action: string) => planned.filter((p) => p.record_action === action).length;
  const undecided = planned.filter(
    (p) =>
      p.record_action === null ||
      p.record_action === "needs_decision" ||
      p.record_action === "cancel",
  ).length;
  const names = new Map(
    snapshot.map((e) => [e.candidate.candidate_id, e.candidate.name?.value ?? "（未命名）"]),
  );
  const results = commit.data?.results ?? [];
  const succeeded = results.filter(
    (r) => r.status === "COMMITTED" || r.status === "ALREADY_COMMITTED",
  ).length;

  return (
    <Modal
      open
      title="提交入库"
      okText={commit.data ? "完成" : "确认提交"}
      cancelText="关闭"
      confirmLoading={commit.isPending}
      onCancel={onClose}
      onOk={() => (commit.data ? onClose() : commit.mutate())}
      width={720}
    >
      {!commit.data && preview.isLoading && <Spin />}
      {!commit.data && preview.error && (
        <Alert type="warning" message={`无法预览：${errorText(preview.error)}`} />
      )}
      {!commit.data && preview.data && (
        <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }}>
          <Descriptions.Item label="新记录">{count("create_record")}</Descriptions.Item>
          <Descriptions.Item label="新版本">{count("new_version")}</Descriptions.Item>
          <Descriptions.Item label="已有记录追加来源">{count("add_provenance")}</Descriptions.Item>
          <Descriptions.Item label="复用已有序列">
            {planned.filter((p) => p.reuses_sequence).length}
          </Descriptions.Item>
          {undecided > 0 && <Descriptions.Item label="将不会入库">{undecided}</Descriptions.Item>}
        </Descriptions>
      )}
      {commit.error && (
        <Alert type="error" message={errorText(commit.error)} style={{ marginTop: 12 }} />
      )}
      {commit.data && (
        <>
          <Alert
            style={{ marginBottom: 12 }}
            type={succeeded === results.length ? "success" : succeeded ? "warning" : "error"}
            message={
              succeeded === results.length
                ? `全部 ${results.length} 条已入库`
                : succeeded
                  ? `部分成功：${succeeded} / ${results.length} 条已入库，其余未入库`
                  : "没有条目入库"
            }
          />
          <Table<CommitResult>
            rowKey="candidate_id"
            size="small"
            pagination={false}
            dataSource={results}
            columns={[
              { title: "名称", render: (_, r) => names.get(r.candidate_id) },
              {
                title: "结果",
                render: (_, r) => (
                  <Tag
                    color={
                      r.status === "COMMITTED" || r.status === "ALREADY_COMMITTED" ? "green" : "red"
                    }
                  >
                    {commitStatus[r.status]}
                  </Tag>
                ),
              },
              {
                title: "原因",
                render: (_, r) => (r.reason ? (commitReason[r.reason] ?? r.reason) : ""),
              },
            ]}
          />
        </>
      )}
    </Modal>
  );
}
