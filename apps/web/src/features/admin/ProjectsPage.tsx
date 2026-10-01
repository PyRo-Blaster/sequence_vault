import { Card, Table, Tag } from "antd";

import type { Me } from "../../lib/api";

const ROLE_LABELS: Record<string, string> = {
  uploader: "上传",
  reviewer: "审核",
  viewer: "查看",
  project_admin: "项目管理员",
};

export function ProjectsPage({ me }: { me: Me }) {
  return (
    <Card title="我的项目与权限">
      <Table
        rowKey="project_id"
        pagination={false}
        dataSource={me.projects}
        columns={[
          { title: "项目", dataIndex: "name" },
          {
            title: "角色",
            dataIndex: "roles",
            render: (roles: string[]) => roles.map((r) => <Tag key={r}>{ROLE_LABELS[r] ?? r}</Tag>),
          },
        ]}
      />
    </Card>
  );
}
