import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Descriptions, Modal, Table, Tag } from "antd";
import { useState } from "react";

import { api, unwrap, type CandidateEnvelope, type CommitResult } from "../../lib/api";
import { commitReason, commitStatus, errorText } from "../../lib/i18n";
import { commitKind } from "./rules";

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
  const commit = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/v1/commits", {
          params: { header: { "idempotency-key": key } },
          body: {
            items: items.map((e) => ({
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
  const kinds = items.map(commitKind);
  const names = new Map(
    items.map((e) => [e.candidate.candidate_id, e.candidate.name?.value ?? "（未命名）"]),
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
      {!commit.data && (
        <Descriptions bordered size="small" column={3}>
          <Descriptions.Item label="新记录">
            {kinds.filter((k) => k === "new_record").length}
          </Descriptions.Item>
          <Descriptions.Item label="新版本">
            {kinds.filter((k) => k === "new_version").length}
          </Descriptions.Item>
          <Descriptions.Item label="复用已有序列">
            {kinds.filter((k) => k === "reuse").length}
          </Descriptions.Item>
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
