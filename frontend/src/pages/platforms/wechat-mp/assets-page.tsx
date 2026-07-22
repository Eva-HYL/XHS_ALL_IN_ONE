import { DeleteOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Image, List, Popconfirm, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { PageHeader } from "../../../components/layout/app-shell";
import { deleteWechatMpAsset, fetchWechatMpAssets } from "../../../lib/api";
import type { WechatMpAsset } from "../../../types";
import { WechatMpLayout } from "./wechat-mp-layout";

const { Text } = Typography;
export function WechatMpAssetsPage() { const [assets, setAssets] = useState<WechatMpAsset[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); async function load() { setLoading(true); try { setAssets((await fetchWechatMpAssets()).items); } catch { setError("公众号素材加载失败。"); } finally { setLoading(false); } } useEffect(() => { void load(); }, []); async function remove(id: number) { try { await deleteWechatMpAsset(id); setAssets((items) => items.filter((item) => item.id !== id)); } catch { setError("素材删除失败。"); } }
  return <WechatMpLayout><PageHeader eyebrow="WeChat MP / Assets" title="公众号素材" description="仅显示 wechat_mp_assets 中属于当前用户的配图，不混入小红书图片资产。" action={<Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button>} />{error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}<Card>{loading ? <Spin /> : assets.length === 0 ? <Empty description="暂无公众号素材" /> : <List grid={{ gutter: 16, xs: 1, sm: 2, md: 3, lg: 4 }} dataSource={assets} renderItem={(asset) => <List.Item><Card cover={<Image src={asset.public_url} width="100%" height={150} style={{ objectFit: "cover", display: "block" }} preview />} actions={[<Popconfirm key="delete" title="删除此公众号素材？" onConfirm={() => void remove(asset.id)}><DeleteOutlined /></Popconfirm>]}><Text ellipsis style={{ display: "block" }}>{asset.prompt}</Text><Tag style={{ marginTop: 8 }}>{asset.status}</Tag></Card></List.Item>} />}</Card></WechatMpLayout>; }
