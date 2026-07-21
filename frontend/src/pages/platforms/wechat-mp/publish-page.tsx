import { CheckCircleOutlined, CloudUploadOutlined, ReloadOutlined, SendOutlined } from "@ant-design/icons";
import { Alert, Button, Card, DatePicker, Empty, Modal, Select, Space, Spin, Tag, Typography } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import {
  cancelWechatMpPublishJob,
  fetchWechatMpAccounts,
  fetchWechatMpArticles,
  fetchWechatMpPublishJobs,
  pollWechatMpPublishJob,
  publishWechatMpArticle,
  syncWechatMpDraft,
} from "../../../lib/api";
import type { WechatMpArticle, WechatMpDraftSync, WechatMpPublishJob } from "../../../types";
import { WechatMpLayout } from "./wechat-mp-layout";

const { Paragraph, Text } = Typography;

export function WechatMpPublishPage() {
  const [params] = useSearchParams();
  const [articles, setArticles] = useState<WechatMpArticle[]>([]);
  const [accounts, setAccounts] = useState<{ id: number; name: string }[]>([]);
  const [articleId, setArticleId] = useState<number | undefined>(Number(params.get("article")) || undefined);
  const [accountId, setAccountId] = useState<number>();
  const [scheduledAt, setScheduledAt] = useState<Dayjs | null>(null);
  const [sync, setSync] = useState<WechatMpDraftSync | null>(null);
  const [jobs, setJobs] = useState<WechatMpPublishJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [articleItems, accountItems] = await Promise.all([
          fetchWechatMpArticles(),
          fetchWechatMpAccounts(),
        ]);
        setArticles(articleItems);
        setAccounts(accountItems.map((item) => ({ id: item.id, name: item.name })));
        if (!articleId && articleItems[0]) setArticleId(articleItems[0].id);
        if (accountItems[0]) setAccountId(accountItems[0].id);
      } catch {
        setError("发布数据加载失败。");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!articleId) {
      setJobs([]);
      return;
    }
    void fetchWechatMpPublishJobs(articleId)
      .then(setJobs)
      .catch(() => setError("发布任务加载失败。"));
  }, [articleId]);

  function upsertJob(next: WechatMpPublishJob) {
    setJobs((items) => [next, ...items.filter((item) => item.id !== next.id)]);
  }

  async function syncDraft() {
    if (!articleId || !accountId) {
      setError("请选择文章与账号。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setSync(await syncWechatMpDraft(articleId, accountId));
    } catch {
      setError("草稿同步失败，请先测试账号连接并确认公众号素材可用。");
    } finally {
      setBusy(false);
    }
  }

  async function submitPublish(confirm: boolean) {
    if (!articleId) return;
    setBusy(true);
    setError(null);
    try {
      upsertJob(await publishWechatMpArticle(articleId, {
        confirm,
        scheduled_at: scheduledAt?.toISOString() ?? null,
      }));
    } catch {
      setError("发布提交失败。请先完成草稿同步并检查是否已有活动发布任务。");
    } finally {
      setBusy(false);
    }
  }

  function publish() {
    if (scheduledAt) {
      void submitPublish(true);
      return;
    }
    Modal.confirm({
      title: "确认立即发布？",
      content: "这会将已同步的草稿提交到微信公众号发布接口，无法自动撤回。",
      okText: "确认立即发布",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: () => submitPublish(true),
    });
  }

  async function poll(jobId: number) {
    setBusy(true);
    try {
      upsertJob(await pollWechatMpPublishJob(jobId));
    } catch {
      setError("发布状态查询失败。");
    } finally {
      setBusy(false);
    }
  }

  async function cancelScheduled(jobId: number) {
    setBusy(true);
    try {
      upsertJob(await cancelWechatMpPublishJob(jobId));
    } catch {
      setError("定时发布取消失败。");
    } finally {
      setBusy(false);
    }
  }

  return <WechatMpLayout>
    <PageHeader eyebrow="WeChat MP / Publish" title="草稿同步与发布" description="先同步公众号草稿，再明确选择立即发布或定时发布。活动任务会在刷新后保留。" />
    {error && <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} style={{ marginBottom: 16 }} />}
    {loading ? <Spin /> : <Card>
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Select
          placeholder="选择文章"
          value={articleId}
          onChange={(value) => { setArticleId(value); setSync(null); }}
          options={articles.map((article) => ({ value: article.id, label: `${article.title} (${article.status})` }))}
        />
        <Select placeholder="选择公众号账号" value={accountId} onChange={setAccountId} options={accounts.map((account) => ({ value: account.id, label: account.name }))} />
        <DatePicker showTime value={scheduledAt} onChange={setScheduledAt} placeholder="留空即立即发布" style={{ width: "100%" }} />
        <Text type="secondary">所选时间按本地时区显示，提交后统一以 UTC 保存。</Text>
        <Text type="secondary">同步草稿预计费用：¥0（仅调用微信 API）</Text>
        <Button icon={<CloudUploadOutlined />} type="primary" loading={busy} onClick={() => void syncDraft()}>同步到公众号草稿箱</Button>
      </Space>
    </Card>}

    <Card title="草稿同步状态" style={{ marginTop: 16 }}>
      {sync ? <Space><CheckCircleOutlined style={{ color: "#52c41a" }} /><Text>草稿 #{sync.id}：{sync.status}</Text><Tag>{sync.wechat_media_id}</Tag></Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本次会话尚未同步草稿；编辑文章后请重新同步" />}
    </Card>

    <Card title="发布" style={{ marginTop: 16 }}>
      <Paragraph>{scheduledAt ? `定时发布：${scheduledAt.format("YYYY-MM-DD HH:mm")}` : "立即发布：点击后将要求明确确认。"}</Paragraph>
      <Paragraph type="secondary">发布预计费用：¥0（仅调用微信 API）</Paragraph>
      <Button type="primary" danger icon={<SendOutlined />} disabled={!sync || busy} loading={busy} onClick={publish}>{scheduledAt ? "确认定时发布" : "立即发布"}</Button>
    </Card>

    <Card title="发布任务" extra={<Button icon={<ReloadOutlined />} disabled={!articleId} loading={busy} onClick={() => articleId && void fetchWechatMpPublishJobs(articleId).then(setJobs)}>刷新任务</Button>} style={{ marginTop: 16 }}>
      {jobs.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该文章暂无发布任务" /> : <Space direction="vertical" size={12} style={{ width: "100%" }}>
        {jobs.map((job) => <Card key={job.id} size="small">
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Space wrap>
              <Tag color={job.status === "published" ? "green" : job.status === "failed" ? "red" : "blue"}>{job.status}</Tag>
              <Text>任务 #{job.id}，草稿同步 #{job.draft_sync_id}</Text>
              {job.scheduled_at && <Text type="secondary">计划：{dayjs(job.scheduled_at).format("YYYY-MM-DD HH:mm")}</Text>}
            </Space>
            <Space wrap>
              {job.publish_id && <Button size="small" icon={<ReloadOutlined />} loading={busy} onClick={() => void poll(job.id)}>查询远端状态</Button>}
              {job.status === "scheduled" && <Button size="small" danger loading={busy} onClick={() => void cancelScheduled(job.id)}>取消定时发布</Button>}
            </Space>
            {job.error_message && <Text type="danger">{job.error_message}</Text>}
          </Space>
        </Card>)}
      </Space>}
    </Card>
  </WechatMpLayout>;
}
