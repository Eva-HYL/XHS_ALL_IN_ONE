import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useState } from "react";

import { PageHeader } from "../../components/layout/app-shell";
import { IllustrationQuotaCard } from "../../components/illustrations/illustration-quota-card";
import {
  fetchIllustrationModelQuotas,
  fetchIllustrationUsageSummary,
  fetchVolcArkInferenceUsage,
} from "../../lib/api";
import type {
  IllustrationModelQuota,
  IllustrationUsageSummary,
  VolcArkInferenceUsage,
} from "../../types";

const { Text } = Typography;

type UsageRow = IllustrationUsageSummary["items"][number] & {
  key: string;
};

function yuan(value: string | number): number {
  return Number(value || 0);
}

function stepLabel(step: string): string {
  if (step === "crack_and_shotlist") return "拆文";
  if (step === "generate_image") return "生图";
  return step;
}

export function BillingCenterPage() {
  const [usage, setUsage] = useState<IllustrationUsageSummary>();
  const [quotas, setQuotas] = useState<IllustrationModelQuota[]>([]);
  const [providerUsage, setProviderUsage] = useState<VolcArkInferenceUsage>();
  const [providerError, setProviderError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  async function loadBilling() {
    setLoading(true);
    setError(undefined);
    try {
      const [usageResult, quotaResult] = await Promise.all([
        fetchIllustrationUsageSummary(),
        fetchIllustrationModelQuotas(),
      ]);
      setUsage(usageResult);
      setQuotas(quotaResult.items);
      try {
        setProviderUsage(await fetchVolcArkInferenceUsage());
        setProviderError(undefined);
      } catch {
        setProviderUsage(undefined);
        setProviderError("火山方舟官方用量暂不可同步。请检查服务端 AK/SK 与权限。");
      }
    } catch {
      setError("账单中心加载失败。");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadBilling();
  }, []);

  const items = usage?.items ?? [];
  const textCost = items
    .filter((item) => item.input_tokens != null || item.output_tokens != null)
    .reduce((sum, item) => sum + yuan(item.cost_yuan), 0);
  const imageCost = items
    .filter((item) => item.image_count != null)
    .reduce((sum, item) => sum + yuan(item.cost_yuan), 0);
  const textTokens = items.reduce((sum, item) => sum + (item.input_tokens ?? 0) + (item.output_tokens ?? 0), 0);
  const imageCount = items.reduce((sum, item) => sum + (item.image_count ?? 0), 0);
  const rows: UsageRow[] = items.map((item, index) => ({ ...item, key: `${item.model}-${item.step}-${index}` })).reverse();

  const columns: ColumnsType<UsageRow> = [
    {
      title: "环节",
      dataIndex: "step",
      render: (value: string) => <Tag color={value === "crack_and_shotlist" ? "blue" : "orange"}>{stepLabel(value)}</Tag>,
    },
    {
      title: "模型",
      dataIndex: "model",
      render: (value: string) => <Text strong>{value}</Text>,
    },
    {
      title: "用量",
      render: (_, row) => row.image_count != null
        ? `${row.image_count} 张`
        : `${(row.input_tokens ?? 0) + (row.output_tokens ?? 0)} tokens`,
    },
    {
      title: "估算费用",
      dataIndex: "cost_yuan",
      align: "right",
      render: (value: string) => `¥${Number(value).toFixed(4)}`,
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Billing Center"
        title="账单中心"
        description="汇总平台记录的费用，并同步火山方舟账户级官方推理用量。"
      />

      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError(undefined)} style={{ marginBottom: 16 }} />}

      {loading ? (
        <div style={{ padding: 48, textAlign: "center" }}><Spin tip="正在加载账单..." /></div>
      ) : (
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Row gutter={[16, 16]}>
            <Col xs={24} md={6}>
              <Card>
                <Statistic title="累计估算费用" value={yuan(usage?.total_cost_yuan ?? "0")} precision={4} prefix="¥" />
              </Card>
            </Col>
            <Col xs={24} md={6}>
              <Card>
                <Statistic title="拆文费用" value={textCost} precision={4} prefix="¥" />
              </Card>
            </Col>
            <Col xs={24} md={6}>
              <Card>
                <Statistic title="生图费用" value={imageCost} precision={4} prefix="¥" />
              </Card>
            </Col>
            <Col xs={24} md={6}>
              <Card>
                <Statistic title="总用量" value={`${textTokens.toLocaleString()} tokens / ${imageCount} 张`} />
              </Card>
            </Col>
          </Row>

          <Card
            title="火山方舟官方用量统计"
            extra={<Button onClick={() => void loadBilling()} loading={loading}>刷新官方用量</Button>}
          >
            {providerError ? (
              <Alert type="warning" showIcon message={providerError} />
            ) : providerUsage ? (
              <>
                <Row gutter={[16, 16]}>
                  <Col xs={24} md={6}><Statistic title="输入 Tokens" value={providerUsage.totals.input_tokens} /></Col>
                  <Col xs={24} md={6}><Statistic title="输出 Tokens" value={providerUsage.totals.output_tokens} /></Col>
                  <Col xs={24} md={6}><Statistic title="图片生成" value={providerUsage.totals.image_count} suffix="张" /></Col>
                  <Col xs={24} md={6}><Statistic title="请求数" value={providerUsage.totals.request_count} /></Col>
                </Row>
                <Alert
                  type="info"
                  showIcon
                  message={`已同步近 ${providerUsage.interval_days} 天的火山方舟账户级用量。火山公开接口当前不提供逐模型免费额度余额。`}
                  style={{ marginTop: 16 }}
                />
              </>
            ) : <Spin tip="正在同步火山方舟官方用量..." />}
          </Card>

          <IllustrationQuotaCard quotas={quotas} />

          <Card title="用量明细">
            {rows.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无用量记录。" />
            ) : (
              <Table
                size="small"
                columns={columns}
                dataSource={rows}
                pagination={{ pageSize: 20 }}
              />
            )}
          </Card>

          <Alert
            type="info"
            showIcon
            message="账单中心当前展示平台记录的估算费用，实际扣费仍以模型服务商控制台为准。"
          />
        </Space>
      )}
    </div>
  );
}
