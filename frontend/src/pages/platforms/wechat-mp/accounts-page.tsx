import { ApiOutlined, DeleteOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Form, Input, Modal, Popconfirm, Row, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { PageHeader } from "../../../components/layout/app-shell";
import { createWechatMpAccount, deleteWechatMpAccount, fetchWechatMpAccounts, testWechatMpAccount } from "../../../lib/api";
import type { CreateWechatMpAccountPayload, WechatMpAccount } from "../../../types";
import { WechatMpLayout } from "./wechat-mp-layout";

const { Text } = Typography;

export function WechatMpAccountsPage() {
  const [accounts, setAccounts] = useState<WechatMpAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form] = Form.useForm<CreateWechatMpAccountPayload>();
  async function load() { setLoading(true); try { setAccounts(await fetchWechatMpAccounts()); } catch { setError("账号列表加载失败。"); } finally { setLoading(false); } }
  useEffect(() => { void load(); }, []);
  async function submit(values: CreateWechatMpAccountPayload) { try { const account = await createWechatMpAccount(values); setAccounts((items) => [account, ...items]); setOpen(false); form.resetFields(); } catch { setError("账号绑定失败。"); } }
  async function test(id: number) { setTesting(id); setError(null); try { const account = await testWechatMpAccount(id); setAccounts((items) => items.map((item) => item.id === id ? account : item)); } catch { setError("连接测试失败，请核对 AppID 与 AppSecret。"); } finally { setTesting(null); } }
  async function remove(id: number) { setDeleting(id); setError(null); try { await deleteWechatMpAccount(id); setAccounts((items) => items.filter((item) => item.id !== id)); } catch { setError("删除账号失败。若该账号已用于文章、草稿或发布任务，请先保留历史记录。"); } finally { setDeleting(null); } }
  return <WechatMpLayout>
    <PageHeader eyebrow="WeChat MP / Accounts" title="公众号账号" description="凭据仅用于提交和服务端加密存储；本页从不展示 AppSecret。" action={<Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>绑定账号</Button>} />
    {error && <Alert type="error" message={error} closable onClose={() => setError(null)} showIcon style={{ marginBottom: 16 }} />}
    <Card extra={<Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新</Button>}>
      {loading ? <Spin /> : accounts.length === 0 ? <Empty description="尚未绑定公众号账号" /> : <Row gutter={[16, 16]}>{accounts.map((account) => <Col xs={24} md={12} lg={8} key={account.id}><Card size="small" title={account.name} extra={<Tag color={account.connection_status === "connected" ? "green" : "default"}>{account.connection_status}</Tag>}><Space direction="vertical"><Text type="secondary">AppID: {account.app_id}</Text><Text type="secondary">AppSecret: 已加密保存，不可查看</Text><Space wrap><Button icon={<ApiOutlined />} loading={testing === account.id} onClick={() => void test(account.id)}>测试连接</Button><Popconfirm title="删除这个公众号账号？" description="已用于文章、草稿或发布任务的账号不会被删除。" onConfirm={() => void remove(account.id)}><Button danger icon={<DeleteOutlined />} loading={deleting === account.id}>删除账号</Button></Popconfirm></Space></Space></Card></Col>)}</Row>}
    </Card>
    <Modal title="绑定公众号账号" open={open} onCancel={() => setOpen(false)} footer={null} destroyOnHidden><Form form={form} layout="vertical" onFinish={(values) => void submit(values)}><Form.Item name="name" label="账号名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="app_id" label="AppID" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="app_secret" label="AppSecret" rules={[{ required: true }]}><Input.Password autoComplete="new-password" /></Form.Item><Button htmlType="submit" type="primary">安全保存</Button></Form></Modal>
  </WechatMpLayout>;
}
