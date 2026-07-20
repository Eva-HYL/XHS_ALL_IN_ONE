import { Card, Col, Row, Space, Tag, Typography, Alert } from "antd";

import { useAuth } from "../../hooks/use-auth";
import { canViewInternalBilling } from "../../lib/billing";
import type { IllustrationModelQuota } from "../../types";

const { Text } = Typography;

type IllustrationQuotaCardProps = {
  quotas: IllustrationModelQuota[];
};

export function IllustrationQuotaCard({ quotas }: IllustrationQuotaCardProps) {
  const auth = useAuth();
  if (!quotas.length || !canViewInternalBilling(auth.user)) return null;

  return (
    <Card className="illustration-quota-card" size="small" title="免费额度监控与自动切换" style={{ marginTop: 16 }}>
      <Row gutter={[12, 12]}>
        {quotas.map((quota) => (
          <Col xs={24} md={12} xl={8} key={quota.model_config_id}>
            <Space direction="vertical" size={2} style={{ width: "100%" }}>
              <Space wrap>
                <Text strong>{quota.model}</Text>
                <Tag color={quota.model_type === "text" ? "blue" : "orange"}>{quota.model_type === "text" ? "拆文" : "生图"}</Tag>
                {quota.is_default && <Tag>默认</Tag>}
              </Space>
              <Text type={quota.free_remaining > 0 ? undefined : "secondary"}>
                免费剩余 {quota.free_remaining.toLocaleString()} / {quota.free_ceiling.toLocaleString()} {quota.model_type === "text" ? "tokens" : "张"}
              </Text>
              <Text type="secondary">用尽后按优先级自动切换 · 标价 ¥{quota.unit_price_yuan}</Text>
            </Space>
          </Col>
        ))}
      </Row>
      <Alert type="info" showIcon message="这里统计本平台已记录用量；最终账单以模型服务商控制台为准。" style={{ marginTop: 12 }} />
    </Card>
  );
}
