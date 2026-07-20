import {
  CheckCircleOutlined,
  FileTextOutlined,
  PictureOutlined,
  RobotOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
  Empty,
  Image,
  Input,
  List,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";

import {
  addDraftAsset,
  createDraftFromNote,
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
  Draft,
  IllustrationAsset,
  IllustrationCharacter,
  IllustrationModelQuota,
  IllustrationRun,
  IllustrationShot,
  IllustrationUsageSummary,
} from "../../types";
import { IllustrationQuotaCard } from "./illustration-quota-card";
import { buildIllustrationPrompt, isCharacterConfirmed } from "./illustration-utils";

const { Text, Title, Paragraph } = Typography;
const { TextArea } = Input;

type IllustrationWorkflowPanelProps = {
  onManageCharacters?: () => void;
};

type QueueItem = {
  key: string;
  essay: string;
  status: "pending" | "running" | "done" | "failed";
  run?: IllustrationRun;
  error?: string;
};

type PromptMap = Record<number, string>;
type AssetMap = Record<number, IllustrationAsset>;

function splitEssays(raw: string): string[] {
  return raw
    .split(/\n-{3,}\n|\n#{3,}\n/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

function shotPrompt(shot: IllustrationShot): string {
  return typeof shot.image_prompt === "string" ? shot.image_prompt : "";
}

function patchShotPrompt(shots: IllustrationRun["shots"], seq: number, prompt: string): IllustrationRun["shots"] {
  return shots.map((shot) => shot.seq === seq ? { ...shot, image_prompt: prompt } : shot);
}

export function IllustrationWorkflowPanel({ onManageCharacters }: IllustrationWorkflowPanelProps) {
  const [characters, setCharacters] = useState<IllustrationCharacter[]>([]);
  const [characterId, setCharacterId] = useState<number>();
  const [essayInput, setEssayInput] = useState("");
  const [runs, setRuns] = useState<IllustrationRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>();
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [creatingQueue, setCreatingQueue] = useState(false);
  const [loading, setLoading] = useState(true);
  const [generated, setGenerated] = useState<AssetMap>({});
  const [prompts, setPrompts] = useState<PromptMap>({});
  const [selected, setSelected] = useState<number[]>([]);
  const [generating, setGenerating] = useState<number[]>([]);
  const [usage, setUsage] = useState<IllustrationUsageSummary>();
  const [quotas, setQuotas] = useState<IllustrationModelQuota[]>([]);
  const [savingDraft, setSavingDraft] = useState(false);
  const [savedDraft, setSavedDraft] = useState<Draft>();
  const [error, setError] = useState<string>();

  const selectedRun = runs.find((run) => run.id === selectedRunId);
  const selectedCharacter = characters.find((item) => item.id === (selectedRun?.character_id ?? characterId));
  const essayCount = splitEssays(essayInput).length;

  async function refreshCharacters() {
    const result = await fetchIllustrationCharacters();
    const confirmed = result.items.filter(isCharacterConfirmed);
    setCharacters(confirmed);
    setCharacterId((current) => confirmed.some((item) => item.id === current) ? current : confirmed[0]?.id);
    return confirmed;
  }

  async function refreshRuns(preferredRunId?: string) {
    const result = await fetchIllustrationRuns();
    setRuns(result.items);
    const nextRunId = preferredRunId ?? selectedRunId ?? result.items[0]?.id;
    setSelectedRunId(nextRunId);
    return result.items.find((run) => run.id === nextRunId) ?? result.items[0];
  }

  async function refreshQuotas() {
    const result = await fetchIllustrationModelQuotas();
    setQuotas(result.items);
  }

  async function loadRunAssets(runId: string) {
    const assets = await fetchIllustrationAssets(runId);
    setGenerated(Object.fromEntries(assets.items.filter((asset) => asset.shot_seq != null).map((asset) => [asset.shot_seq!, asset])));
  }

  async function loadUsage(runId: string) {
    setUsage(await fetchIllustrationUsageSummary(runId));
  }

  function characterForRun(run: IllustrationRun, source = characters) {
    return source.find((item) => item.id === run.character_id);
  }

  async function ensureRunPrompts(run: IllustrationRun, source = characters, syncVisibleState = true) {
    const character = characterForRun(run, source);
    if (!character) return run;

    let changed = false;
    const nextPrompts: PromptMap = {};
    const nextShots = run.shots.map((shot) => {
      const existingPrompt = shotPrompt(shot);
      const prompt = existingPrompt || buildIllustrationPrompt(shot, character);
      nextPrompts[shot.seq] = prompt;
      if (existingPrompt) return shot;
      changed = true;
      return { ...shot, image_prompt: prompt };
    });

    if (syncVisibleState) setPrompts(nextPrompts);
    if (!changed) return run;

    const updated = await updateIllustrationRun(run.id, {
      shots: nextShots,
      selected_shot_seqs: run.selected_shot_seqs,
    });
    setRuns((items) => items.map((item) => item.id === updated.id ? updated : item));
    return updated;
  }

  async function loadInitial() {
    setLoading(true);
    setError(undefined);
    try {
      const [confirmed] = await Promise.all([refreshCharacters(), refreshQuotas()]);
      const run = await refreshRuns();
      if (run) {
        const readyRun = await ensureRunPrompts(run, confirmed);
        hydrateRun(readyRun);
        await Promise.all([loadRunAssets(readyRun.id), loadUsage(readyRun.id)]);
      }
    } catch {
      setError("拆文资产加载失败。");
    } finally {
      setLoading(false);
    }
  }

  function hydrateRun(run: IllustrationRun) {
    setSelected(run.selected_shot_seqs);
    setPrompts(Object.fromEntries(run.shots.map((shot) => [shot.seq, shotPrompt(shot)])));
    setSavedDraft(undefined);
  }

  useEffect(() => {
    void loadInitial();
  }, []);

  useEffect(() => {
    if (!selectedRun) return;
    void ensureRunPrompts(selectedRun).then((readyRun) => {
      hydrateRun(readyRun);
      return Promise.all([loadRunAssets(readyRun.id), loadUsage(readyRun.id)]);
    }).catch(() => undefined);
  }, [selectedRun?.id]);

  async function createRunsInQueue() {
    if (!characterId || !essayInput.trim()) return;
    const essays = splitEssays(essayInput);
    if (!essays.length) return;

    setCreatingQueue(true);
    setError(undefined);
    setQueue(essays.map((essay, index) => ({ key: `${Date.now()}-${index}`, essay, status: "pending" })));

    let latestRun: IllustrationRun | undefined;
    for (let index = 0; index < essays.length; index += 1) {
      setQueue((items) => items.map((item, idx) => idx === index ? { ...item, status: "running" } : item));
      try {
        const run = await createIllustrationRun({ essay: essays[index], character_id: characterId });
        const readyRun = await ensureRunPrompts(run, characters, false);
        latestRun = readyRun;
        setQueue((items) => items.map((item, idx) => idx === index ? { ...item, status: "done", run: readyRun } : item));
        setRuns((items) => [readyRun, ...items.filter((item) => item.id !== readyRun.id)]);
      } catch {
        setQueue((items) => items.map((item, idx) => idx === index ? { ...item, status: "failed", error: "拆文失败" } : item));
      }
    }

    setCreatingQueue(false);
    if (latestRun) {
      setSelectedRunId(latestRun.id);
      hydrateRun(latestRun);
      await Promise.all([loadRunAssets(latestRun.id), loadUsage(latestRun.id), refreshQuotas()]);
    }
  }

  async function persistRunPatch(nextShots = selectedRun?.shots, nextSelected = selected) {
    if (!selectedRun || !nextShots) return;
    const updated = await updateIllustrationRun(selectedRun.id, {
      shots: nextShots,
      selected_shot_seqs: nextSelected,
    });
    setRuns((items) => items.map((item) => item.id === updated.id ? updated : item));
  }

  async function generatePromptForShot(shot: IllustrationRun["shots"][number]) {
    if (!selectedRun || !selectedCharacter) return;
    const prompt = buildIllustrationPrompt(shot, selectedCharacter);
    const nextShots = patchShotPrompt(selectedRun.shots, shot.seq, prompt);
    setPrompts((items) => ({ ...items, [shot.seq]: prompt }));
    await persistRunPatch(nextShots);
  }

  async function updatePrompt(seq: number, prompt: string) {
    setPrompts((items) => ({ ...items, [seq]: prompt }));
  }

  async function savePrompt(seq: number) {
    if (!selectedRun) return;
    await persistRunPatch(patchShotPrompt(selectedRun.shots, seq, prompts[seq] ?? ""));
  }

  async function toggleSelected(seq: number, checked: boolean) {
    const nextSelected = checked ? [...new Set([...selected, seq])] : selected.filter((item) => item !== seq);
    setSelected(nextSelected);
    await persistRunPatch(selectedRun?.shots, nextSelected);
  }

  async function generateShot(shot: IllustrationRun["shots"][number]) {
    if (!selectedRun || !selectedCharacter) return;
    const prompt = (prompts[shot.seq] || buildIllustrationPrompt(shot, selectedCharacter)).trim();
    if (!prompt) {
      setError("图片提示词为空，请检查拆文资产。");
      return;
    }

    setGenerating((items) => [...items, shot.seq]);
    setError(undefined);
    try {
      await savePrompt(shot.seq);
      const result = await generateIllustrationRunShot(selectedRun.id, shot.seq, {
        prompt,
        size: "3:4",
        reference_asset_ids: selectedCharacter.reference_image_asset_ids,
      });
      setRuns((items) => items.map((item) => item.id === result.run.id ? result.run : item));
      setGenerated((items) => ({ ...items, [shot.seq]: result.asset }));
      await Promise.all([loadUsage(selectedRun.id), refreshQuotas()]);
    } catch {
      setError("图片生成失败，请检查图片模型配置或额度。");
    } finally {
      setGenerating((items) => items.filter((seq) => seq !== shot.seq));
    }
  }

  async function generateSelectedShots() {
    if (!selectedRun) return;
    for (const shot of selectedRun.shots.filter((item) => selected.includes(item.seq))) {
      if (!generated[shot.seq]) await generateShot(shot);
    }
  }

  async function saveToDraftStudio() {
    if (!selectedRun) return;
    const assets = selectedRun.shots
      .filter((shot) => selected.includes(shot.seq))
      .map((shot) => generated[shot.seq])
      .filter(Boolean);
    if (!assets.length) {
      setError("请先生成至少一张配图。");
      return;
    }

    setSavingDraft(true);
    setError(undefined);
    try {
      const draft = await createDraftFromNote({
        platform: "xhs",
        title: selectedRun.core_thesis || "小红书配图草稿",
        body: selectedRun.essay,
        intent: "publish",
      });
      for (const asset of assets) {
        await addDraftAsset(draft.id, { asset_type: "image", url: asset.file_path });
      }
      setSavedDraft(draft);
    } catch {
      setError("保存到草稿工坊失败。");
    } finally {
      setSavingDraft(false);
    }
  }

  return (
    <div>
      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError(undefined)} style={{ marginBottom: 16 }} />}

      <Card
        className="illustration-workflow-card"
        title={<Space><ThunderboltOutlined /><span>拆文资产队列</span><Tag color="gold">拆文独立资产</Tag></Space>}
        extra={<Text type="secondary">拆文完成后自动生成提示词，可修改后再生成图片</Text>}
      >
        {loading ? (
          <div style={{ padding: 40, textAlign: "center" }}><Spin tip="正在加载拆文资产..." /></div>
        ) : (
          <Row gutter={[16, 16]}>
            <Col xs={24} lg={8}>
              <Space direction="vertical" size={12} style={{ width: "100%" }}>
                <Card size="small" title="创建拆文流程">
                  <Text strong>已确认主角</Text>
                  <Select
                    value={characterId}
                    onChange={setCharacterId}
                    style={{ width: "100%", marginTop: 8 }}
                    placeholder="先去主角形象页确认一个形象"
                    options={characters.map((item) => ({ value: item.id, label: item.name }))}
                  />
                  {characters.length === 0 && (
                    <Alert
                      type="warning"
                      showIcon
                      message="需要先确认主角形象"
                      action={<Button size="small" onClick={onManageCharacters}>去管理</Button>}
                      style={{ marginTop: 12 }}
                    />
                  )}
                  <TextArea
                    value={essayInput}
                    onChange={(event) => setEssayInput(event.target.value)}
                    rows={8}
                    placeholder="粘贴一篇或多篇正文。多篇文章用单独一行 --- 分隔，会按队列逐个拆文。"
                    style={{ marginTop: 12 }}
                  />
                  <Button
                    block
                    type="primary"
                    icon={<FileTextOutlined />}
                    loading={creatingQueue}
                    disabled={!characterId || !essayInput.trim()}
                    onClick={createRunsInQueue}
                    style={{ marginTop: 12 }}
                  >
                    创建 {essayCount || 1} 个拆文流程
                  </Button>
                </Card>

                {queue.length > 0 && (
                  <Card size="small" title="当前队列">
                    <List
                      size="small"
                      dataSource={queue}
                      renderItem={(item, index) => (
                        <List.Item>
                          <Space>
                            <Badge status={item.status === "done" ? "success" : item.status === "failed" ? "error" : item.status === "running" ? "processing" : "default"} />
                            <Text>#{index + 1}</Text>
                            <Text type="secondary" ellipsis style={{ maxWidth: 180 }}>{item.essay.slice(0, 36)}</Text>
                          </Space>
                        </List.Item>
                      )}
                    />
                  </Card>
                )}

                <Card size="small" title={<Space>拆文资产 <Badge count={runs.length} /></Space>}>
                  {runs.length === 0 ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无拆文资产。" />
                  ) : (
                    <List
                      size="small"
                      dataSource={runs}
                      renderItem={(run) => (
                        <List.Item
                          onClick={() => setSelectedRunId(run.id)}
                          style={{
                            cursor: "pointer",
                            borderRadius: 6,
                            paddingInline: 8,
                            background: run.id === selectedRunId ? "var(--illustration-quota-bg)" : undefined,
                          }}
                        >
                          <List.Item.Meta
                            title={<Text strong={run.id === selectedRunId} ellipsis>{run.core_thesis || "未命名拆文"}</Text>}
                            description={<Space wrap><Tag>{run.status}</Tag><Text type="secondary">{run.shots.length} 张方案</Text></Space>}
                          />
                        </List.Item>
                      )}
                    />
                  )}
                </Card>
              </Space>
            </Col>

            <Col xs={24} lg={16}>
              {!selectedRun ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一个拆文资产查看详情。" />
              ) : (
                <Space direction="vertical" size={16} style={{ width: "100%" }}>
                  <Card size="small">
                    <Space direction="vertical" size={8} style={{ width: "100%" }}>
                      <Space wrap>
                        <Title level={5} style={{ margin: 0 }}>{selectedRun.core_thesis}</Title>
                        <Tag color="blue">{selectedCharacter?.name ?? "主角"}</Tag>
                        <Tag>{selectedRun.status}</Tag>
                      </Space>
                      <Paragraph type="secondary" ellipsis={{ rows: 3 }}>{selectedRun.essay}</Paragraph>
                      <Space wrap>
                        {selectedRun.cognitive_anchors.map((anchor) => <Tag key={anchor}>{anchor}</Tag>)}
                      </Space>
                      <Space wrap>
                        {usage && <Statistic title="本拆文资产成本" value={Number(usage.total_cost_yuan)} precision={4} prefix="¥" />}
                        <Button
                          type="primary"
                          icon={<ThunderboltOutlined />}
                          disabled={!selected.length || Boolean(generating.length)}
                          onClick={generateSelectedShots}
                        >
                          生成已选 {selected.length} 张
                        </Button>
                        <Button
                          icon={<CheckCircleOutlined />}
                          loading={savingDraft}
                          disabled={!Object.keys(generated).length}
                          onClick={saveToDraftStudio}
                        >
                          保存到草稿工坊
                        </Button>
                      </Space>
                      {savedDraft && <Alert type="success" showIcon message={`已保存到草稿工坊 #${savedDraft.id}`} />}
                    </Space>
                  </Card>

                  <Row gutter={[12, 12]}>
                    {selectedRun.shots.map((shot) => {
                      const asset = generated[shot.seq];
                      const prompt = prompts[shot.seq] ?? "";
                      const busy = generating.includes(shot.seq);
                      return (
                        <Col xs={24} xl={12} key={shot.seq}>
                          <Card
                            size="small"
                            title={<Space><Checkbox checked={selected.includes(shot.seq)} onChange={(event) => void toggleSelected(shot.seq, event.target.checked)} />#{shot.seq} {shot.purpose}</Space>}
                            extra={<Tag>{shot.structure_type}</Tag>}
                          >
                            <Text strong>{shot.theme}</Text>
                            <Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ marginTop: 6 }}>{shot.anchor_paragraph}</Paragraph>
                            <Space wrap style={{ marginBottom: 8 }}>
                              <Tag color="orange">动作：{shot.character_action}</Tag>
                              {shot.chinese_labels.map((label) => <Tag key={label}>{label}</Tag>)}
                            </Space>
                            <Button size="small" icon={<RobotOutlined />} onClick={() => void generatePromptForShot(shot)} style={{ marginBottom: 8 }}>
                              重新生成提示词
                            </Button>
                            <TextArea
                              value={prompt}
                              onChange={(event) => void updatePrompt(shot.seq, event.target.value)}
                              onBlur={() => void savePrompt(shot.seq)}
                              autoSize={{ minRows: 4, maxRows: 8 }}
                              placeholder="拆文完成后会自动生成提示词，可在这里修改后再生成图片。"
                            />
                            <Button
                              block
                              type={asset ? "default" : "primary"}
                              icon={<PictureOutlined />}
                              loading={busy}
                              disabled={!prompt.trim()}
                              onClick={() => void generateShot(shot)}
                              style={{ marginTop: 10 }}
                            >
                              {asset ? "重新生成图片" : "生成图片"}
                            </Button>
                            {asset ? (
                              <>
                                <Divider style={{ margin: "12px 0" }} />
                                <Image src={asset.file_path} style={{ width: "100%", aspectRatio: "3 / 4", objectFit: "cover" }} />
                                <Tag color="green" style={{ marginTop: 8 }}>已自动保存：{asset.model}</Tag>
                              </>
                            ) : (
                              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未生成图片" style={{ marginTop: 12 }} />
                            )}
                          </Card>
                        </Col>
                      );
                    })}
                  </Row>
                </Space>
              )}
            </Col>
          </Row>
        )}
      </Card>

      <IllustrationQuotaCard quotas={quotas} />
    </div>
  );
}
