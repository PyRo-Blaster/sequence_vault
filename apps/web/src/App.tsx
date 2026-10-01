import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Input,
  Layout,
  Menu,
  Result,
  Select,
  Space,
  Spin,
  Typography,
} from "antd";
import { useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router";

import { ProjectsPage } from "./features/admin/ProjectsPage";
import { RecordDetailPage } from "./features/records/RecordDetailPage";
import { RecordsPage } from "./features/records/RecordsPage";
import { ReviewPage } from "./features/review/ReviewPage";
import { UploadsPage } from "./features/uploads/UploadsPage";
import { setDevUser, type Me } from "./lib/api";
import { errorText } from "./lib/i18n";
import { ProjectProvider, useHealth, useMe, useProject } from "./lib/session";

const DEV_USERS = [
  "alice@example.test",
  "bob@example.test",
  "victor@example.test",
  "admin@example.test",
];

function DevLogin() {
  const queryClient = useQueryClient();
  const [subject, setSubject] = useState("");
  const signIn = (value: string) => {
    setDevUser(value);
    void queryClient.invalidateQueries({ queryKey: ["me"] });
  };
  return (
    <Card title="开发环境登录" style={{ maxWidth: 480, margin: "64px auto" }}>
      <Typography.Paragraph type="secondary">
        生产环境由统一身份认证代理登录。此处仅用于开发与测试。
      </Typography.Paragraph>
      <Space direction="vertical" style={{ width: "100%" }}>
        {DEV_USERS.map((user) => (
          <Button key={user} block onClick={() => signIn(user)}>
            {user}
          </Button>
        ))}
        <Space.Compact style={{ width: "100%" }}>
          <Input
            aria-label="账号"
            placeholder="其他账号"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          />
          <Button type="primary" disabled={!subject.trim()} onClick={() => signIn(subject.trim())}>
            登录
          </Button>
        </Space.Compact>
      </Space>
    </Card>
  );
}

function Shell({ me }: { me: Me }) {
  const { project, setProjectId } = useProject();
  const location = useLocation();
  const queryClient = useQueryClient();
  const health = useHealth();
  const section = location.pathname.split("/")[1] || "tasks";
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Header className="sv-header">
        <Typography.Text className="sv-brand">序列库</Typography.Text>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[section === "review" ? "tasks" : section]}
          style={{ flex: 1, minWidth: 0 }}
          items={[
            { key: "tasks", label: <Link to="/tasks">上传与任务</Link> },
            { key: "records", label: <Link to="/records">序列检索</Link> },
            { key: "projects", label: <Link to="/projects">项目与权限</Link> },
          ]}
        />
        <Space>
          <Select
            aria-label="当前项目"
            value={project?.project_id}
            style={{ minWidth: 200 }}
            onChange={setProjectId}
            options={me.projects.map((p) => ({ value: p.project_id, label: p.name }))}
          />
          <Typography.Text style={{ color: "#fff" }}>{me.display_name}</Typography.Text>
          {health.data?.dev_login && (
            <Button
              size="small"
              onClick={() => {
                setDevUser(null);
                queryClient.clear();
              }}
            >
              切换账号
            </Button>
          )}
        </Space>
      </Layout.Header>
      <Layout.Content className="sv-content">
        {!project ? (
          <Result
            status="info"
            title="您还没有加入任何项目"
            subTitle="请联系项目管理员为您分配角色。"
          />
        ) : (
          <Routes>
            <Route path="/tasks" element={<UploadsPage me={me} />} />
            <Route path="/review/:taskId" element={<ReviewPage />} />
            <Route path="/records" element={<RecordsPage me={me} />} />
            <Route path="/records/:recordId" element={<RecordDetailPage />} />
            <Route path="/projects" element={<ProjectsPage me={me} />} />
            <Route path="*" element={<Navigate to="/tasks" replace />} />
          </Routes>
        )}
      </Layout.Content>
    </Layout>
  );
}

export function App() {
  const me = useMe();
  const health = useHealth();
  if (me.isLoading || health.isLoading) return <Spin fullscreen />;
  if (me.error) {
    if (me.error.status === 401 && health.data?.dev_login) return <DevLogin />;
    return <Alert type="error" showIcon message={errorText(me.error)} style={{ margin: 48 }} />;
  }
  return (
    <ProjectProvider projects={me.data!.projects}>
      <Shell me={me.data!} />
    </ProjectProvider>
  );
}
