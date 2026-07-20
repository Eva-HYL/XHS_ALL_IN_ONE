import {
  CheckCircleOutlined,
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
  createIllustrationRun,
  fetchIllustrationAssets,
  fetchIllustrationCharacters,
  fetchIllustrationModelQuotas,
  fetchIllustrationRuns,
  fetchIllustrationUsageSummary,
  generateIllustrationRunShot,
  updateIllustrationRun,
} from "../../lib/api";
import type {
  IllustrationAsset,
  IllustrationCharacter,
  IllustrationModelQuota,
  IllustrationShot,
  IllustrationShotList,
  IllustrationUsageSummary,
} from "../../types";
import { IllustrationQuotaCard } from "./illustration-quota-card";
import { buildIllustrationPrompt, isCharacterConfirmed } from "./illustration-utils";

const { Text, Title } = Typography;
const { TextArea } = Input;

type IllustrationWorkflowPanelProps = {
  onManageCharacters?: () => void;
};

export function IllustrationWorkflowPanel({ onManageCharacters }: IllustrationWorkflowPanelProps) {
  const [characters, setCharacters] = useState<IllustrationCharacter[]>([]);
  const [characterId, setCharacterId] = useState<number>();
  const [essay, setEssay] = useState("");
  const [shotList, setShotList] = useState<IllustrationShotList>();
  const [selected, setSelected] = useState<number[]>([]);
  const [generated, setGenerated] = useState<Record<number, IllustrationAsset>>({});
  const [generating, setGenerating] = useState<number[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [runId, setRunId] = useState("");
  const [usage, setUsage] = useState<IllustrationUsageSummary>();
  const [quotas, setQuotas] = useState<IllustrationModelQuota[]>([]);
  const [error, setError] = useState<string>();

  async function loadCharacters() {
    const result = await fetchIllustrationCharacters();
    const confirmed = result.items.filter(isCharacterConfirmed);
    setCharacters(confirmed);
    setCharacterId((current) => confirmed.some((item) => item.id === current) ? current : confirmed[0]?.id);
  }

  async function refreshUsage(currentRunId = runId) {
    setUsage(await fetchIllustrationUsageSummary(currentRunId));
  }

  async function loadQuotas() {
    const result = await fetchIllustrationModelQuotas();
    setQuotas(result.items);
  }

  async function restoreLatestRun() {
    const result = await fetchIllustrationRuns();
    const latest = result.items[0];
    if (!latest) return;
    setRunId(latest.id);
    setEssay(latest.essay);
    setCharacterId(latest.character_id);
    setShotList({ core_thesis: latest.core_thesis, cognitive_anchors: latest.cognitive_anchors, shots: latest.shots });
    setSelected(latest.selected_shot_seqs);
    const assets = await fetchIllustrationAssets(latest.id);
    setGenerated(Object.fromEntries(assets.items.filter((asset) => asset.shot_seq != null).map((asset) => [asset.shot_seq!, asset])));
    await refreshUsage(latest.id);
  }

  useEffect(() => {
    void loadCharacters().catch(() => setError("形象库加载失败"));
    void loadQuotas().catch(() => setError("模型额度加载失败"));
    void restoreLatestRun().catch(() => undefined);
  }, []);

  async function handleAnalyze() {
    if (!characterId || !essay.trim()) return;
    setAnalyzing(true);
    setError(undefined);
    setGenerated({});
    try {
      const result = await createIllustrationRun({
        essay: essay.trim(),
        character_id: characterId,
      });
      setRunId(result.id);
      setShotList({ core_thesis: result.core_thesis, cognitive_anchors: result.cognitive_anchors, shots: result.shots });
      setSelected(result.selected_shot_seqs);
      await refreshUsage(result.id);
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
      if (shotList) await updateIllustrationRun(runId, { shots: shotList.shots, selected_shot_seqs: selected });
      const result = await generateIllustrationRunShot(runId, shot.seq, {
        prompt: buildIllustrationPrompt(shot, character),
        size: "3:4",
        reference_asset_ids: character.reference_image_asset_ids,
      });
      const asset = result.asset;
      setGenerated((items) => ({ ...items, [shot.seq]: asset }));
      await Promise.all([refreshUsage(), loadQuotas()]);
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
      className="illustration-workflow-card"
      title={<Space><ThunderboltOutlined /><span>文章配图流水线</span><Tag color="gold">独立资产库</Tag></Space>}
      extra={<Text type="secondary">拆文免费试算 · 按需生成 · 默认保存</Text>}
      style={{ marginBottom: 24 }}
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
          <Text strong>已确认主角形象</Text>
          <Select
            value={characterId}
            onChange={setCharacterId}
            style={{ width: "100%", marginTop: 8 }}
            placeholder="先去主角形象页确认一个形象"
            options={characters.map((item) => ({ value: item.id, label: item.name }))}
          />
          {characters.length === 0 ? (
            <Alert
              type="warning"
              showIcon
              message="需要先生成并确认主角形象"
              description="主角拥有至少 1 张锚定图后，流水线才会使用它生成整组文章配图。"
              action={<Button size="small" onClick={onManageCharacters}>去管理</Button>}
              style={{ marginTop: 12 }}
            />
          ) : (
            <Text type="secondary" style={{ display: "block", marginTop: 10 }}>
              已绑定 {characters.find((item) => item.id === characterId)?.reference_image_asset_ids.length ?? 0} 张锚定图，后续配图会自动引用。
            </Text>
          )}
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
          {usage && <Statistic title="本次按定价估算" value={Number(usage.total_cost_yuan)} precision={4} prefix="¥" style={{ marginTop: 18 }} />}
        </Col>
      </Row>

      <IllustrationQuotaCard quotas={quotas} />

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
                      <>
                        <Image src={asset.file_path} style={{ width: "100%", aspectRatio: "3 / 4", objectFit: "cover" }} />
                        <Tag color="green" style={{ marginTop: 8 }}>实际模型：{asset.model}</Tag>
                      </>
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
    </Card>
  );
}
