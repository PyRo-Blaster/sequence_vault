import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Typography,
} from "antd";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap, type Me, type RecordSummary } from "../../lib/api";
import { errorText } from "../../lib/i18n";

interface Filters {
  project_id?: string;
  q?: string;
  sequence?: string;
  min_length?: number;
  max_length?: number;
}

export function RecordsPage({ me }: { me: Me }) {
  const [filters, setFilters] = useState<Filters>({});
  const [cursor, setCursor] = useState<string | undefined>();
  const records = useQuery({
    queryKey: ["records", filters, cursor],
    queryFn: () =>
      unwrap(api.GET("/v1/records", { params: { query: { ...filters, cursor, limit: 50 } } })),
  });
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Typography.Title level={1} className="sv-page-title">
        序列检索
      </Typography.Title>
      <Card title="检索条件">
        <Form
          layout="inline"
          onFinish={(values: Filters) => {
            setCursor(undefined);
            setFilters(
              Object.fromEntries(
                Object.entries(values).filter(([, v]) => v !== undefined && v !== ""),
              ),
            );
          }}
        >
          <Form.Item name="q" label="名称">
            <Input aria-label="名称" allowClear maxLength={200} placeholder="名称或别名片段" />
          </Form.Item>
          <Form.Item name="project_id" label="项目">
            <Select
              aria-label="项目"
              allowClear
              style={{ minWidth: 180 }}
              options={me.projects.map((p) => ({ value: p.project_id, label: p.name }))}
            />
          </Form.Item>
          <Form.Item name="min_length" label="长度">
            <InputNumber min={0} placeholder="最短" />
          </Form.Item>
          <Form.Item name="max_length">
            <InputNumber min={0} placeholder="最长" />
          </Form.Item>
          <Form.Item name="sequence" label="精确序列" className="sv-sequence-filter">
            <Input.TextArea
              aria-label="精确序列"
              rows={1}
              placeholder="粘贴完整序列，忽略空白与大小写"
            />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            检索
          </Button>
        </Form>
      </Card>
      <Card>
        {records.error && (
          <Alert
            type="error"
            showIcon
            message={
              (records.error as { code?: string }).code === "malformed_request"
                ? "检索条件不正确：名称最多 200 个字符，长度须为非负整数。"
                : errorText(records.error)
            }
            style={{ marginBottom: 12 }}
          />
        )}
        <Table<RecordSummary>
          rowKey="record_id"
          loading={records.isLoading}
          dataSource={records.data?.items ?? []}
          pagination={false}
          scroll={{ x: "max-content" }}
          locale={records.error ? { emptyText: "检索失败" } : undefined}
          columns={[
            {
              title: "名称",
              dataIndex: "name",
              render: (name: string, r) => <Link to={`/records/${r.record_id}`}>{name}</Link>,
            },
            { title: "项目", dataIndex: "project" },
            { title: "当前版本", dataIndex: "version_no", render: (v: number) => `v${v}` },
            { title: "长度", dataIndex: "length" },
            {
              title: "更新时间",
              dataIndex: "updated_at",
              render: (v: string) => new Date(v).toLocaleString("zh-CN"),
            },
          ]}
        />
        {records.data?.next_cursor && (
          <Button
            style={{ marginTop: 12 }}
            onClick={() => setCursor(records.data?.next_cursor ?? undefined)}
          >
            下一页
          </Button>
        )}
      </Card>
    </Space>
  );
}
