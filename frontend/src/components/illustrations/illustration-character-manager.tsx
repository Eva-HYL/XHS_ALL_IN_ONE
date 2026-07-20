import {
  DeleteOutlined,
  EditOutlined,
  PictureOutlined,
  PlusOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Image,
  Input,
  Modal,
  Popconfirm,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
  Upload,
} from "antd";
import { useEffect, useState } from "react";

import {
  createIllustrationCharacter,
  deleteIllustrationCharacter,
  fetchIllustrationAssets,
  fetchIllustrationCharacters,
  fetchIllustrationModelQuotas,
  generateIllustrationImage,
  importIllustrationAsset,
  updateIllustrationCharacter,
  uploadAssetFile,
} from "../../lib/api";
import type { IllustrationAsset, IllustrationCharacter, IllustrationModelQuota } from "../../types";
import { IllustrationQuotaCard } from "./illustration-quota-card";
import { isCharacterConfirmed, slugify } from "./illustration-utils";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

type EditingCharacter = {
  id?: number;
  name: string;
  ip_definition: string;
};

export function IllustrationCharacterManager() {
  const [characters, setCharacters] = useState<IllustrationCharacter[]>([]);
  const [assets, setAssets] = useState<IllustrationAsset[]>([]);
  const [quotas, setQuotas] = useState<IllustrationModelQuota[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [anchoringId, setAnchoringId] = useState<number>();
  const [editing, setEditing] = useState<EditingCharacter>();
  const [error, setError] = useState<string>();

  async function loadAll() {
    setLoading(true);
    setError(undefined);
    try {
      const [characterResult, assetResult, quotaResult] = await Promise.all([
        fetchIllustrationCharacters(),
        fetchIllustrationAssets(),
        fetchIllustrationModelQuotas(),
      ]);
      setCharacters(characterResult.items);
      setAssets(assetResult.items);
      setQuotas(quotaResult.items);
    } catch {
      setError("主角形象加载失败。");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAll();
  }, []);

  function openCreate() {
    setEditing({ name: "", ip_definition: "" });
  }

  function openEdit(character: IllustrationCharacter) {
    setEditing({ id: character.id, name: character.name, ip_definition: character.ip_definition });
  }

  async function saveCharacter() {
    if (!editing?.name.trim() || !editing.ip_definition.trim()) return;
    setSaving(true);
    try {
      if (editing.id) {
        const updated = await updateIllustrationCharacter(editing.id, {
          name: editing.name.trim(),
          ip_definition: editing.ip_definition.trim(),
        });
        setCharacters((items) => items.map((item) => item.id === updated.id ? updated : item));
      } else {
        const created = await createIllustrationCharacter({
          name: editing.name.trim(),
          slug: slugify(editing.name),
          ip_definition: editing.ip_definition.trim(),
          created_via: "text_only",
        });
        setCharacters((items) => [created, ...items]);
      }
      setEditing(undefined);
    } finally {
      setSaving(false);
    }
  }

  async function attachAnchorAsset(character: IllustrationCharacter, asset: IllustrationAsset) {
    const ids = [...new Set([...character.reference_image_asset_ids, asset.id])];
    const updated = await updateIllustrationCharacter(character.id, { reference_image_asset_ids: ids });
    setCharacters((items) => items.map((item) => item.id === updated.id ? updated : item));
    setAssets((items) => [asset, ...items.filter((item) => item.id !== asset.id)]);
  }

  async function uploadAnchor(character: IllustrationCharacter, file: File) {
    setAnchoringId(character.id);
    try {
      const uploaded = await uploadAssetFile(file);
      const asset = await importIllustrationAsset(uploaded.file_name, character.id);
      await attachAnchorAsset(character, asset);
    } catch {
      setError("参考图上传失败。");
    } finally {
      setAnchoringId(undefined);
    }
    return false;
  }

  async function generateAnchor(character: IllustrationCharacter) {
    setAnchoringId(character.id);
    setError(undefined);
    try {
      const asset = await generateIllustrationImage({
        prompt: `Create a clean 3:4 character reference sheet on white background. Preserve this character exactly for future illustrations: ${character.ip_definition}`,
        size: "3:4",
        character_id: character.id,
        role: "character_anchor",
        pipeline_run_id: `character-${character.id}-${Date.now()}`,
        shot_seq: 0,
      });
      await attachAnchorAsset(character, asset);
      const quotaResult = await fetchIllustrationModelQuotas();
      setQuotas(quotaResult.items);
    } catch {
      setError("在线生成形象失败，请检查图片模型配置或额度。");
    } finally {
      setAnchoringId(undefined);
    }
  }

  async function removeCharacter(character: IllustrationCharacter) {
    await deleteIllustrationCharacter(character.id);
    setCharacters((items) => items.filter((item) => item.id !== character.id));
  }

  function anchorAssets(character: IllustrationCharacter) {
    const ids = new Set(character.reference_image_asset_ids);
    return assets.filter((asset) => ids.has(asset.id));
  }

  return (
    <div>
      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError(undefined)} style={{ marginBottom: 16 }} />}

      <Card
        title={<Space><RobotOutlined /><span>主角形象管理</span></Space>}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建主角</Button>}
      >
        <Paragraph type="secondary">
          先创建形象定义，再上传参考图或在线生成锚定图。拥有至少 1 张锚定图后，流水线和单图生成才会把它视为已确认主角。
        </Paragraph>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center" }}><Spin tip="正在加载主角形象..." /></div>
        ) : characters.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无主角形象，先创建一个用于配图的固定 IP。" />
        ) : (
          <Row gutter={[12, 12]}>
            {characters.map((character) => {
              const anchors = anchorAssets(character);
              const confirmed = isCharacterConfirmed(character);
              const busy = anchoringId === character.id;
              return (
                <Col xs={24} md={12} xl={8} key={character.id}>
                  <Card
                    size="small"
                    title={<Space><span>{character.name}</span><Tag color={confirmed ? "green" : "orange"}>{confirmed ? "已确认" : "待确认"}</Tag></Space>}
                    extra={
                      <Space size={4}>
                        <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(character)} />
                        <Popconfirm title="删除这个主角形象？" onConfirm={() => void removeCharacter(character)}>
                          <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                      </Space>
                    }
                  >
                    <Paragraph ellipsis={{ rows: 3 }} style={{ minHeight: 66 }}>{character.ip_definition}</Paragraph>
                    <Space wrap style={{ marginBottom: 12 }}>
                      {anchors.slice(0, 3).map((asset) => (
                        <Image
                          key={asset.id}
                          src={asset.file_path}
                          width={58}
                          height={78}
                          style={{ objectFit: "cover", borderRadius: 4 }}
                        />
                      ))}
                      {!anchors.length && <Text type="secondary">还没有锚定图</Text>}
                    </Space>
                    <Space wrap>
                      <Upload accept="image/*" showUploadList={false} beforeUpload={(file) => uploadAnchor(character, file)} disabled={busy}>
                        <Button icon={<PictureOutlined />} loading={busy}>上传参考图</Button>
                      </Upload>
                      <Button icon={<RobotOutlined />} loading={busy} onClick={() => void generateAnchor(character)}>在线生成形象</Button>
                    </Space>
                  </Card>
                </Col>
              );
            })}
          </Row>
        )}
      </Card>

      <IllustrationQuotaCard quotas={quotas} />

      <Modal
        title={editing?.id ? "编辑主角形象" : "新建主角形象"}
        open={Boolean(editing)}
        onCancel={() => setEditing(undefined)}
        onOk={saveCharacter}
        confirmLoading={saving}
        okButtonProps={{ disabled: !editing?.name.trim() || !editing.ip_definition.trim() }}
      >
        <Input
          value={editing?.name}
          onChange={(event) => setEditing((current) => current && { ...current, name: event.target.value })}
          placeholder="形象名称，如：小猫、小护士"
          style={{ marginBottom: 12 }}
        />
        <TextArea
          value={editing?.ip_definition}
          onChange={(event) => setEditing((current) => current && { ...current, ip_definition: event.target.value })}
          rows={8}
          placeholder="外形 + 性格态度 + 动作习惯 + 禁忌。例：圆胖玳瑁猫，懒但会把活干完，默认眯眼，不卖萌。"
        />
      </Modal>
    </div>
  );
}
