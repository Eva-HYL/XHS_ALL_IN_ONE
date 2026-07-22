import { EditOutlined, PictureOutlined, SaveOutlined, SendOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Input, Row, Select, Space, Steps, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import {
  createWechatMpArticle,
  fetchModelConfigs,
  fetchWechatMpArticle,
  fetchWechatMpAssets,
  fetchWechatMpImageCostEstimate,
  fetchWechatMpPrompts,
  generateWechatMpCover,
  generateWechatMpImage,
  generateWechatMpPrompts,
  regenerateWechatMpPrompt,
  updateWechatMpArticle,
  updateWechatMpPrompt,
} from "../../../lib/api";
import type {
  ModelConfig,
  WechatMpArticle,
  WechatMpAsset,
  WechatMpImageCostEstimate,
  WechatMpImagePrompt,
} from "../../../types";
import { WechatMpLayout } from "./wechat-mp-layout";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;
const DEFAULT_SKILL = "xiaomao-illustrations";

function errorMessage(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response;
    if (typeof response?.data?.detail === "string") return response.data.detail;
  }
  if (typeof error === "object" && error !== null && "code" in error && (error as { code?: string }).code === "ECONNABORTED") {
    return "请求超时：提示词生成仍可能在后台继续执行，请稍后刷新文章查看结果。";
  }
  return fallback;
}

function activeArticleAssets(
  articleId: number,
  prompts: WechatMpImagePrompt[],
  assets: WechatMpAsset[],
): WechatMpAsset[] {
  const activePromptIds = new Set(prompts.map((prompt) => prompt.id));
  return assets.filter((asset) =>
    asset.article_id === articleId && (asset.role === "cover" || (asset.prompt_id !== null && activePromptIds.has(asset.prompt_id)))
  );
}

