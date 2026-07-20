import {
  CheckCircleOutlined,
  PlusOutlined,
  RobotOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
  Empty,
  Image,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Steps,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";

import {
  createIllustrationCharacter,
  fetchIllustrationCharacters,
  fetchIllustrationUsageSummary,
  generateIllustrationImage,
  generateIllustrationShotList,
} from "../../lib/api";
import type {
  IllustrationAsset,
  IllustrationCharacter,
  IllustrationShot,
  IllustrationShotList,
  IllustrationUsageSummary,
} from "../../types";

const { Text, Title } = Typography;
const { TextArea } = Input;

function makeRunId(): string {
  return `illustration-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function slugify(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, "-") || `character-${Date.now()}`;
}

function buildPrompt(shot: IllustrationShot, character: IllustrationCharacter): string {
  return `Generate one standalone 3:4 vertical Chinese Xiaohongshu illustration.

Pure white background. Minimalist black hand-drawn line art with slightly wobbly pen lines. At least 35% empty white space. Sparse red (#D9432F), orange (#FFB37A), and blue handwritten annotations. No gradients, shadows, paper texture, PPT look, or cute mascot poster.

Character definition:
${character.ip_definition}

Theme: ${shot.theme}
Structure: ${shot.structure_type}
Core character action: ${shot.character_action}
Elements: ${shot.elements.join("、")}
Chinese labels: ${shot.chinese_labels.join("、")}

One image explains one core idea. The character performs the core action rather than decorating the scene. Main subject occupies 40-60% of the canvas. Do not put a formal title in the top-left corner.`;
}

export function IllustrationWorkflowPanel() {
  const [characters, setCharacters] = useState<IllustrationCharacter[]>([]);
  const [characterId, setCharacterId] = useState<number>();
  const [essay, setEssay] = useState("");
  const [shotList, setShotList] = useState<IllustrationShotList>();
  const [selected, setSelected] = useState<number[]>([]);
  const [generated, setGenerated] = useState<Record<number, IllustrationAsset>>({});
  const [generating, setGenerating] = useState<number[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [runId, setRunId] = useState(makeRunId());
  const [usage, setUsage] = useState<IllustrationUsageSummary>();
  const [error, setError] = useState<string>();
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDefinition, setNewDefinition] = useState("");
  const [creating, setCreating] = useState(false);

  async function loadCharacters() {
    const result = await fetchIllustrationCharacters();
    setCharacters(result.items);
    setCharacterId((current) => current ?? result.items[0]?.id);
  }

  async function refreshUsage(currentRunId = runId) {
    setUsage(await fetchIllustrationUsageSummary(currentRunId));
  }

  useEffect(() => {
    void loadCharacters().catch(() => setError("形象库加载失败"));
  }, []);

  async function handleCreateCharacter() {
    if (!newName.trim() || !newDefinition.trim()) return;
    setCreating(true);
    try {
      const created = await createIllustrationCharacter({
        name: newName.trim(),
        slug: slugify(newName),
        ip_definition: newDefinition.trim(),
        created_via: "text_only",
      });
      setCharacters((items) => [created, ...items]);
      setCharacterId(created.id);
      setCreateOpen(false);
      setNewName("");
      setNewDefinition("");
    } finally {
      setCreating(false);
    }
  }

  async function handleAnalyze() {
    if (!characterId || !essay.trim()) return;
    const nextRunId = makeRunId();
    setRunId(nextRunId);
    setAnalyzing(true);
    setError(undefined);
    setGenerated({});
    try {
      const result = await generateIllustrationShotList({
        essay: essay.trim(),
        character_id: characterId,
        pipeline_run_id: nextRunId,
      });
      setShotList(result);
      setSelected(result.shots.map((shot) => shot.seq));
      await refreshUsage(nextRunId);
    } catch {
      setError("拆文失败，请检查文本模型配置。拦截器会显示具体错误。");
    } finally {
      setAnalyzing(false);
    }
  }

  function updateShot(seq: number, patch: Partial<IllustrationShot>) {
    setShotList((current) => current ? {
      ...current,
      shots: current.shots.map((shot) => shot.seq === seq ? { ...shot, ...patch } : shot),
    } : current);
  }

  async function generateShot(shot: IllustrationShot) {
    const character = characters.find((item) => item.id === characterId);
    if (!character) return;
    setGenerating((items) => [...items, shot.seq]);
    try {
      const asset = await generateIllustrationImage({
        prompt: buildPrompt(shot, character),
        size: "3:4",
        character_id: character.id,
        reference_asset_ids: character.reference_image_asset_ids,
        pipeline_run_id: runId,
        shot_seq: shot.seq,
      });
      setGenerated((items) => ({ ...items, [shot.seq]: asset }));
      await refreshUsage();
    } finally {
      setGenerating((items) => items.filter((seq) => seq !== shot.seq));
    }
  }

  async function generateSelected() {
    if (!shotList) return;
    for (const shot of shotList.shots.filter((item) => selected.includes(item.seq))) {
      if (!generated[shot.seq]) await generateShot(shot);
    }
  }

  const currentStep = shotList ? (Object.keys(generated).length ? 3 : 2) : (essay.trim() ? 1 : 0);

  return (
    <Card
      title={<Space><ThunderboltOutlined /><span>文章配图流水线</span><Tag color="gold">独立资产库</Tag></Space>}
      extra={<Text type="secondary">拆文免费试算 · 按需生成 · 默认保存</Text>}
      style={{ marginBottom: 24, borderColor: "#7d6b3c" }}
    >
      <Steps
        current={currentStep}
        size="small"
        items={[{ title: "贴文章" }, { title: "选形象" }, { title: "确认分镜" }, { title: "生成配图" }]}
        style={{ marginBottom: 24 }}
      />

      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError(undefined)} style={{ marginBottom: 16 }} />}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={15}>
          <TextArea
            value={essay}
            onChange={(event) => setEssay(event.target.value)}
            rows={8}
            placeholder="粘贴小红书正文、公众号文章或方法论内容。系统会找认知锚点，而不是平均配图。"
          />
        </Col>
        <Col xs={24} lg={9}>
          <Text strong>主角形象</Text>
          <Space.Compact style={{ width: "100%", marginTop: 8 }}>
            <Select
              value={characterId}
              onChange={setCharacterId}
              style={{ width: "100%" }}
              placeholder="先创建一个形象"
              options={characters.map((item) => ({ value: item.id, label: item.name }))}
            />
            <Button icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建</Button>
          </Space.Compact>
          <Text type="secondary" style={{ display: "block", marginTop: 10 }}>
            当前支持文字定义；上传参考图和在线生成锚定图将在额度切换阶段接入同一形象库。
          </Text>
          <Button
            type="primary"
            icon={<RobotOutlined />}
            loading={analyzing}
            disabled={!essay.trim() || !characterId}
            onClick={handleAnalyze}
            block
            style={{ marginTop: 20 }}
          >
            拆文并生成配图方案
          </Button>
          {usage && (
            <Statistic title="本次实际花费" value={Number(usage.total_cost_yuan)} precision={4} prefix="¥" style={{ marginTop: 18 }} />
          )}
        </Col>
      </Row>

      {analyzing && <div style={{ padding: 40, textAlign: "center" }}><Spin tip="正在提炼认知锚点…" /></div>}

      {shotList && (
        <>
          <Divider />
          <Title level={5}>{shotList.core_thesis}</Title>
          <Space wrap style={{ marginBottom: 16 }}>
            {shotList.cognitive_anchors.map((anchor) => <Tag key={anchor}>{anchor}</Tag>)}
          </Space>
          <Row gutter={[12, 12]}>
            {shotList.shots.map((shot) => {
              const asset = generated[shot.seq];
              const busy = generating.includes(shot.seq);
              return (
                <Col xs={24} md={12} xl={8} key={shot.seq}>
                  <Card
                    size="small"
                    title={<Space><Checkbox checked={selected.includes(shot.seq)} onChange={(event) => setSelected((items) => event.target.checked ? [...items, shot.seq] : items.filter((seq) => seq !== shot.seq))} />#{shot.seq} {shot.purpose}</Space>}
                    extra={<Tag>{shot.structure_type}</Tag>}
                  >
                    {asset ? (
                      <Image src={asset.file_path} style={{ width: "100%", aspectRatio: "3 / 4", objectFit: "cover" }} />
                    ) : (
                      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={busy ? "生成中…" : "尚未生成"} />
                    )}
                    <TextArea value={shot.theme} onChange={(event) => updateShot(shot.seq, { theme: event.target.value })} autoSize={{ minRows: 2, maxRows: 4 }} style={{ marginTop: 10 }} />
                    <Space wrap style={{ marginTop: 8 }}>
                      <Tag color="orange">动作：{shot.character_action}</Tag>
                      {shot.chinese_labels.map((label) => <Tag key={label}>{label}</Tag>)}
                    </Space>
                    <Button block type={asset ? "default" : "primary"} loading={busy} onClick={() => generateShot(shot)} style={{ marginTop: 12 }}>
                      {asset ? <><CheckCircleOutlined /> 已保存，重新生成</> : "生成这张"}
                    </Button>
                  </Card>
                </Col>
              );
            })}
          </Row>
          <Button type="primary" size="large" block icon={<ThunderboltOutlined />} disabled={!selected.length || Boolean(generating.length)} onClick={generateSelected} style={{ marginTop: 18 }}>
            一键生成已选 {selected.length} 张
          </Button>
        </>
      )}

      <Modal title="新建形象" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={handleCreateCharacter} confirmLoading={creating} okButtonProps={{ disabled: !newName.trim() || !newDefinition.trim() }}>
        <Input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="形象名称，如：小猫、小护士" style={{ marginBottom: 12 }} />
        <TextArea value={newDefinition} onChange={(event) => setNewDefinition(event.target.value)} rows={8} placeholder="外形 + 性格态度 + 动作习惯 + 禁忌。例：圆胖玳瑁猫，懒但会把活干完，默认眯眼，不卖萌。" />
      </Modal>
    </Card>
  );
}
