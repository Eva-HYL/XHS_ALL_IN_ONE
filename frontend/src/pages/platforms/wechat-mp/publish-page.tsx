import { CheckCircleOutlined, CloudUploadOutlined, ReloadOutlined, SendOutlined } from "@ant-design/icons";
import { Alert, Button, Card, DatePicker, Empty, Modal, Select, Space, Spin, Tag, Typography } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { cancelWechatMpPublishJob, fetchWechatMpAccounts, fetchWechatMpArticles, pollWechatMpPublishJob, publishWechatMpArticle, syncWechatMpDraft } from "../../../lib/api";
import type { WechatMpArticle, WechatMpDraftSync, WechatMpPublishJob } from "../../../types";
import { WechatMpLayout } from "./wechat-mp-layout";

const { Paragraph, Text } = Typography;

export function WechatMpPublishPage() {
  const [params] = useSearchParams();
  const [articles, setArticles] = useState<WechatMpArticle[]>([]); const [accounts, setAccounts] = useState<{ id: number; name: string }[]>([]);
  const [articleId, setArticleId] = useState<number | undefined>(Number(params.get("article")) || undefined); const [accountId, setAccountId] = useState<number>(); const [scheduledAt, setScheduledAt] = useState<Dayjs | null>(null);
  const [sync, setSync] = useState<WechatMpDraftSync | null>(null); const [job, setJob] = useState<WechatMpPublishJob | null>(null); const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  useEffect(() => { void (async () => { try { const [articleItems, accountItems] = await Promise.all([fetchWechatMpArticles(), fetchWechatMpAccounts()]); setArticles(articleItems); setAccounts(accountItems.map((item) => ({ id: item.id, name: item.name }))); if (!articleId && articleItems[0]) setArticleId(articleItems[0].id); if (accountItems[0]) setAccountId(accountItems[0].id); } catch { setError("发布数据加载失败。"); } finally { setLoading(false); } })(); }, []);
  async function syncDraft() { if (!articleId || !accountId) { setError("请选择文章与账号。"); return; } setBusy(true); setError(null); try { setSync(await syncWechatMpDraft(articleId, accountId)); } catch { setError("草稿同步失败，请先测试账号连接并确认公众号素材可用。"); } finally { setBusy(false); } }
  async function submitPublish(confirm: boolean) { if (!articleId) return; setBusy(true); setError(null); try { const next = await publishWechatMpArticle(articleId, { confirm, scheduled_at: scheduledAt?.toISOString() ?? null }); setJob(next); } catch { setError("发布提交失败。请先完成草稿同步并检查状态。"); } finally { setBusy(false); } }
  function publish() { if (scheduledAt) { void submitPublish(true); return; } Modal.confirm({ title: "确认立即发布？", content: "这会将已同步的草稿提交到微信公众号发布接口，无法自动撤回。", okText: "确认立即发布", cancelText: "取消", okButtonProps: { danger: true }, onOk: () => submitPublish(true) }); }
  async function poll() { if (!job) return; setBusy(true); try { setJob(await pollWechatMpPublishJob(job.id)); } catch { setError("发布状态查询失败。"); } finally { setBusy(false); } }
  async function cancelScheduled() { if (!job) return; setBusy(true); try { setJob(await cancelWechatMpPublishJob(job.id)); } catch { setError("定时发布取消失败。" ); } finally { setBusy(false); } }
  return <WechatMpLayout><PageHeader eyebrow="WeChat MP / Publish" title="草稿同步与发布" description="先同步公众号草稿，再明确选择立即发布或定时发布。立即发布必须二次确认。" />
    {error && <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} style={{ marginBottom: 16 }} />}
    {loading ? <Spin /> : <Card><Space direction="vertical" size={16} style={{ width: "100%" }}><Select placeholder="选择文章" value={articleId} onChange={setArticleId} options={articles.map((article) => ({ value: article.id, label: `${article.title} (${article.status})` }))} /><Select placeholder="选择公众号账号" value={accountId} onChange={setAccountId} options={accounts.map((account) => ({ value: account.id, label: account.name }))} /><DatePicker showTime value={scheduledAt} onChange={setScheduledAt} placeholder="留空即立即发布" style={{ width: "100%" }} /><Button icon={<CloudUploadOutlined />} type="primary" loading={busy} onClick={() => void syncDraft()}>同步到公众号草稿箱</Button></Space></Card>}
    <Card title="草稿同步状态" style={{ marginTop: 16 }}>{sync ? <Space><CheckCircleOutlined style={{ color: "#52c41a" }} /><Text>草稿 #{sync.id}：{sync.status}</Text><Tag>{sync.wechat_media_id}</Tag></Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本次会话尚未同步草稿" />}</Card>
    <Card title="发布" style={{ marginTop: 16 }}><Paragraph>{scheduledAt ? `定时发布：${scheduledAt.format("YYYY-MM-DD HH:mm")}` : "立即发布：点击后将要求明确确认。"}</Paragraph><Button type="primary" danger icon={<SendOutlined />} disabled={!sync || busy} loading={busy} onClick={publish}>{scheduledAt ? "确认定时发布" : "立即发布"}</Button></Card>
    <Card title="发布任务状态" extra={job && <Space><Button icon={<ReloadOutlined />} disabled={!job.publish_id} loading={busy} onClick={() => void poll()}>查询状态</Button>{job.status === "scheduled" && <Button danger loading={busy} onClick={() => void cancelScheduled()}>取消定时发布</Button>}</Space>} style={{ marginTop: 16 }}>{job ? <Space direction="vertical"><Tag color={job.status === "published" ? "green" : "blue"}>{job.status}</Tag><Text>任务 #{job.id}，草稿同步 #{job.draft_sync_id}</Text>{job.error_message && <Text type="danger">{job.error_message}</Text>}</Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本次会话尚无发布任务" />}</Card>
  </WechatMpLayout>;
}