export function WechatMpWriterPage() {
  const [params, setParams] = useSearchParams();
  const [article, setArticle] = useState<WechatMpArticle | null>(null);
  const [prompts, setPrompts] = useState<WechatMpImagePrompt[]>([]);
  const [assets, setAssets] = useState<WechatMpAsset[]>([]);
  const [imageModels, setImageModels] = useState<ModelConfig[]>([]);
  const [imageModel, setImageModel] = useState<string | undefined>();
  const [imageEstimate, setImageEstimate] = useState<WechatMpImageCostEstimate | null>(null);
  const [title, setTitle] = useState("");
  const [topic, setTopic] = useState("");
  const [material, setMaterial] = useState("");
  const [reader, setReader] = useState("");
  const [tone, setTone] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [editMarkdown, setEditMarkdown] = useState("");
  const [skill, setSkill] = useState(DEFAULT_SKILL);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const articleId = Number(params.get("article"));

  useEffect(() => {
    void fetchModelConfigs("image")
      .then(({ items }) => {
        setImageModels(items);
        setImageModel(items.find((item) => item.is_default)?.model_name ?? items[0]?.model_name);
      })
      .catch(() => setError("图片模型配置加载失败。"));
  }, []);

  useEffect(() => {
    void fetchWechatMpImageCostEstimate(imageModel)
      .then(setImageEstimate)
      .catch(() => setImageEstimate(null));
  }, [imageModel]);

  useEffect(() => {
    if (!articleId) return;
    let cancelled = false;
    void (async () => {
      try {
        const [loadedArticle, loadedPrompts, loadedAssets] = await Promise.all([
          fetchWechatMpArticle(articleId),
          fetchWechatMpPrompts(articleId),
          fetchWechatMpAssets(),
        ]);
        if (cancelled) return;
        setArticle(loadedArticle);
        setEditTitle(loadedArticle.title);
        setEditMarkdown(loadedArticle.markdown_body);
        setSkill(loadedArticle.illustration_skill);
        setPrompts(loadedPrompts);
        setAssets(activeArticleAssets(articleId, loadedPrompts, loadedAssets.items));
      } catch {
        if (!cancelled) setError("文章或提示词加载失败。");
      }
    })();
    return () => { cancelled = true; };
  }, [articleId]);

  async function createArticle() {
    if (!title.trim() || !topic.trim()) {
      setError("请填写标题和主题。");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice("文章与配图提示词生成中；长文可能需要几分钟，请不要重复点击。");
    try {
      const next = await createWechatMpArticle({
        title: title.trim(),
        topic: topic.trim(),
        source_material: material,
        target_reader: reader,
        tone,
        illustration_skill: skill,
      });
      setArticle(next);
      setEditTitle(next.title);
      setEditMarkdown(next.markdown_body);
      setParams({ article: String(next.id) });
      setPrompts(await generateWechatMpPrompts(next.id, skill));
      setArticle(await fetchWechatMpArticle(next.id));
      setNotice("文章、排版和配图提示词已生成。");
    } catch (err) {
      setError(errorMessage(err, "文章工作流生成失败，请确认文本模型配置。"));
    } finally {
      setBusy(false);
    }
  }

  async function saveArticle() {
    if (!article || !editTitle.trim()) {
      setError("文章标题不能为空。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const previousRevision = article.revision;
      const bodyChanged = editMarkdown !== article.markdown_body;
      const updated = await updateWechatMpArticle(article.id, {
        title: editTitle.trim(),
        markdown_body: editMarkdown,
      });
      setArticle(updated);
      setEditTitle(updated.title);
      setEditMarkdown(updated.markdown_body);
      if (bodyChanged) {
        const [loadedPrompts, loadedAssets] = await Promise.all([
          fetchWechatMpPrompts(article.id),
          fetchWechatMpAssets(),
        ]);
        setPrompts(loadedPrompts);
        setAssets(activeArticleAssets(article.id, loadedPrompts, loadedAssets.items));
      }
      setNotice(updated.revision === previousRevision
        ? "文章内容无变化，现有排版、配图和同步修订已保留。"
        : "文章已保存。已同步的旧草稿会标记为过期，请重新同步后再发布。"
      );
    } catch {
      setError("文章保存失败。");
    } finally {
      setBusy(false);
    }
  }

  async function makePrompts() {
    if (!article) return;
    setBusy(true);
    setError(null);
    setNotice("配图提示词生成中；长文会按段落串行调用模型，可能需要几分钟。");
    try {
      setPrompts(await generateWechatMpPrompts(article.id, skill));
      setArticle(await fetchWechatMpArticle(article.id));
      setNotice("配图提示词已生成。none 模式保留可编辑提示词，但不会嵌入正文或生成正文图片。");
    } catch (err) {
      setError(errorMessage(err, "提示词生成失败。"));
    } finally {
      setBusy(false);
    }
  }

  async function savePrompt(prompt: WechatMpImagePrompt) {
    try {
      const updated = await updateWechatMpPrompt(prompt.article_id, prompt.id, prompt.editable_prompt);
      setPrompts((items) => items.map((item) => item.id === updated.id ? updated : item));
      setArticle(await fetchWechatMpArticle(prompt.article_id));
      setNotice(prompt.skill_name === "none"
        ? "提示词已保存；none 模式不会将提示词或图片嵌入正文。"
        : "提示词已保存；旧配图已从正文预览移除，可重新生成。"
      );
    } catch {
      setError("提示词保存失败。");
    }
  }

  async function regenerate(prompt: WechatMpImagePrompt) {
    setBusy(true);
    setError(null);
    try {
      const updated = await regenerateWechatMpPrompt(prompt.article_id, prompt.id);
      setPrompts((items) => items.map((item) => item.id === updated.id ? updated : item));
      setArticle(await fetchWechatMpArticle(prompt.article_id));
    } catch (err) {
      setError(errorMessage(err, "提示词重新生成失败。"));
    } finally {
      setBusy(false);
    }
  }

  async function generateImage(prompt: WechatMpImagePrompt) {
    setBusy(true);
    try {
      const asset = await generateWechatMpImage(prompt.id, { image_model: imageModel, size: "16:9" });
      setAssets((items) => [asset, ...items]);
      setPrompts((items) => items.map((item) => item.id === prompt.id ? { ...item, status: "generated" } : item));
      setArticle(await fetchWechatMpArticle(prompt.article_id));
      setNotice("公众号正文配图已生成并计入实际费用。");
    } catch {
      setError("图片生成失败，请确认图片模型配置。");
    } finally {
      setBusy(false);
    }
  }

  async function generateCover() {
    if (!article) return;
    setBusy(true);
    try {
      const asset = await generateWechatMpCover(article.id, { image_model: imageModel, size: "16:9" });
      setAssets((items) => [asset, ...items.filter((item) => item.role !== "cover")]);
      setArticle(await fetchWechatMpArticle(article.id));
      setNotice("封面已生成并计入实际费用，现在可以同步公众号草稿。");
    } catch {
      setError("封面生成失败，请确认图片模型配置。");
    } finally {
      setBusy(false);
    }
  }

  const activeStep = !article ? 0 : prompts.length === 0 ? 2 : 4;
  const estimatedCost = imageEstimate?.pricing_available
    ? `预计每张 ¥${imageEstimate.estimated_yuan}`
    : "当前模型暂无价格估算";

  return <WechatMpLayout>
    <PageHeader eyebrow="WeChat MP / Writer" title="文章写作" description="六步完成公众号文章、配图和草稿同步发布。默认插画技能为小猫。" />
    <Steps current={activeStep} size="small" items={["输入主题/素材", "生成文章", "编辑与预览", "生成提示词", "编辑提示词并生图", "同步草稿/发布"].map((stepTitle) => ({ title: stepTitle }))} style={{ marginBottom: 16 }} />
    {error && <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} style={{ marginBottom: 16 }} />}
    {notice && <Alert type="success" message={notice} showIcon closable onClose={() => setNotice(null)} style={{ marginBottom: 16 }} />}

    <Card title="1. 输入主题与素材" style={{ marginBottom: 16 }}>
      <Row gutter={[12, 12]}>
        <Col xs={24} md={12}><Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="文章标题" /></Col>
        <Col xs={24} md={12}><Select value={skill} onChange={setSkill} style={{ width: "100%" }} options={[{ value: DEFAULT_SKILL, label: "小猫插画（xiaomao-illustrations）" }, { value: "none", label: "none（跳过正文配图）" }]} /></Col>
        <Col span={24}><TextArea value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="文章主题与核心观点" rows={2} /></Col>
        <Col xs={24} md={12}><Input value={reader} onChange={(event) => setReader(event.target.value)} placeholder="目标读者（可选）" /></Col>
        <Col xs={24} md={12}><Input value={tone} onChange={(event) => setTone(event.target.value)} placeholder="语气风格（可选）" /></Col>
        <Col span={24}><TextArea value={material} onChange={(event) => setMaterial(event.target.value)} placeholder="参考素材、事实和要点（可选）" rows={4} /></Col>
      </Row>
      <Text type="secondary">正文生成与提示词费用将在模型调用前按已配置价格展示；微信排版本身不收模型费。</Text>
      <Button type="primary" icon={<EditOutlined />} loading={busy} onClick={() => void createArticle()} style={{ marginTop: 12 }}>生成文章</Button>
    </Card>

    {article && <>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="2. 编辑文章" extra={<Space><Tag>修订 {article.revision}</Tag><Tag>{article.status}</Tag></Space>}>
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} placeholder="公众号标题" />
              <TextArea value={editMarkdown} onChange={(event) => setEditMarkdown(event.target.value)} rows={16} placeholder="Markdown 正文" />
              <Button type="primary" icon={<SaveOutlined />} loading={busy} onClick={() => void saveArticle()}>保存标题与正文</Button>
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="3. 微信排版预览">
            <Text strong>{article.title}</Text>
            <Paragraph type="secondary">{article.digest}</Paragraph>
            <Paragraph type="secondary">累计实际模型费用（正文、提示词、封面、配图）：¥{String(article.cost_estimate.total_yuan ?? "0.0000")}，共 {String(article.cost_estimate.calls ?? 0)} 次调用</Paragraph>
            <div style={{ borderTop: "1px solid #eee", paddingTop: 12 }} dangerouslySetInnerHTML={{ __html: article.html_body }} />
          </Card>
        </Col>
      </Row>

      <Card title="4. 生成配图提示词" style={{ marginTop: 16 }}>
        <Paragraph>当前技能：<Text code>{skill}</Text>。<Text code>none</Text> 仍生成可编辑提示词，但不嵌入正文、不生成正文图片；公众号封面仍可生成。</Paragraph>
        <Paragraph type="secondary">提示词预估：所有技能均按文本模型 token 计费；<Text code>none</Text> 仅免去正文图片生成费用。</Paragraph>
        <Button type="primary" icon={<PictureOutlined />} loading={busy} onClick={() => void makePrompts()}>重新生成提示词</Button>
      </Card>

      <Card title="5. 编辑提示词并生成图片" style={{ marginTop: 16 }}>
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Select placeholder="使用后端默认图片模型" allowClear value={imageModel} onChange={setImageModel} options={imageModels.map((model) => ({ value: model.model_name, label: `${model.name}${model.is_default ? "（默认）" : ""}` }))} />
          <Text type="secondary">{estimatedCost}；执行后会写入上方累计实际费用。</Text>
          <Button type="primary" icon={<PictureOutlined />} loading={busy} onClick={() => void generateCover()}>生成 16:9 公众号封面</Button>
          {prompts.length === 0 ? <Empty description="提示词生成后在此编辑；非 none 技能可继续生图" /> : prompts.map((prompt) =>
            <Card key={prompt.id} size="small" title={`段落 #${prompt.section_id}`} extra={<Tag>{prompt.status}</Tag>}>
              <TextArea value={prompt.editable_prompt} onChange={(event) => setPrompts((items) => items.map((item) => item.id === prompt.id ? { ...item, editable_prompt: event.target.value } : item))} rows={3} />
              <Space style={{ marginTop: 8 }} wrap>
                <Button icon={<SaveOutlined />} onClick={() => void savePrompt(prompt)}>保存提示词</Button>
                <Button onClick={() => void regenerate(prompt)} loading={busy}>重新生成</Button>
                <Button type="primary" icon={<PictureOutlined />} disabled={prompt.skill_name === "none"} loading={busy} onClick={() => void generateImage(prompt)}>生成正文图片</Button>
              </Space>
            </Card>
          )}
        </Space>
      </Card>

      {assets.length > 0 && <Card title="生成图片" style={{ marginTop: 16 }}>
        <Space wrap>{assets.map((asset) => <div key={asset.id}><Tag>{asset.role === "cover" ? "封面" : "正文"}</Tag><img src={asset.public_url} alt="公众号配图" style={{ width: 160, height: 90, objectFit: "cover", display: "block", marginTop: 6 }} /></div>)}</Space>
      </Card>}

      <Card title="6. 同步草稿与发布" style={{ marginTop: 16 }}>
        <Paragraph>文章编辑后必须重新同步公众号草稿，再提交发布。</Paragraph>
        <Button icon={<SendOutlined />} href={`/platforms/wechat-mp/publish?article=${article.id}`}>前往发布中心</Button>
      </Card>
    </>}
  </WechatMpLayout>;
}
