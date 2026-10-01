import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Descriptions,
  Space,
  Spin,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useParams } from "react-router";

import { SequenceView } from "../../components/SequenceView";
import { api, download, unwrap } from "../../lib/api";
import { errorText } from "../../lib/i18n";

export function RecordDetailPage() {
  const { recordId = "" } = useParams();
  const { message } = App.useApp();
  const record = useQuery({
    queryKey: ["record", recordId],
    queryFn: () =>
      unwrap(api.GET("/v1/records/{record_id}", { params: { path: { record_id: recordId } } })),
  });
  if (record.error) return <Alert type="error" message={errorText(record.error)} />;
  if (!record.data) return <Spin />;
  const data = record.data;
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Typography.Title level={3}>{data.name}</Typography.Title>
      <Timeline
        items={data.versions.map((version) => ({
          color: version.is_current ? "green" : "gray",
          children: (
            <Card
              size="small"
              title={
                <Space>
                  <span>版本 v{version.version_no}</span>
                  {version.is_current ? <Tag color="green">当前</Tag> : <Tag>已被取代</Tag>}
                </Space>
              }
              extra={
                <Button
                  onClick={() =>
                    void download(
                      `/v1/records/${data.record_id}/export?version=${version.version_no}`,
                    ).catch((e) => message.error(errorText(e)))
                  }
                >
                  导出 FASTA
                </Button>
              }
            >
              <Descriptions size="small" column={3}>
                <Descriptions.Item label="长度">{version.length}</Descriptions.Item>
                <Descriptions.Item label="创建人">{version.created_by}</Descriptions.Item>
                <Descriptions.Item label="时间">
                  {new Date(version.created_at).toLocaleString("zh-CN")}
                </Descriptions.Item>
                <Descriptions.Item label="SHA-256" span={3}>
                  <Typography.Text code copyable>
                    {version.sha256}
                  </Typography.Text>
                </Descriptions.Item>
              </Descriptions>
              <SequenceView sequence={version.sequence} />
              <Collapse
                style={{ marginTop: 12 }}
                items={version.provenance.map((p, i) => ({
                  key: i,
                  label: `来源：${p.file_name} · 批准 ${p.approved_by} · 入库 ${p.committed_by}`,
                  children: (
                    <Descriptions size="small" column={2}>
                      <Descriptions.Item label="候选">
                        {p.candidate_id}（修订 {p.candidate_revision}）
                      </Descriptions.Item>
                      <Descriptions.Item label="提取运行">{p.run_id}</Descriptions.Item>
                      <Descriptions.Item label="证据" span={2}>
                        <pre className="sv-mono">{JSON.stringify(p.evidence, null, 2)}</pre>
                      </Descriptions.Item>
                      <Descriptions.Item label="规范化步骤" span={2}>
                        {p.transformation_log.length
                          ? p.transformation_log
                              .map((t) => `${t.rule_id} ${t.operation}（${t.positions.length} 处）`)
                              .join("；")
                          : "无"}
                      </Descriptions.Item>
                    </Descriptions>
                  ),
                }))}
              />
            </Card>
          ),
        }))}
      />
    </Space>
  );
}
