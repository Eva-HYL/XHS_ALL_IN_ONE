import { CloudSyncOutlined, CopyOutlined, DeleteOutlined, DownloadOutlined, EditOutlined, PlusOutlined, ReloadOutlined, UploadOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Image,
  Input,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import { useEffect, useState } from "react";

import { PageHeader } from "../../../components/layout/app-shell";
import {
  createWechatMpMaterial,
  deleteWechatMpAsset,
  deleteWechatMpMaterial,
  downloadExportFile,
  fetchWechatMpAssets,
  fetchWechatMpMaterials,
  parseWechatMpMaterialFeishu,
  updateWechatMpMaterial,
  uploadWechatMpMaterialFile,
} from "../../../lib/api";
import type { WechatMpAsset, WechatMpMaterial, WechatMpMaterialPayload } from "../../../types";
import { WechatMpLayout } from "./wechat-mp-layout";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

const materialTypeOptions = [
  { value: "text", label: "正文资料" },
  { value: "link", label: "链接 / 飞书" },
  { value: "outline", label: "大纲" },
  { value: "quote", label: "摘录" },
  { value: "file", label: "文件" },
  { value: "other", label: "其它" },
];

const imageGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 280px), 1fr))",
  gap: 16,
  width: "100%",
  maxWidth: "100%",
  overflow: "hidden",
} as const;

const imageFrameStyle = {
  width: "100%",
  maxWidth: "100%",
  aspectRatio: "16 / 9",
  overflow: "hidden",
  background: "#111",
} as const;

const imageStyle = {
  width: "100%",
  maxWidth: "100%",
  height: "100%",
  objectFit: "cover",
  display: "block",
} as const;

