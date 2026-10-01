import { InboxOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Space, Table, Tag, Typography, Upload } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";
import { Link } from "react-router";

import { TaskStatusTag } from "../../components/StatusTag";
import { api, unwrap, type Me, type Task } from "../../lib/api";
import { errorText, failure } from "../../lib/i18n";
import { hasRole, useProject } from "../../lib/session";
import { uploadFile, type UploadOutcome } from "./upload";

const ACTIVE = new Set(["UPLOADED", "SCANNING", "PARSING", "EXTRACTING", "VALIDATING"]);
const SETTLED = new Set(["COMMITTED", "REJECTED", "ARCHIVED"]);

function counts(task: Task): { committed: number; unresolved: number; total: number } {
  const entries = Object.entries(task.candidate_counts);
  const total = entries.reduce((sum, [, n]) => sum + n, 0);
  const committed = task.candidate_counts.COMMITTED ?? 0;
  const unresolved = entries
    .filter(([s]) => !SETTLED.has(s) && s !== "SUPERSEDED")
    .reduce((sum, [, n]) => sum + n, 0);
  return { committed, unresolved, total };
}

export function UploadsPage({ me }: { me: Me }) {
  const { project } = useProject();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const [outcomes, setOutcomes] = useState<UploadOutcome[]>([]);
  const [busy, setBusy] = useState(false);
  const projectId = project?.project_id ?? "";

  const tasks = useQuery({
    queryKey: ["tasks", projectId],
    enabled: !!projectId,
    queryFn: () =>
      unwrap(api.GET("/v1/jobs", { params: { query: { project_id: projectId, limit: 100 } } })),
    refetchInterval: (query) =>
      query.state.data?.items.some((t) => ACTIVE.has(t.status)) ? 1500 : false,
  });

  const action = useMutation({
    mutationFn: async ({ task, kind }: { task: Task; kind: "cancel" | "reprocess" }) =>
      kind === "cancel"
        ? unwrap(
            api.POST("/v1/jobs/{task_id}/cancel", { params: { path: { task_id: task.task_id } } }),
          )
        : unwrap(
            api.POST("/v1/jobs/{task_id}/reprocess", {
              params: { path: { task_id: task.task_id } },
            }),
          ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }),
    onError: (error) => message.error(errorText(error)),
  });

  async function start(files: File[]) {
    const limit = me.limits.max_files_per_batch;
    if (files.length > limit) {
      message.error(`每批最多 ${limit} 个文件`);
      return;
    }
    setBusy(true);
    const results: UploadOutcome[] = [];
    for (const file of files) {
      results.push(await uploadFile(file, projectId));
      setOutcomes([...results]);
    }
    setBusy(false);
    await queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
  }

  const canUpload = hasRole(project, "uploader", "reviewer");
  const columns: ColumnsType<Task> = [
    {
      title: "文件",
      dataIndex: "file_name",
      render: (name: string, task) => (
        <Typography.Text title={task.file_id}>{name}</Typography.Text>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      render: (status: string) => <TaskStatusTag status={status} />,
    },
    {
      title: "候选",
      render: (_, task) => {
        const c = counts(task);
        return c.total ? (
          <Space size={4}>
            <Tag color="green">已入库 {c.committed}</Tag>
            <Tag color={c.unresolved ? "gold" : "default"}>未完成 {c.unresolved}</Tag>
          </Space>
        ) : (
          "—"
        );
      },
    },
    {
      title: "原因",
      dataIndex: "failure_code",
      render: (code: string | null, task) =>
        code
          ? (failure[code] ?? code)
          : task.status === "UNSUPPORTED"
            ? `检测到的类型：${task.detected_type ?? "未知"}`
            : "",
    },
    {
      title: "时间",
      dataIndex: "created_at",
      render: (value: string) => new Date(value).toLocaleString("zh-CN"),
    },
    {
      title: "操作",
      render: (_, task) => (
        <Space>
          {(task.status === "REVIEW_READY" || task.status === "COMPLETED") && (
            <Link to={`/review/${task.task_id}`}>审核</Link>
          )}
          {canUpload && (ACTIVE.has(task.status) || task.status === "REVIEW_READY") && (
            <Button size="small" onClick={() => action.mutate({ task, kind: "cancel" })}>
              取消
            </Button>
          )}
          {canUpload &&
            ["REVIEW_READY", "COMPLETED", "FAILED"].includes(task.status) &&
            task.security_status === "clean" && (
              <Button size="small" onClick={() => action.mutate({ task, kind: "reprocess" })}>
                重新提取
              </Button>
            )}
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      {canUpload ? (
        <Card title="上传序列文件">
          <Typography.Paragraph type="secondary">
            支持格式：{me.accepted_extensions.join("、")}。单个文件不超过{" "}
            {(me.limits.max_file_bytes / 1_000_000).toFixed(0)} MB，每批最多{" "}
            {me.limits.max_files_per_batch} 个文件。系统按内容识别格式，不只看扩展名。
          </Typography.Paragraph>
          <Upload.Dragger
            multiple
            disabled={busy}
            showUploadList={false}
            accept={me.accepted_extensions.join(",")}
            beforeUpload={(_file, fileList) => {
              if (_file === fileList[0]) void start(fileList as unknown as File[]);
              return false;
            }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">拖入文件或点击选择</p>
          </Upload.Dragger>
          {outcomes.length > 0 && (
            <ul className="sv-upload-results">
              {outcomes.map((o) => (
                <li key={o.name}>
                  {o.name}：
                  {o.error ? (
                    <Typography.Text type="danger">{errorText(o.error)}</Typography.Text>
                  ) : (
                    <Typography.Text type="success">已提交处理</Typography.Text>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : (
        <Alert type="info" message="您在此项目中没有上传权限，可查看任务与记录。" />
      )}
      <Card title="处理任务">
        <Table
          rowKey="task_id"
          loading={tasks.isLoading}
          dataSource={tasks.data?.items ?? []}
          columns={columns}
          pagination={false}
        />
      </Card>
    </Space>
  );
}
