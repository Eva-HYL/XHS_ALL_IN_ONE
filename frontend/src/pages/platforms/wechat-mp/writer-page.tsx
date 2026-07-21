import { EditOutlined, PictureOutlined, SaveOutlined, SendOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Input, Row, Select, Space, Spin, Steps, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { createWechatMpArticle, fetchWechatMpArticle, fetchWechatMpPrompts, generateWechatMpImage, generateWechatMpPrompts, regenerateWechatMpPrompt, updateWechatMpPrompt } from "../../../lib/api";
import type { WechatMpArticle, WechatMpAsset, WechatMpImagePrompt } from "../../../types";
import { WechatMpLayout } from "./wechat-mp-layout";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;
const DEFAULT_SKILL = "xiaomao-illustrations";

export function WechatMpWriterPage() {
  const [params, setParams] = useSearchParams();
  const [article, setArticle] = useState<WechatMpArticle | null>(null);
  const [prompts, setPrompts] = useState<WechatMpImagePrompt[]>([]);
  const [assets, setAssets] = useState<WechatMpAsset[]>([]);
  const [title, setTitle] = useState(""); const [topic, setTopic] = useState(""); const [material, setMaterial] = useState(""); const [reader, setReader] = useState(""); const [tone, setTone] = useState("");
  const [skill, setSkill] = useState(DEFAULT_SKILL); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const articleId = Number(params.get("article"));
  useEffect(() => {
    if (!articleId) return;
    let cancelled = false;
    void (async () => {
      try {
        const [loadedArticle, loadedPrompts] = await Promise.all([fetchWechatMpArticle(articleId), fetchWechatMpPrompts(articleId)]);
        if (cancelled) return;
        setArticle(loadedArticle);
        setSkill(loadedArticle.illustration_skill);
        setPrompts(loadedPrompts);
      } catch {
        if (!cancelled) setError("文章或提示词加载失败。");
      }
    })();
    return () => { cancelled = true; };
  }, [articleId]);
  async function createArticle() { if (!title.trim() || !topic.trim()) { setError("请填写标题和主题。"); return; } setBusy(true); setError(null); try { const next = await createWechatMpArticle({ title: title.trim(), topic: topic.trim(), source_material: material, target_reader: reader, tone, illustration_skill: skill }); setArticle(next); setParams({ article: String(next.id) }); setNotice("文章已生成，可检查排版预览。"); } catch { setError("文章生成失败，请确认文本模型配置。"); } finally { setBusy(false); } }
  async function makePrompts() { if (!article) return; setBusy(true); try { setPrompts(await generateWechatMpPrompts(article.id, skill)); setArticle(await fetchWechatMpArticle(article.id)); setNotice("配图提示词已生成。即使选择 none，提示词也可以继续生成。"); } catch { setError("提示词生成失败。"); } finally { setBusy(false); } }
  async function savePrompt(prompt: WechatMpImagePrompt) { try { const updated = await updateWechatMpPrompt(prompt.article_id, prompt.id, prompt.editable_prompt); setPrompts((items) => items.map((item) => item.id === updated.id ? updated : item)); } catch { setError("提示词保存失败。"); } }
  async function regenerate(prompt: WechatMpImagePrompt) { setBusy(true); try { const updated = await regenerateWechatMpPrompt(prompt.article_id, prompt.id); setPrompts((items) => items.map((item) => item.id === updated.id ? updated : item)); } catch { setError("提示词重新生成失败。"); } finally { setBusy(false); } }
  async function generateImage(prompt: WechatMpImagePrompt) { setBusy(true); try { const asset = await generateWechatMpImage(prompt.id, { image_model: "gpt-image-2", size: "16:9" }); setAssets((items) => [asset, ...items]); setArticle(await fetchWechatMpArticle(prompt.article_id)); setNotice("公众号配图已生成并回填预览。"); } catch { setError("图片生成失败，请确认图片模型配置。"); } finally { setBusy(false); } }
  const activeStep = !article ? 0 : prompts.length === 0 ? 2 : 4;
  return <WechatMpLayout>
    <PageHeader eyebrow="WeChat MP / Writer" title="文章写作" description="六步完成公众号文章、配图和草稿同步发布。默认插画技能为小猫。" />
    <Steps current={activeStep} size="small" items={["输入主题/素材", "生成文章", "排版预览", "生成提示词", "编辑提示词并生图", "同步草稿/发布"].map((title) => ({ title }))} style={{ marginBottom: 16 }} />
    {error && <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} style={{ marginBottom: 16 }} />}{notice && <Alert type="success" message={notice} showIcon closable onClose={() => setNotice(null)} style={{ marginBottom: 16 }} />}
    <Card title="1. 输入主题与素材" style={{ marginBottom: 16 }}><Row gutter={[12, 12]}><Col xs={24} md={12}><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="文章标题" /></Col><Col xs={24} md={12}><Select value={skill} onChange={setSkill} style={{ width: "100%" }} options={[{ value: DEFAULT_SKILL, label: "小猫插画（xiaomao-illustrations）" }, { value: "none", label: "none（仅生成提示词）" }]} /></Col><Col span={24}><TextArea value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="文章主题与核心观点" rows={2} /></Col><Col xs={24} md={12}><Input value={reader} onChange={(e) => setReader(e.target.value)} placeholder="目标读者（可选）" /></Col><Col xs={24} md={12}><Input value={tone} onChange={(e) => setTone(e.target.value)} placeholder="语气风格（可选）" /></Col><Col span={24}><TextArea value={material} onChange={(e) => setMaterial(e.target.value)} placeholder="参考素材、事实和要点（可选）" rows={4} /></Col></Row><Button type="primary" icon={<EditOutlined />} loading={busy} onClick={() => void createArticle()} style={{ marginTop: 12 }}>生成文章</Button></Card>
    {article && <><Row gutter={[16, 16]}><Col xs={24} lg={12}><Card title="2-3. 格式化预览" extra={<Tag>{article.status}</Tag>}><Text strong>{article.title}</Text><Paragraph type="secondary">{article.digest}</Paragraph><div style={{ borderTop: "1px solid #eee", paddingTop: 12 }} dangerouslySetInnerHTML={{ __html: article.html_body }} /></Card></Col><Col xs={24} lg={12}><Card title="4. 生成配图提示词"><Paragraph>当前技能：<Text code>{skill}</Text>。选择 <Text code>none</Text> 时仅禁用图片生成，不会禁用提示词生成。</Paragraph><Button type="primary" icon={<PictureOutlined />} loading={busy} onClick={() => void makePrompts()}>生成提示词</Button></Card></Col></Row>
      <Card title="5. 编辑提示词并生成图片" style={{ marginTop: 16 }}>{prompts.length === 0 ? <Empty description="生成提示词后在此编辑并生图" /> : <Space direction="vertical" size={12} style={{ width: "100%" }}>{prompts.map((prompt) => <Card key={prompt.id} size="small" title={`段落 #${prompt.section_id}`} extra={<Tag>{prompt.status}</Tag>}><TextArea value={prompt.editable_prompt} onChange={(e) => setPrompts((items) => items.map((item) => item.id === prompt.id ? { ...item, editable_prompt: e.target.value } : item))} rows={3} /><Space style={{ marginTop: 8 }}><Button icon={<SaveOutlined />} onClick={() => void savePrompt(prompt)}>保存提示词</Button><Button onClick={() => void regenerate(prompt)} loading={busy}>重新生成</Button><Button type="primary" icon={<PictureOutlined />} disabled={skill === "none"} loading={busy} onClick={() => void generateImage(prompt)}>生成图片</Button></Space></Card>)}</Space>}</Card>
      {assets.length > 0 && <Card title="生成图片" style={{ marginTop: 16 }}><Space wrap>{assets.map((asset) => <img key={asset.id} src={asset.public_url} alt="公众号配图" style={{ width: 160, height: 90, objectFit: "cover" }} />)}</Space></Card>}
      <Card title="6. 同步草稿与发布" style={{ marginTop: 16 }}><Paragraph>草稿同步和发布操作在发布中心执行。</Paragraph><Button icon={<SendOutlined />} href={`/platforms/wechat-mp/publish?article=${article.id}`}>前往发布中心</Button></Card>
    </>}
  </WechatMpLayout>;
}
