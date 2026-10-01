import { Checkbox, Form, Input, InputNumber, Modal, Space, Tabs, Typography } from "antd";
import { useState } from "react";

import { CharDiff } from "../../components/CharDiff";
import { api, unwrap, type CandidateEnvelope } from "../../lib/api";
import { useCandidateAction } from "./actions";
import { previewNormalize } from "./rules";

type Span = CandidateEnvelope["candidate"]["sequence_spans"][number];

/** Change evidence ranges or type a corrected sequence; both need a reason (design 6, 7). */
export function SequenceEditor({
  envelope,
  taskId,
  onClose,
}: {
  envelope: CandidateEnvelope;
  taskId: string;
  onClose: () => void;
}) {
  const { candidate } = envelope;
  const [mode, setMode] = useState(candidate.sequence_spans.length ? "spans" : "typed");
  const [typed, setTyped] = useState(candidate.normalized_sequence);
  const [spans, setSpans] = useState<Span[]>(candidate.sequence_spans);
  const [reason, setReason] = useState("");
  const [fragment, setFragment] = useState(candidate.completeness === "fragment");
  const save = useCandidateAction(taskId, () =>
    unwrap(
      api.PATCH("/v1/candidates/{candidate_id}", {
        params: {
          path: { candidate_id: candidate.candidate_id },
          header: { "if-match": `"${candidate.revision}"` },
        },
        body: {
          sequence:
            mode === "typed"
              ? { typed_sequence: typed, reason, fragment }
              : { spans, reason, fragment },
        },
      }),
    ),
  );

  return (
    <Modal
      open
      title="修改序列"
      okText="保存并重新质控"
      cancelText="取消"
      width={760}
      okButtonProps={{ disabled: !reason.trim() }}
      confirmLoading={save.isPending}
      onCancel={onClose}
      onOk={() => save.mutate(undefined, { onSuccess: onClose })}
    >
      <Tabs
        activeKey={mode}
        onChange={setMode}
        items={[
          {
            key: "spans",
            label: "调整证据范围",
            disabled: !candidate.sequence_spans.length,
            children: (
              <Space direction="vertical">
                <Typography.Text type="secondary">
                  按 Unicode 码点计，起点含、终点不含。只能引用原文中可见的字符。
                </Typography.Text>
                {spans.map((span, i) => (
                  <Space key={i}>
                    <span>
                      块 {span.block_id} · 顺序 {span.order}
                    </span>
                    <InputNumber
                      aria-label="起点"
                      min={0}
                      value={span.start}
                      onChange={(v) =>
                        setSpans(spans.map((s, j) => (j === i ? { ...s, start: v ?? 0 } : s)))
                      }
                    />
                    <InputNumber
                      aria-label="终点"
                      min={0}
                      value={span.end}
                      onChange={(v) =>
                        setSpans(spans.map((s, j) => (j === i ? { ...s, end: v ?? 0 } : s)))
                      }
                    />
                  </Space>
                ))}
              </Space>
            ),
          },
          {
            key: "typed",
            label: "手工修订序列",
            children: (
              <Space direction="vertical" style={{ width: "100%" }}>
                <Input.TextArea
                  aria-label="序列"
                  rows={6}
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  className="sv-mono"
                />
                <Typography.Text type="secondary">字符级差异：</Typography.Text>
                <CharDiff before={candidate.normalized_sequence} after={previewNormalize(typed)} />
              </Space>
            ),
          },
        ]}
      />
      <Form layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item label="修改原因（必填）" required>
          <Input
            aria-label="修改原因"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="例如：原文第 3 行混入了页眉"
          />
        </Form.Item>
        <Checkbox checked={fragment} onChange={(e) => setFragment(e.target.checked)}>
          登记为片段（只保留原文中实际可见的连续序列，不补全缺失部分）
        </Checkbox>
      </Form>
    </Modal>
  );
}