function tagsFromText(value?: string): string[] {
  return (value ?? "")
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function errorMessage(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

function tagsToText(tags?: string[]): string {
  return (tags ?? []).join(", ");
}

function formatFileSize(size: number): string {
  if (!size) return "";
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function isFeishuLink(url?: string): boolean {
  return /(?:feishu\.cn|larksuite\.com)/i.test(url ?? "");
}

export function WechatMpAssetsPage() {
  const [assets, setAssets] = useState<WechatMpAsset[]>([]);
  const [materials, setMaterials] = useState<WechatMpMaterial[]>([]);
  const [loadingAssets, setLoadingAssets] = useState(true);
  const [loadingMaterials, setLoadingMaterials] = useState(true);
  const [parsingMaterialId, setParsingMaterialId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [materialModalOpen, setMaterialModalOpen] = useState(false);
  const [editingMaterial, setEditingMaterial] = useState<WechatMpMaterial | null>(null);
  const [form] = Form.useForm<WechatMpMaterialPayload & { tags_text?: string }>();

  async function loadAssets() {
    setLoadingAssets(true);
    try {
      setAssets((await fetchWechatMpAssets()).items);
    } catch {
      setError("公众号图片素材加载失败。");
    } finally {
      setLoadingAssets(false);
    }
  }

  async function loadMaterials() {
    setLoadingMaterials(true);
    try {
      setMaterials((await fetchWechatMpMaterials()).items);
    } catch {
      setError("公众号资料库加载失败。");
    } finally {
      setLoadingMaterials(false);
    }
  }

  useEffect(() => {
    void loadAssets();
    void loadMaterials();
  }, []);

  function openCreateMaterial() {
    setEditingMaterial(null);
    form.setFieldsValue({ material_type: "text", title: "", source_url: "", content: "", notes: "", tags_text: "" });
    setMaterialModalOpen(true);
  }

  function openEditMaterial(material: WechatMpMaterial) {
    setEditingMaterial(material);
    form.setFieldsValue({
      title: material.title,
      material_type: material.material_type,
      source_url: material.source_url,
      content: material.content,
      notes: material.notes,
      tags_text: tagsToText(material.tags),
    });
    setMaterialModalOpen(true);
  }

  async function submitMaterial(values: WechatMpMaterialPayload & { tags_text?: string }) {
    const payload = { ...values, tags: tagsFromText(values.tags_text) };
    delete payload.tags_text;
    try {
      if (editingMaterial) {
        const updated = await updateWechatMpMaterial(editingMaterial.id, payload);
        setMaterials((items) => items.map((item) => item.id === updated.id ? updated : item));
      } else {
        const created = await createWechatMpMaterial(payload);
        setMaterials((items) => [created, ...items]);
      }
      setMaterialModalOpen(false);
    } catch {
      setError("资料保存失败。");
    }
  }

  async function removeMaterial(id: number) {
    try {
      await deleteWechatMpMaterial(id);
      setMaterials((items) => items.filter((item) => item.id !== id));
    } catch {
      setError("资料删除失败。");
    }
  }

  async function removeAsset(id: number) {
    try {
      await deleteWechatMpAsset(id);
      setAssets((items) => items.filter((item) => item.id !== id));
    } catch {
      setError("图片素材删除失败。");
    }
  }

  async function uploadMaterial(file: File) {
    try {
      const created = await uploadWechatMpMaterialFile(file);
      setMaterials((items) => [created, ...items]);
      message.success("文件已保存到资料库。");
    } catch {
      setError("文件上传失败，请确认格式和大小。");
    }
    return false;
  }

  async function copyMaterial(material: WechatMpMaterial) {
    const text = [
      material.title,
      material.source_url && `来源：${material.source_url}`,
      material.content,
      material.notes && `备注：${material.notes}`,
    ].filter(Boolean).join("\n\n");
    await navigator.clipboard.writeText(text);
    message.success("资料已复制，可粘贴到写作页参考素材。");
  }

  async function downloadMaterial(material: WechatMpMaterial) {
    if (!material.download_url) return;
    await downloadExportFile(material.download_url, material.original_file_name || material.file_name || material.title);
  }

  async function parseFeishuMaterial(material: WechatMpMaterial) {
    setParsingMaterialId(material.id);
    setError(null);
    try {
      const updated = await parseWechatMpMaterialFeishu(material.id);
      setMaterials((items) => items.map((item) => item.id === updated.id ? updated : item));
      message.success("飞书内容已解析并保存到资料正文。");
    } catch (err) {
      setError(errorMessage(err, "飞书内容解析失败。请确认服务端已配置飞书凭证，并且应用有文档读取权限。"));
    } finally {
      setParsingMaterialId(null);
    }
  }

  return (
    <WechatMpLayout>
      <PageHeader
        eyebrow="WeChat MP / Assets"
        title="公众号素材"
        description="资料库存放待写公众号的参考资料；图片素材存放 AI 生成的公众号配图。"
        action={<Button icon={<ReloadOutlined />} onClick={() => { void loadAssets(); void loadMaterials(); }}>刷新</Button>}
      />
      {error && <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} style={{ marginBottom: 16 }} />}

      <Tabs
        items={[
          {
            key: "materials",
            label: "资料库",
            children: (
              <Card
                extra={
                  <Space>
                    <Upload
                      showUploadList={false}
                      beforeUpload={(file) => void uploadMaterial(file)}
                      accept=".txt,.md,.csv,.json,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.jpg,.jpeg,.png,.gif,.webp"
                    >
                      <Button icon={<UploadOutlined />}>上传文件</Button>
                    </Upload>
                    <Button type="primary" icon={<PlusOutlined />} onClick={openCreateMaterial}>新增资料/飞书链接</Button>
                  </Space>
                }
              >
                {loadingMaterials ? <Spin /> : materials.length === 0 ? (
                  <Empty description="暂无公众号发文资料，先添加飞书链接、选题、摘录、大纲，或上传文件。" />
                ) : (
                  <List
                    dataSource={materials}
                    renderItem={(material) => (
                      <List.Item
                        actions={[
                          <Button key="copy" size="small" icon={<CopyOutlined />} onClick={() => void copyMaterial(material)}>复制</Button>,
                          isFeishuLink(material.source_url) && (
                            <Button
                              key="parse-feishu"
                              size="small"
                              icon={<CloudSyncOutlined />}
                              loading={parsingMaterialId === material.id}
                              onClick={() => void parseFeishuMaterial(material)}
                            >
                              解析飞书
                            </Button>
                          ),
                          material.download_url && <Button key="download" size="small" icon={<DownloadOutlined />} onClick={() => void downloadMaterial(material)}>下载</Button>,
                          <Button key="edit" size="small" icon={<EditOutlined />} onClick={() => openEditMaterial(material)}>编辑</Button>,
                          <Popconfirm key="delete" title="删除这条资料？" onConfirm={() => void removeMaterial(material.id)}>
                            <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
                          </Popconfirm>,
                        ]}
                      >
                        <List.Item.Meta
                          title={<Space wrap>
                            <Text strong>{material.title}</Text>
                            <Tag>{material.material_type}</Tag>
                            <Tag color={material.usage_status === "used" ? "green" : "default"}>
                              {material.usage_status === "used" ? `已写过 ${material.used_article_count} 篇` : "未使用"}
                            </Tag>
                            {material.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}
                          </Space>}
                          description={
                            <Space direction="vertical" size={4} style={{ width: "100%" }}>
                              {material.source_url && <Text type="secondary" ellipsis>来源：{material.source_url}</Text>}
                              {material.original_file_name && <Text type="secondary" ellipsis>文件：{material.original_file_name} {formatFileSize(material.file_size)}</Text>}
                              <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0 }}>{material.content || material.notes || "暂无正文"}</Paragraph>
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                  />
                )}
              </Card>
            ),
          },
          {
            key: "images",
            label: "图片素材",
            children: (
              <Card>
                {loadingAssets ? <Spin /> : assets.length === 0 ? (
                  <Empty description="暂无公众号图片素材" />
                ) : (
                  <div style={imageGridStyle}>
                    {assets.map((asset) => (
                      <Card
                        key={asset.id}
                        style={{ minWidth: 0, maxWidth: "100%", overflow: "hidden" }}
                        styles={{ body: { overflow: "hidden" } }}
                        cover={
                          <div style={imageFrameStyle}>
                            <Image
                              src={asset.public_url}
                              preview
                              wrapperStyle={{ width: "100%", maxWidth: "100%", height: "100%", display: "block", overflow: "hidden" }}
                              style={imageStyle}
                            />
                          </div>
                        }
                        actions={[
                          <Popconfirm key="delete" title="删除此公众号图片素材？" onConfirm={() => void removeAsset(asset.id)}>
                            <DeleteOutlined />
                          </Popconfirm>,
                        ]}
                      >
                        <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 8, maxWidth: "100%", wordBreak: "break-word", overflowWrap: "anywhere" }}>{asset.prompt}</Paragraph>
                        <Tag>{asset.status}</Tag>
                      </Card>
                    ))}
                  </div>
                )}
              </Card>
            ),
          },
        ]}
      />

      <Modal
        title={editingMaterial ? "编辑资料" : "新增资料"}
        open={materialModalOpen}
        onCancel={() => setMaterialModalOpen(false)}
        footer={null}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(values) => void submitMaterial(values)}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: "请输入资料标题" }]}>
            <Input placeholder="例如：软考信息系统工程考点" />
          </Form.Item>
          <Form.Item name="material_type" label="类型">
            <Select options={materialTypeOptions} />
          </Form.Item>
          <Form.Item name="source_url" label="来源链接">
            <Input placeholder="可选，飞书文档链接、原文链接或资料出处" />
          </Form.Item>
          <Form.Item name="content" label="资料正文">
            <TextArea rows={6} placeholder="粘贴要用于公众号写作的资料、摘录、观点或大纲" />
          </Form.Item>
          <Form.Item name="tags_text" label="标签">
            <Input placeholder="用逗号或空格分隔，例如：软考, 备考, 信息系统" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <TextArea rows={3} placeholder="可选：这条资料适合怎么用、要注意什么" />
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit">保存资料</Button>
            <Button onClick={() => setMaterialModalOpen(false)}>取消</Button>
          </Space>
        </Form>
      </Modal>
    </WechatMpLayout>
  );
}
