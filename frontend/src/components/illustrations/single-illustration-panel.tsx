import { PictureOutlined, RobotOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Image,
  Input,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";

import {
  fetchIllustrationCharacters,
  fetchIllustrationModelQuotas,
  fetchIllustrationUsageSummary,
  generateIllustrationImage,
} from "../../lib/api";
import type {
  IllustrationAsset,
  IllustrationCharacter,
  IllustrationModelQuota,
  IllustrationUsageSummary,
} from "../../types";
import { IllustrationQuotaCard } from "./illustration-quota-card";
import { isCharacterConfirmed } from "./illustration-utils";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

type SingleIllustrationPanelProps = {
  onManageCharacters?: () => void;
};

function buildSinglePrompt(character: IllustrationCharacter, description: string): string {
  return `Generate one standalone 3:4 vertical Chinese Xiaohongshu illustration.

Pure white background. Minimalist black hand-drawn line art with slightly wobbly pen lines. At least 35% empty white space. Sparse red (#D9432F), orange (#FFB37A), and blue handwritten annotations. No gradients, shadows, paper texture, PPT look, or cute mascot poster.

Character definition:
${character.ip_definition}

Illustration brief:
${description}

One image explains one core idea. The character must be the same confirmed character from the reference image. Main subject occupies 40-60% of the canvas. Do not put a formal title in the top-left corner.`;
}

export function SingleIllustrationPanel({ onManageCharacters }: SingleIllustrationPanelProps) {
  const [characters, setCharacters] = useState<IllustrationCharacter[]>([]);
  const [characterId, setCharacterId] = useState<number>();
  const [quotas, setQuotas] = useState<IllustrationModelQuota[]>([]);
  const [description, setDescription] = useState("");
  const [asset, setAsset] = useState<IllustrationAsset>();
  const [usage, setUsage] = useState<IllustrationUsageSummary>();
  const [runId, setRunId] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string>();

  async function loadBasics() {
    const [characterResult, quotaResult] = await Promise.all([
      fetchIllustrationCharacters(),
      fetchIllustrationModelQuotas(),
    ]);
    const confirmed = characterResult.items.filter(isCharacterConfirmed);
    setCharacters(confirmed);
    setCharacterId((current) => current ?? confirmed[0]?.id);
    setQuotas(quotaResult.items);
  }

  useEffect(() => {
    void loadBasics().catch(() => setError("单图生成初始化失败。"));
  }, []);

  async function handleGenerate() {
    const character = characters.find((item) => item.id === characterId);
    if (!character || !description.trim()) return;
    const nextRunId = `single-${character.id}-${Date.now()}`;
    setRunId(nextRunId);
    setGenerating(true);
    setError(undefined);
    setAsset(undefined);
    setUsage(undefined);
    try {
      const result = await generateIllustrationImage({
        prompt: buildSinglePrompt(character, description.trim()),
        size: "3:4",
        character_id: character.id,
        reference_asset_ids: character.reference_image_asset_ids,
        role: "illustration",
        pipeline_run_id: nextRunId,
        shot_seq: 1,
      });
      setAsset(result);
      const [usageResult, quotaResult] = await Promise.all([
        fetchIllustrationUsageSummary(nextRunId),
        fetchIllustrationModelQuotas(),
      ]);
      setUsage(usageResult);
      setQuotas(quotaResult.items);
    } catch {
      setError("单图生成失败，请检查图片模型配置或额度。");
    } finally {
      setGenerating(false);
    }
  }

  const selectedCharacter = characters.find((item) => item.id === characterId);

  return (
    <div>
      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError(undefined)} style={{ marginBottom: 16 }} />}

      <Card
        title={<Space><PictureOutlined /><span>文章配图单图生成</span><Tag color="gold">独立配图资产</Tag></Space>}
        extra={<Text type="secondary">默认保存到文章配图资产库</Text>}
      >
        {characters.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="还没有已确认主角形象。先去主角形象页生成或上传锚定图。"
          >
            <Button type="primary" icon={<RobotOutlined />} onClick={onManageCharacters}>去确认主角形象</Button>
          </Empty>
        ) : (
          <Row gutter={[16, 16]}>
            <Col xs={24} lg={14}>
              <TextArea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={9}
                placeholder="写这一张图要表达的核心画面：主题、主角动作、场景元素、需要出现的中文手写标签。"
              />
            </Col>
            <Col xs={24} lg={10}>
              <Text strong>已确认主角</Text>
              <Select
                value={characterId}
                onChange={setCharacterId}
                style={{ width: "100%", marginTop: 8 }}
                options={characters.map((item) => ({ value: item.id, label: item.name }))}
              />
              {selectedCharacter && (
                <Paragraph type="secondary" ellipsis={{ rows: 3 }} style={{ marginTop: 12 }}>
                  {selectedCharacter.ip_definition}
                </Paragraph>
              )}
              <Button
                block
                type="primary"
                icon={<RobotOutlined />}
                loading={generating}
                disabled={!description.trim() || !characterId}
                onClick={handleGenerate}
                style={{ marginTop: 12 }}
              >
                生成这张配图
              </Button>
              {usage && <Statistic title="本张按定价估算" value={Number(usage.total_cost_yuan)} precision={4} prefix="¥" style={{ marginTop: 18 }} />}
            </Col>
          </Row>
        )}

        {asset && (
          <Card size="small" title="生成结果" style={{ marginTop: 16 }}>
            <Row gutter={[16, 16]}>
              <Col xs={24} md={8}>
                <Image src={asset.file_path} style={{ width: "100%", aspectRatio: "3 / 4", objectFit: "cover" }} />
              </Col>
              <Col xs={24} md={16}>
                <Space direction="vertical" size={8}>
                  <Tag color="green">已保存到文章配图资产库</Tag>
                  <Text>实际模型：{asset.model}</Text>
                  <Text type="secondary">流水号：{runId}</Text>
                </Space>
              </Col>
            </Row>
          </Card>
        )}
      </Card>

      <IllustrationQuotaCard quotas={quotas} />
    </div>
  );
}
