import { FileTextOutlined, PictureOutlined, TeamOutlined } from "@ant-design/icons";
import { Alert, Card, Col, Empty, List, Row, Spin, Statistic, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { PageHeader } from "../../../components/layout/app-shell";
import { fetchWechatMpAccounts, fetchWechatMpArticles, fetchWechatMpAssets } from "../../../lib/api";
import type { WechatMpArticle } from "../../../types";
import { WechatMpLayout } from "./wechat-mp-layout";

const { Text } = Typography;

export function WechatMpDashboardPage() {
  const [articles, setArticles] = useState<WechatMpArticle[]>([]);
  const [counts, setCounts] = useState({ accounts: 0, assets: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [accountItems, articleItems, assetItems] = await Promise.all([fetchWechatMpAccounts(), fetchWechatMpArticles(), fetchWechatMpAssets()]);
        setArticles(articleItems);
        setCounts({ accounts: accountItems.length, assets: assetItems.total });
      } catch {
        setError("公众号数据加载失败。");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return <WechatMpLayout>
    <PageHeader eyebrow="WeChat MP" title="公众号工作台" description="从内容创作、配图到草稿同步与发布的一条独立流程。" />
    {error && <Alert type="error" message={error} showIcon />}
    {loading ? <Spin /> : <>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}><Card><Statistic title="本地文章" value={articles.length} prefix={<FileTextOutlined />} /></Card></Col>
        <Col xs={24} md={8}><Card><Statistic title="已绑定账号" value={counts.accounts} prefix={<TeamOutlined />} /></Card></Col>
        <Col xs={24} md={8}><Card><Statistic title="公众号素材" value={counts.assets} prefix={<PictureOutlined />} /></Card></Col>
      </Row>
      <Card title="最近文章" style={{ marginTop: 16 }}>
        {articles.length === 0 ? <Empty description="还没有公众号文章" /> : <List dataSource={articles.slice(0, 6)} renderItem={(article) => <List.Item><List.Item.Meta title={article.title} description={<Text type="secondary">{article.digest || "暂无摘要"}</Text>} /><Tag>{article.status}</Tag></List.Item>} />}
      </Card>
    </>}
  </WechatMpLayout>;
}
