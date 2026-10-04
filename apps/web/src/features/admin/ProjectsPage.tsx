import { CloseOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";

import { api, unwrap, type Me, type Schemas } from "../../lib/api";
import { candidateStatus, errorText, failure, taskStatus } from "../../lib/i18n";
import { hasRole, useProject } from "../../lib/session";

const ROLE_LABELS: Record<string, string> = {
  uploader: "上传",
  reviewer: "审核",
  viewer: "查看",
  project_admin: "项目管理员",
};
type Role = Schemas["Member"]["roles"][number];

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

function Members({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const key = ["members", projectId];
  const members = useQuery({
    queryKey: key,
    queryFn: () =>
      unwrap(
        api.GET("/v1/projects/{project_id}/members", {
          params: { path: { project_id: projectId } },
        }),
      ),
  });
  const onDone = {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
    onError: (e: unknown) => message.error(errorText(e)),
  };
  const grant = useMutation({
    mutationFn: (values: { subject: string; role: Role }) =>
      unwrap(
        api.POST("/v1/projects/{project_id}/members", {
          params: { path: { project_id: projectId } },
          body: values,
        }),
      ),
    ...onDone,
  });
  const revoke = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) =>
      unwrap(
        api.DELETE("/v1/projects/{project_id}/members/{user_id}/roles/{role}", {
          params: { path: { project_id: projectId, user_id: userId, role } },
        }),
      ),
    ...onDone,
  });
  return (
    <Card title="成员与角色">
      <Form
        layout="inline"
        onFinish={(values: { subject: string; role: Role }) => grant.mutate(values)}
        style={{ marginBottom: 16 }}
      >
        <Form.Item name="subject" rules={[{ required: true, message: "请输入登录账号" }]}>
          <Input aria-label="登录账号" placeholder="登录账号（如邮箱）" />
        </Form.Item>
        <Form.Item name="role" rules={[{ required: true, message: "请选择角色" }]}>
          <Select
            aria-label="角色"
            style={{ width: 140 }}
            placeholder="角色"
            options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))}
          />
        </Form.Item>
        <Button htmlType="submit" type="primary" loading={grant.isPending}>
          授予角色
        </Button>
      </Form>
      <Table
        rowKey="user_id"
        pagination={false}
        scroll={{ x: "max-content" }}
        loading={members.isLoading}
        dataSource={members.data?.items ?? []}
        columns={[
          { title: "成员", dataIndex: "display_name" },
          { title: "登录账号", dataIndex: "subject" },
          {
            title: "角色",
            render: (_, member: Schemas["Member"]) => (
              <Space wrap>
                {member.roles.map((role) => (
                  <Tag key={role}>
                    {ROLE_LABELS[role]}
                    <Popconfirm
                      title={`撤销 ${member.display_name} 的「${ROLE_LABELS[role]}」角色？`}
                      okText="撤销"
                      okButtonProps={{ danger: true }}
                      cancelText="取消"
                      onConfirm={() => revoke.mutate({ userId: member.user_id, role })}
                    >
                      <Button
                        type="text"
                        size="small"
                        className="sv-tag-action"
                        icon={<CloseOutlined />}
                        aria-label={`撤销${ROLE_LABELS[role]}角色`}
                      />
                    </Popconfirm>
                  </Tag>
                ))}
              </Space>
            ),
          },
        ]}
      />
    </Card>
  );
}

function Quality({ projectId }: { projectId: string }) {
  const quality = useQuery({
    queryKey: ["quality", projectId],
    queryFn: () =>
      unwrap(
        api.GET("/v1/projects/{project_id}/quality", {
          params: { path: { project_id: projectId } },
        }),
      ),
  });
  const q = quality.data;
  const total = (counts: Record<string, number> | undefined) =>
    Object.values(counts ?? {}).reduce((a, b) => a + b, 0);
  return (
    <Card title="质量概览" loading={quality.isLoading}>
      {q && (
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="处理任务" value={total(q.tasks)} />
            </Col>
            <Col span={6}>
              <Statistic title="已入库记录" value={q.records} />
            </Col>
            <Col span={6}>
              <Statistic title="人工修订率" value={percent(q.manual_revision_rate)} />
            </Col>
            <Col span={6}>
              <Statistic title="名称修改率" value={percent(q.rename_rate)} />
            </Col>
          </Row>
          <Space wrap>
            {Object.entries(q.tasks).map(([status, n]) => (
              <Tag key={status}>
                {taskStatus[status] ?? status} {n}
              </Tag>
            ))}
            {Object.entries(q.candidates).map(([status, n]) => (
              <Tag key={status} color="blue">
                候选{candidateStatus[status] ?? status} {n}
              </Tag>
            ))}
            {Object.entries(q.failure_codes).map(([code, n]) => (
              <Tag key={code} color="red">
                {failure[code] ?? code} {n}
              </Tag>
            ))}
          </Space>
          <Table
            rowKey="format"
            size="small"
            pagination={false}
            scroll={{ x: "max-content" }}
            dataSource={q.formats}
            columns={[
              { title: "格式", dataIndex: "format" },
              { title: "任务", dataIndex: "tasks" },
              { title: "失败或不支持", dataIndex: "failed" },
              {
                title: "失败率",
                dataIndex: "failure_rate",
                render: (v: number | null) => percent(v),
              },
            ]}
          />
          <Table
            rowKey={(r) => `${r.parser_version}-${r.model_version}-${r.prompt_version}`}
            size="small"
            pagination={false}
            scroll={{ x: "max-content" }}
            dataSource={q.runs}
            columns={[
              { title: "解析器版本", dataIndex: "parser_version" },
              {
                title: "模型版本",
                dataIndex: "model_version",
                render: (v: string | null) => v ?? "未使用模型",
              },
              {
                title: "提示词版本",
                dataIndex: "prompt_version",
                render: (v: string | null) => v ?? "—",
              },
              { title: "运行次数", dataIndex: "runs" },
            ]}
          />
        </Space>
      )}
    </Card>
  );
}

export function ProjectsPage({ me }: { me: Me }) {
  const { project } = useProject();
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Typography.Title level={1} className="sv-page-title">
        项目管理
      </Typography.Title>
      <Card title="我的项目与权限">
        <Table
          rowKey="project_id"
          pagination={false}
          scroll={{ x: "max-content" }}
          dataSource={me.projects}
          columns={[
            { title: "项目", dataIndex: "name" },
            {
              title: "角色",
              dataIndex: "roles",
              render: (roles: string[]) =>
                roles.map((r) => <Tag key={r}>{ROLE_LABELS[r] ?? r}</Tag>),
            },
          ]}
        />
      </Card>
      {project && (
        <Typography.Title level={2} className="sv-section-title">
          当前项目：{project.name}
        </Typography.Title>
      )}
      {project && hasRole(project, "project_admin", "reviewer") && (
        <Quality projectId={project.project_id} />
      )}
      {project && hasRole(project, "project_admin") && <Members projectId={project.project_id} />}
    </Space>
  );
}
