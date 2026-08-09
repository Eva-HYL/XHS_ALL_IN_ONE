import { ArrowLeftOutlined, ArrowRightOutlined, EditOutlined, PictureOutlined, SaveOutlined, SendOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Input, Row, Select, Space, Steps, Tag, Tooltip, Typography } from "antd";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import {
  createWechatMpArticle,
  fetchModelConfigs,
  fetchWechatMpArticle,
  fetchWechatMpArticles,
  fetchWechatMpAssets,
  fetchWechatMpImageCostEstimate,
  fetchWechatMpIllustrationCharacters,
  fetchWechatMpMaterials,
  fetchWechatMpPrompts,
  generateWechatMpCover,
  generateWechatMpImage,
  generateWechatMpPrompts,
  ignoreWechatMpPrompt,
  prepareWechatMpWritingBrief,
  regenerateWechatMpArticle,
  regenerateWechatMpPrompt,
  restoreWechatMpPrompt,
  updateWechatMpArticle,
  updateWechatMpPrompt,
} from "../../../lib/api";
import type {
  ModelConfig,
  WechatMpArticle,
  WechatMpAsset,
  WechatMpImageCostEstimate,
  WechatMpImagePrompt,
  WechatMpIllustrationCharacter,
  WechatMpMaterial,
  WechatMpPromptAnalysis,
  WechatMpWritingBrief,
} from "../../../types";
import {
  appendUniquePromptIds,
  isQueueLifecycleCurrent,
  nextQueuedPromptId,
  removeQueuedPromptId,
  resetImageQueueForArticle,
  selectEligibleImagePromptIds,
} from "./image-queue";
import type { ImageQueueLifecycle } from "./image-queue";
import { WechatMpLayout } from "./wechat-mp-layout";
import {
  hasWritingSource,
  hasMaterialSelectionChanged,
  isWritingBriefReady,
  isWritingBriefStale,
  WECHAT_WRITER_STEPS,
  writingSourceFingerprint,
} from "./writing-flow";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;
const DEFAULT_SKILL = "xiaomao-illustrations";
const ARTICLE_RECOVERY_DELAY_MS = 12000;
const ARTICLE_RECOVERY_POLL_MS = 5000;
const ARTICLE_RECOVERY_CREATED_AT_MARGIN_MS = 30000;

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
    asset.status === "generated"
    && asset.article_id === articleId
    && (asset.role === "cover" || (asset.prompt_id !== null && activePromptIds.has(asset.prompt_id)))
  );
}

function replaceCharacterMention(text: string, name: string): string {
  const scene = text.replace(/^[ \t]*主角[：:][ \t]*@[^\s@,，。；;：:（）()]+[ \t]*$/gm, "").trim();
  return `主角：@${name}${scene ? `\n${scene}` : ""}`;
}

function resolveCharacterMention(
  characters: WechatMpIllustrationCharacter[],
  characterId: number | null | undefined,
  skillName: string | null | undefined,
  text: string | null | undefined,
): WechatMpIllustrationCharacter | null {
  if (skillName === "none") return null;
  if (characterId !== null && characterId !== undefined) {
    const character = characters.find((item) => item.id === characterId);
    if (character) return character;
  }
  if (skillName) {
    const character = characters.find((item) => item.skill_name === skillName);
    if (character) return character;
  }
  const mention = text?.match(/^[ \t]*主角[：:][ \t]*@([^\s@,，。；;：:（）()]+)[ \t]*$/m)?.[1];
  return mention ? characters.find((item) => item.name === mention) ?? null : null;
}

export function WechatMpWriterPage() {
  const [params, setParams] = useSearchParams();
  const [article, setArticle] = useState<WechatMpArticle | null>(null);
  const [prompts, setPrompts] = useState<WechatMpImagePrompt[]>([]);
  const [promptAnalysis, setPromptAnalysis] = useState<WechatMpPromptAnalysis | null>(null);
  const [assets, setAssets] = useState<WechatMpAsset[]>([]);
  const [materials, setMaterials] = useState<WechatMpMaterial[]>([]);
  const [characters, setCharacters] = useState<WechatMpIllustrationCharacter[]>([]);
  const [draftMaterialIds, setDraftMaterialIds] = useState<number[]>([]);
  const [selectedMaterialIds, setSelectedMaterialIds] = useState<number[]>([]);
  const [imageModels, setImageModels] = useState<ModelConfig[]>([]);
  const [imageModel, setImageModel] = useState<string | undefined>();
  const [imageEstimate, setImageEstimate] = useState<WechatMpImageCostEstimate | null>(null);
  const [title, setTitle] = useState("");
  const [topic, setTopic] = useState("");
  const [idea, setIdea] = useState("");
  const [reader, setReader] = useState("");
  const [tone, setTone] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [editMarkdown, setEditMarkdown] = useState("");
  const [skill, setSkill] = useState(DEFAULT_SKILL);
  const [busy, setBusy] = useState(false);
  const [briefBusy, setBriefBusy] = useState(false);
  const [briefVisible, setBriefVisible] = useState(false);
  const [briefSourceFingerprint, setBriefSourceFingerprint] = useState<string | null>(null);
  const [briefCost, setBriefCost] = useState<WechatMpWritingBrief["cost_estimate"] | null>(null);
  const [promptBusy, setPromptBusy] = useState(false);
  const [coverBusy, setCoverBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [workflowStep, setWorkflowStep] = useState(0);
  const [activeImagePromptId, setActiveImagePromptId] = useState<number | null>(null);
  const [imageQueue, setImageQueue] = useState<number[]>([]);
  const imageQueueRef = useRef<number[]>([]);
  const imageWorkerRunningRef = useRef(false);
  const imageQueueLifecycleRef = useRef<ImageQueueLifecycle>({ articleId: null, token: 0 });
  const promptSnapshotRef = useRef<WechatMpImagePrompt[]>([]);
  const activePromptArticleIdRef = useRef<number | null>(null);
  const promptGenerationTokenRef = useRef(0);
  const briefGenerationTokenRef = useRef(0);
  const selectedMaterialIdsRef = useRef<number[]>([]);
  const ideaRef = useRef("");
  const articleId = Number(params.get("article"));
  const focusPromptId = Number(params.get("prompt")) || null;

  useLayoutEffect(() => {
    activePromptArticleIdRef.current = articleId || null;
    promptGenerationTokenRef.current += 1;
    briefGenerationTokenRef.current += 1;
    const resetQueue = resetImageQueueForArticle(
      imageQueueRef.current,
      imageQueueLifecycleRef.current,
      articleId || null,
    );
    imageQueueLifecycleRef.current = resetQueue.lifecycle;
    imageQueueRef.current = resetQueue.queue;
    setImageQueue(resetQueue.queue);
    setActiveImagePromptId(null);
    setPrompts([]);
    setPromptAnalysis(null);
    setPromptBusy(false);
    setBriefBusy(false);
  }, [articleId]);

  useEffect(() => {
    promptSnapshotRef.current = prompts;
  }, [prompts]);

  useEffect(() => {
    void fetchModelConfigs("image")
      .then(({ items }) => {
        setImageModels(items);
        setImageModel(items.find((item) => item.is_default)?.model_name ?? items[0]?.model_name);
      })
      .catch(() => setError("图片模型配置加载失败。"));
  }, []);

  useEffect(() => {
    void fetchWechatMpMaterials({ page_size: 100 })
      .then((response) => setMaterials(response.items))
      .catch(() => setError("公众号资料库加载失败。"));
  }, []);

  useEffect(() => {
    void fetchWechatMpIllustrationCharacters()
      .then(setCharacters)
      .catch(() => setError("公众号形象库加载失败。"));
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
        setPromptAnalysis(null);
        setAssets(activeArticleAssets(articleId, loadedPrompts, loadedAssets.items));
        setWorkflowStep(focusPromptId && loadedPrompts.some((prompt) => prompt.id === focusPromptId) ? 3 : loadedPrompts.length > 0 ? 3 : 1);
        if (focusPromptId && loadedPrompts.some((prompt) => prompt.id === focusPromptId)) {
          setNotice(`已定位到 prompt-${focusPromptId}，请生成或重新生成对应正文图片后再同步草稿。`);
        }
      } catch {
        if (!cancelled) setError("文章或提示词加载失败。");
      }
    })();
    return () => { cancelled = true; };
  }, [articleId, focusPromptId]);

  useEffect(() => {
    if (!focusPromptId || workflowStep !== 3) return;
    window.setTimeout(() => {
      document.getElementById(`wechat-prompt-${focusPromptId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 120);
  }, [focusPromptId, workflowStep, prompts.length]);

  function updateIdea(nextIdea: string) {
    ideaRef.current = nextIdea;
    setIdea(nextIdea);
  }

  async function prepareBrief(nextMaterialIds: number[] = selectedMaterialIdsRef.current) {
    const nextIdea = ideaRef.current;
    if (!hasWritingSource(nextMaterialIds, nextIdea)) {
      setError("请先选择素材或输入一句话想法。");
      return;
    }
    const requestFingerprint = writingSourceFingerprint(nextMaterialIds, nextIdea);
    const requestToken = briefGenerationTokenRef.current + 1;
    briefGenerationTokenRef.current = requestToken;
    setBriefBusy(true);
    setError(null);
    try {
      const next = await prepareWechatMpWritingBrief({
        material_ids: nextMaterialIds,
        idea: nextIdea.trim(),
      });
      const currentFingerprint = writingSourceFingerprint(
        selectedMaterialIdsRef.current,
        ideaRef.current,
      );
      if (briefGenerationTokenRef.current !== requestToken || currentFingerprint !== requestFingerprint) return;
      setTitle(next.title);
      setTopic(next.topic);
      setReader(next.target_reader);
      setTone(next.tone);
      setBriefCost(next.cost_estimate);
      setBriefSourceFingerprint(requestFingerprint);
      setBriefVisible(true);
      setNotice("写作简报已自动整理，可修改后直接生成文章。");
    } catch (err) {
      if (briefGenerationTokenRef.current !== requestToken) return;
      setBriefVisible(true);
      setError(errorMessage(err, "写作简报生成失败，当前输入已保留，可重试或手动填写。"));
    } finally {
      if (briefGenerationTokenRef.current === requestToken) setBriefBusy(false);
    }
  }

  function confirmMaterialSelection() {
    const nextMaterialIds = [...draftMaterialIds];
    selectedMaterialIdsRef.current = nextMaterialIds;
    setSelectedMaterialIds(nextMaterialIds);
    if (nextMaterialIds.length > 0) {
      void prepareBrief(nextMaterialIds);
    } else {
      setNotice("未选择素材，可以输入一句话想法后智能补全写作简报。");
    }
  }

  function applyCreatedArticle(next: WechatMpArticle, message: string) {
    setArticle(next);
    setEditTitle(next.title);
    setEditMarkdown(next.markdown_body);
    setParams({ article: String(next.id) });
    setPrompts([]);
    setPromptAnalysis(null);
    setAssets([]);
    setWorkflowStep(1);
    setNotice(message);
  }

  async function recoverCreatedArticle(expectedTitle: string, startedAtMs: number): Promise<boolean> {
    const items = await fetchWechatMpArticles();
    const createdAfter = startedAtMs - ARTICLE_RECOVERY_CREATED_AT_MARGIN_MS;
    const match = items
      .filter((item) => item.title === expectedTitle)
      .filter((item) => !item.created_at || new Date(item.created_at).getTime() >= createdAfter)
      .sort((left, right) => {
        const leftTime = left.created_at ? new Date(left.created_at).getTime() : 0;
        const rightTime = right.created_at ? new Date(right.created_at).getTime() : 0;
        return rightTime - leftTime;
      })[0];
    if (!match) return false;
    const next = await fetchWechatMpArticle(match.id);
    applyCreatedArticle(next, "文章已生成，已自动进入编辑步骤。");
    return true;
  }

  async function recoverRegeneratedArticle(articleId: number, previousRevision: number): Promise<boolean> {
    const next = await fetchWechatMpArticle(articleId);
    if (next.revision <= previousRevision) return false;
    applyCreatedArticle(next, "文章已重新生成，已自动进入编辑步骤。");
    return true;
  }

  async function createArticle() {
    const articleToRegenerate = article;
    const previousRevision = articleToRegenerate?.revision ?? null;
    const expectedTitle = title.trim();
    const expectedTopic = topic.trim();
    if (!hasWritingSource(selectedMaterialIds, idea)) {
      setError("请先选择素材或输入一句话想法。");
      return;
    }
    if (!expectedTitle || !expectedTopic) {
      setError("请先补全文章标题和主题。");
      return;
    }
    const startedAtMs = Date.now();
    let recovered = false;
    let recoveryDelayId: number | undefined;
    let recoveryIntervalId: number | undefined;
    const clearRecoveryTimers = () => {
      if (recoveryDelayId !== undefined) window.clearTimeout(recoveryDelayId);
      if (recoveryIntervalId !== undefined) window.clearInterval(recoveryIntervalId);
    };
    const tryRecover = async () => {
      try {
        const ok = articleToRegenerate && previousRevision !== null
          ? await recoverRegeneratedArticle(articleToRegenerate.id, previousRevision)
          : await recoverCreatedArticle(expectedTitle, startedAtMs);
        if (!ok) return;
        recovered = true;
        clearRecoveryTimers();
        setBusy(false);
      } catch {
        // Recovery is opportunistic; the original create request still owns hard failures.
      }
    };
    setBusy(true);
    setError(null);
    setNotice(articleToRegenerate
      ? "文章重新生成中；完成后将替换当前版本并返回编辑与预览。"
      : "文章生成中；完成后进入编辑与预览。若模型响应较慢，页面会自动检测已生成文章。");
    recoveryDelayId = window.setTimeout(() => {
      recoveryIntervalId = window.setInterval(() => {
        void tryRecover();
      }, ARTICLE_RECOVERY_POLL_MS);
      void tryRecover();
    }, ARTICLE_RECOVERY_DELAY_MS);
    try {
      const payload = {
        title: expectedTitle,
        topic: expectedTopic,
        source_material: idea,
        material_ids: selectedMaterialIds,
        target_reader: reader,
        tone,
        illustration_skill: skill,
      };
      const next = articleToRegenerate
        ? await regenerateWechatMpArticle(articleToRegenerate.id, payload)
        : await createWechatMpArticle(payload);
      if (recovered) return;
      applyCreatedArticle(next, articleToRegenerate
        ? "当前文章已重新生成，微信排版和修订号已刷新。"
        : "文章和微信排版已生成。请检查正文，再进入提示词步骤。");
    } catch (err) {
      try {
        const recoverySucceeded = articleToRegenerate && previousRevision !== null
          ? await recoverRegeneratedArticle(articleToRegenerate.id, previousRevision)
          : await recoverCreatedArticle(expectedTitle, startedAtMs);
        if (recoverySucceeded) {
          recovered = true;
          return;
        }
      } catch {
        // Keep the original create error visible if the recovery lookup also fails.
      }
      setError(errorMessage(err, articleToRegenerate
        ? "文章重新生成失败，原文章和当前输入已保留。"
        : "文章工作流生成失败，请确认文本模型配置。"));
    } finally {
      clearRecoveryTimers();
      if (!recovered) setBusy(false);
    }
  }

  function returnToWritingRequirements() {
    if (!article) return;
    if (!briefVisible) {
      setTitle(article.title);
      setTopic(article.digest || article.title);
      setSkill(article.illustration_skill);
      setBriefVisible(true);
    }
    setWorkflowStep(0);
    setNotice("已返回写作要求；修改后会在同一篇文章上重新生成。");
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
      let refreshed = updated;
      try {
        // Use the persisted HTML so the preview never keeps a stale pre-save layout snapshot.
        refreshed = await fetchWechatMpArticle(article.id);
      } catch {
        // The PATCH has already succeeded; retain its response if a follow-up read is transiently unavailable.
      }
      setArticle(refreshed);
      setEditTitle(refreshed.title);
      setEditMarkdown(refreshed.markdown_body);
      if (bodyChanged) {
        const [loadedPrompts, loadedAssets] = await Promise.all([
          fetchWechatMpPrompts(article.id),
          fetchWechatMpAssets(),
        ]);
        setPrompts(loadedPrompts);
        setPromptAnalysis(null);
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
    const requestedArticleId = article.id;
    const requestToken = ++promptGenerationTokenRef.current;
    const isCurrentPromptRequest = () =>
      requestToken === promptGenerationTokenRef.current && activePromptArticleIdRef.current === requestedArticleId;
    setPromptBusy(true);
    setError(null);
    setNotice("配图提示词生成中；正在分析正文内容。");
    try {
      const result = await generateWechatMpPrompts(article.id, skill);
      if (!isCurrentPromptRequest()) return;
      const refreshedArticle = await fetchWechatMpArticle(article.id);
      if (!isCurrentPromptRequest()) return;
      setPrompts(result.items);
      setPromptAnalysis(result.analysis);
      setArticle(refreshedArticle);
      setWorkflowStep(3);
      setNotice(skill === "none"
        ? "已跳过正文提示词和正文生图费用。"
        : result.items.length === 0
          ? "未发现值得配图的正文内容，本次未生成装饰性配图。"
          : "配图提示词已生成。"
      );
    } catch (err) {
      if (!isCurrentPromptRequest()) return;
      setError(errorMessage(err, "提示词生成失败。"));
    } finally {
      if (isCurrentPromptRequest()) setPromptBusy(false);
    }
  }

  async function regenerate(prompt: WechatMpImagePrompt) {
    setPromptBusy(true);
    setError(null);
    try {
      const updated = await regenerateWechatMpPrompt(prompt.article_id, prompt.id);
      setPrompts((items) => items.map((item) => item.id === updated.id ? updated : item));
      setArticle(await fetchWechatMpArticle(prompt.article_id));
    } catch (err) {
      setError(errorMessage(err, "提示词重新生成失败。"));
    } finally {
      setPromptBusy(false);
    }
  }

  async function ignorePrompt(prompt: WechatMpImagePrompt, scope: "current" | "future_similar") {
    setError(null);
    imageQueueRef.current = removeQueuedPromptId(imageQueueRef.current, prompt.id);
    setImageQueue([...imageQueueRef.current]);
    try {
      const updated = await ignoreWechatMpPrompt(prompt.article_id, prompt.id, scope);
      setPrompts((items) => items.map((item) => item.id === updated.id ? updated : item));
      setArticle(await fetchWechatMpArticle(prompt.article_id));
      setNotice(scope === "future_similar"
        ? "已忽略；后续文章中的相似内容会在生成提示词前跳过。"
        : "已仅忽略当前提示词。"
      );
    } catch (err) {
      setError(errorMessage(err, "忽略提示词失败。"));
    }
  }

  async function restorePrompt(prompt: WechatMpImagePrompt) {
    setError(null);
    try {
      const updated = await restoreWechatMpPrompt(prompt.article_id, prompt.id);
      setPrompts((items) => items.map((item) => item.id === updated.id ? updated : item));
      setArticle(await fetchWechatMpArticle(prompt.article_id));
      setNotice("已恢复当前提示词；长期忽略规则可在规则管理中单独停用。 ");
    } catch (err) {
      setError(errorMessage(err, "恢复提示词失败。"));
    }
  }

  async function selectCharacter(prompt: WechatMpImagePrompt, skillName: string) {
    const character = characters.find((item) => item.skill_name === skillName && item.is_available && item.skill_name !== "none");
    if (!character || character.id === null) return;
    const previousPrompt = prompt;
    const editablePrompt = replaceCharacterMention(prompt.editable_prompt, character.name);
    const nextPrompt = {
      ...prompt,
      editable_prompt: editablePrompt,
      character_id: character.id,
      skill_name: character.skill_name,
    };
    setPrompts((items) => items.map((item) => item.id === prompt.id ? nextPrompt : item));
    try {
      const savedPrompt = await updateWechatMpPrompt(prompt.article_id, prompt.id, {
        editable_prompt: editablePrompt,
        character_id: character.id,
        skill_name: character.skill_name,
      });
      setPrompts((items) => items.map((item) => item.id === savedPrompt.id ? savedPrompt : item));
    } catch (err) {
      setPrompts((items) => items.map((item) => item.id === previousPrompt.id ? previousPrompt : item));
      setError(errorMessage(err, "形象切换失败，请确认该形象的四视图已确认。"));
    }
  }

  const eligibleImagePromptIds = selectEligibleImagePromptIds(
    prompts,
    assets,
    activeImagePromptId,
    imageQueueRef.current,
  );

  async function runImageQueue() {
    if (imageWorkerRunningRef.current) return;
    imageWorkerRunningRef.current = true;
    const workerLifecycle = imageQueueLifecycleRef.current;
    const isCurrentWorker = () => isQueueLifecycleCurrent(workerLifecycle, imageQueueLifecycleRef.current);
    try {
      while (true) {
        const promptId = nextQueuedPromptId(imageQueueRef.current, workerLifecycle, imageQueueLifecycleRef.current);
        if (promptId === null) break;
        setActiveImagePromptId(promptId);
        setImageQueue([...imageQueueRef.current]);
        const prompt = promptSnapshotRef.current.find((item) => item.id === promptId);
        if (!prompt || prompt.article_id !== workerLifecycle.articleId || prompt.skill_name === "none") {
          imageQueueRef.current = removeQueuedPromptId(imageQueueRef.current, promptId);
          setImageQueue([...imageQueueRef.current]);
          continue;
        }
        try {
          const savedPrompt = await updateWechatMpPrompt(prompt.article_id, prompt.id, { editable_prompt: prompt.editable_prompt });
          if (!isCurrentWorker()) return;
          setPrompts((items) => items.map((item) => item.id === savedPrompt.id ? savedPrompt : item));
          const asset = await generateWechatMpImage(prompt.id, { image_model: imageModel, size: "16:9" });
          if (!isCurrentWorker()) return;
          setAssets((items) => [asset, ...items.filter((item) => item.prompt_id !== prompt.id)]);
          setPrompts((items) => items.map((item) => item.id === prompt.id ? { ...item, status: "generated" } : item));
          const refreshedArticle = await fetchWechatMpArticle(prompt.article_id);
          if (!isCurrentWorker()) return;
          setArticle(refreshedArticle);
          setNotice(
            asset.model_name === "deterministic-layout-v1"
              ? `段落 #${prompt.section_id} 结构图已按原文精确渲染，未调用生图模型。`
              : asset.provider_response?.reused_from_asset_id
                ? `段落 #${prompt.section_id} 已复用相似提示词的历史图片，未重复扣除图片生成费用。`
                : `段落 #${prompt.section_id} 正文配图已生成并计入实际费用。`
          );
        } catch {
          if (isCurrentWorker()) {
            setError(`段落 #${prompt.section_id} 图片生成失败，请确认图片模型配置。`);
            setPrompts((items) => items.map((item) => item.id === prompt.id ? { ...item, status: "failed" } : item));
          }
        } finally {
          imageQueueRef.current = removeQueuedPromptId(imageQueueRef.current, promptId);
          if (isCurrentWorker()) setImageQueue([...imageQueueRef.current]);
        }
      }
    } finally {
      imageWorkerRunningRef.current = false;
      if (isCurrentWorker()) {
        setActiveImagePromptId(null);
        setImageQueue([...imageQueueRef.current]);
      }
      if (imageQueueRef.current.length > 0) void runImageQueue();
    }
  }

  function enqueueImage(prompt: WechatMpImagePrompt) {
    if (prompt.skill_name === "none") return;
    if (activeImagePromptId === prompt.id || imageQueueRef.current.includes(prompt.id)) return;
    imageQueueRef.current = appendUniquePromptIds(imageQueueRef.current, [prompt.id]);
    setImageQueue([...imageQueueRef.current]);
    setNotice(imageWorkerRunningRef.current ? "已加入图片生成队列。" : "开始按队列生成正文图片。");
    void runImageQueue();
  }

  function enqueueAllImages() {
    const previousQueueLength = imageQueueRef.current.length;
    imageQueueRef.current = appendUniquePromptIds(imageQueueRef.current, eligibleImagePromptIds);
    const addedCount = imageQueueRef.current.length - previousQueueLength;
    if (addedCount === 0) return;
    setImageQueue([...imageQueueRef.current]);
    setNotice(`已将 ${addedCount} 张正文配图加入串行生成队列。`);
    void runImageQueue();
  }

  async function generateCover() {
    if (!article) return;
    setCoverBusy(true);
    setError(null);
    try {
      const asset = await generateWechatMpCover(article.id, { image_model: imageModel, size: "16:9" });
      setAssets((items) => [asset, ...items.filter((item) => item.role !== "cover")]);
      setArticle(await fetchWechatMpArticle(article.id));
      setNotice("封面已生成并计入实际费用，现在可以同步公众号草稿。");
    } catch {
      setError("封面生成失败，请确认图片模型配置。");
    } finally {
      setCoverBusy(false);
    }
  }

  const estimatedCost = imageEstimate?.pricing_available
    ? `预计每张 ¥${imageEstimate.estimated_yuan}`
    : "当前模型暂无价格估算";
  const coverAsset = assets.find((asset) => asset.role === "cover");
  const inlineImageCount = assets.filter((asset) => asset.role !== "cover").length;
  const stepItems = WECHAT_WRITER_STEPS.map((stepTitle) => ({ title: stepTitle }));
  const sourceReady = hasWritingSource(selectedMaterialIds, idea);
  const briefReady = isWritingBriefReady(title, topic);
  const briefStale = isWritingBriefStale(briefSourceFingerprint, selectedMaterialIds, idea);
  const materialSelectionChanged = hasMaterialSelectionChanged(draftMaterialIds, selectedMaterialIds);
  const selectedMaterials = selectedMaterialIds
    .map((id) => materials.find((item) => item.id === id))
    .filter((item): item is WechatMpMaterial => Boolean(item));
  const coverCharacter = article ? resolveCharacterMention(characters, null, article.illustration_skill, article.cover_brief) : null;
  const characterMentionBadge = coverCharacter ? (
    <Tooltip title={<div><strong>{coverCharacter.name}</strong><div>{coverCharacter.is_available ? "四视图已确认" : "待确认四视图"}</div><div>{coverCharacter.prompt}</div></div>}>
      <Tag color={coverCharacter.is_available ? "blue" : "gold"}>
        主角：@{coverCharacter.name}
      </Tag>
    </Tooltip>
  ) : null;

  return <WechatMpLayout>
    <PageHeader eyebrow="WeChat MP / Writer" title="文章写作" description="先确定素材或想法，五步完成公众号文章、配图和发布。" />
    <Steps current={workflowStep} size="small" items={stepItems} style={{ marginBottom: 16 }} />
    {error && <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} style={{ marginBottom: 16 }} />}
    {notice && <Alert type="success" message={notice} showIcon closable onClose={() => setNotice(null)} style={{ marginBottom: 16 }} />}

    {workflowStep === 0 && <Card title="1. 选择素材与写作要求" style={{ marginBottom: 16 }}>
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Card
          size="small"
          title="先选写作素材（可选）"
          extra={<Link to="/platforms/wechat-mp/assets">管理资料库</Link>}
          style={{ borderColor: "rgba(22, 119, 255, 0.35)" }}
        >
          <Paragraph type="secondary">可以选择一份或多份资料；确认整组选项后，系统只调用一次模型自动整理标题等内容。</Paragraph>
          <Select
            mode="multiple"
            allowClear
            showSearch
            optionFilterProp="label"
            value={draftMaterialIds}
            onChange={setDraftMaterialIds}
            placeholder="从资料库选择素材（可多选）"
            style={{ width: "100%" }}
            options={materials.map((item) => ({
              value: item.id,
              label: `${item.title} · ${item.usage_status === "used" ? `已写过 ${item.used_article_count} 篇` : "未使用"}`,
            }))}
          />
          {materials.length === 0 && <Text type="secondary" style={{ display: "block", marginTop: 8 }}>暂无资料，也可以直接输入想法开始写作。</Text>}
          <Space style={{ marginTop: 12 }} wrap>
            <Button
              type="primary"
              loading={briefBusy}
              disabled={!materialSelectionChanged || briefBusy || busy}
              onClick={confirmMaterialSelection}
            >
              {draftMaterialIds.length > 0 ? `使用选中素材（${draftMaterialIds.length}）` : "确认不使用素材"}
            </Button>
            {selectedMaterials.map((item) => <Tag key={item.id} color="blue">{item.title}</Tag>)}
          </Space>
        </Card>

        <Card size="small" title={selectedMaterialIds.length > 0 ? "补充写作角度（可选）" : "没有素材？直接写一句想法"}>
          <TextArea
            value={idea}
            onChange={(event) => updateIdea(event.target.value)}
            placeholder={selectedMaterialIds.length > 0 ? "例如：突出考试中的易错关系" : "例如：写一篇关于第一本推理小说如何影响我的文章"}
            rows={3}
          />
          <Space style={{ marginTop: 12 }} wrap>
            <Button
              icon={<EditOutlined />}
              loading={briefBusy}
              disabled={!sourceReady || briefBusy || busy}
              onClick={() => void prepareBrief(selectedMaterialIds)}
            >
              {briefVisible ? "重新整理写作简报" : "智能补全写作简报"}
            </Button>
            <Button disabled={!sourceReady || briefBusy || busy} onClick={() => setBriefVisible(true)}>手动填写简报</Button>
          </Space>
        </Card>

        {briefBusy && <Alert type="info" showIcon message="正在根据当前素材与想法整理写作简报…" />}
        {briefVisible && <Card
          size="small"
          title="可编辑写作简报"
          extra={<Tag color={briefStale ? "gold" : briefReady ? "green" : "default"}>{briefStale ? "来源已变化" : briefReady ? "可以生成" : "待补全"}</Tag>}
        >
          {briefStale && <Alert type="warning" showIcon message="写作来源已变化，当前人工修改不会被覆盖；需要时请重新整理简报。" style={{ marginBottom: 12 }} />}
          <Row gutter={[12, 12]}>
            <Col xs={24} md={12}><Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="文章标题" /></Col>
            <Col xs={24} md={12}>
              <Select
                value={skill}
                onChange={setSkill}
                style={{ width: "100%" }}
                options={(characters.length ? characters : [
                  { name: "小猫插画", skill_name: DEFAULT_SKILL, prompt: "", is_builtin: true },
                  { name: "none（跳过正文配图）", skill_name: "none", prompt: "", is_builtin: true },
                ] as WechatMpIllustrationCharacter[]).map((character) => ({
                  value: character.skill_name,
                  label: `${character.name}${character.is_available === false ? "（待确认四视图）" : character.is_builtin ? "" : "（自定义）"}`,
                  disabled: character.skill_name !== "none" && character.is_available === false,
                }))}
              />
              <Text type="secondary" style={{ display: "block", marginTop: 6 }}>
                需要新增或调整形象，请到 <Link to="/platforms/wechat-mp/characters">形象管理</Link>。
              </Text>
            </Col>
            <Col span={24}><TextArea value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="文章主题与核心观点" rows={3} /></Col>
            <Col xs={24} md={12}><Input value={reader} onChange={(event) => setReader(event.target.value)} placeholder="目标读者（可选）" /></Col>
            <Col xs={24} md={12}><Input value={tone} onChange={(event) => setTone(event.target.value)} placeholder="语气风格（可选）" /></Col>
          </Row>
          <Space direction="vertical" size={8} style={{ width: "100%", marginTop: 16 }}>
            {briefCost && <Text type="secondary">本次写作简报实际费用：¥{briefCost.total_yuan}，已计入账单中心。</Text>}
            <Text type="secondary">正文会使用已确认素材和这份简报生成；微信安全排版本身不收模型费。</Text>
            <Button
              type="primary"
              icon={<EditOutlined />}
              loading={busy}
              disabled={!sourceReady || !briefReady || briefBusy || busy}
              onClick={() => void createArticle()}
            >
              {article ? "重新生成文章" : "生成文章"}
            </Button>
          </Space>
        </Card>}
      </Space>
    </Card>}

    {article && workflowStep === 1 && <Card title="2. 编辑与预览" extra={<Space><Tag>修订 {article.revision}</Tag><Tag>{article.status}</Tag></Space>}>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} placeholder="公众号标题" />
            <TextArea value={editMarkdown} onChange={(event) => setEditMarkdown(event.target.value)} rows={16} placeholder="Markdown 正文" />
            <Space wrap>
              <Button icon={<ArrowLeftOutlined />} disabled={busy} onClick={returnToWritingRequirements}>返回修改写作要求</Button>
              <Button type="primary" icon={<SaveOutlined />} loading={busy} onClick={() => void saveArticle()}>保存标题与正文</Button>
              <Button icon={<ArrowRightOutlined />} onClick={() => setWorkflowStep(2)}>下一步：生成提示词</Button>
            </Space>
          </Space>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="微信排版预览" size="small">
            <Text strong>{article.title}</Text>
            <Paragraph type="secondary">{article.digest}</Paragraph>
            <Paragraph type="secondary">累计实际模型费用（正文、提示词、封面、配图）：¥{String(article.cost_estimate.total_yuan ?? "0.0000")}，共 {String(article.cost_estimate.calls ?? 0)} 次调用</Paragraph>
            <div style={{ borderTop: "1px solid #eee", paddingTop: 12 }} dangerouslySetInnerHTML={{ __html: article.html_body }} />
          </Card>
        </Col>
      </Row>
    </Card>}

    {article && workflowStep === 2 && <Card title="3. 生成配图提示词">
        <Paragraph>文章已排版完成。现在分析正文内容，生成值得配图的提示词。</Paragraph>
        <Paragraph>当前技能：<Text code>{skill}</Text>。<Text code>none</Text> 会跳过正文提示词和正文图片；公众号封面仍可生成。</Paragraph>
        <Paragraph type="secondary">提示词预估：非 <Text code>none</Text> 技能按文本模型 token 计费；<Text code>none</Text> 不产生正文提示词和正文生图费用。</Paragraph>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => setWorkflowStep(1)}>返回编辑文章</Button>
          <Button type="primary" icon={<PictureOutlined />} loading={promptBusy} onClick={() => void makePrompts()}>{prompts.length > 0 ? "重新生成提示词" : "生成提示词"}</Button>
        </Space>
      </Card>}

    {article && workflowStep === 3 && <Card title="4. 编辑提示词并生成图片">
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          {promptAnalysis && <Alert
            type="info"
            showIcon
            message={`本次分析：原文 ${promptAnalysis.source_blocks} 段，过滤 ${promptAnalysis.filtered_blocks} 段，复用 ${promptAnalysis.reused_prompts} 条，模型调用 ${promptAnalysis.model_calls} 次，Token ${promptAnalysis.input_tokens + promptAnalysis.output_tokens}。`}
          />}
          <Select placeholder="使用后端默认图片模型" allowClear value={imageModel} onChange={setImageModel} options={imageModels.map((model) => ({ value: model.model_name, label: `${model.name}${model.is_default ? "（默认）" : ""}` }))} />
          <Text type="secondary">{estimatedCost}；执行后会写入上方累计实际费用。</Text>
          <Button
            type="primary"
            icon={<PictureOutlined />}
            disabled={eligibleImagePromptIds.length === 0}
            onClick={enqueueAllImages}
          >
            {activeImagePromptId !== null || imageQueue.length > 0
              ? `正在按队列生成（剩余 ${imageQueue.length}）`
              : `一键生成全部正文图片（${eligibleImagePromptIds.length}）`}
          </Button>
          <Card size="small" title="公众号封面" extra={<Tag>{coverAsset ? "已生成" : "未生成"}</Tag>}>
            <Row gutter={[16, 12]} align="stretch">
              <Col xs={24} lg={15}>
                <Text strong>封面提示词</Text>
                {characterMentionBadge && <div style={{ marginTop: 8 }}>{characterMentionBadge}</div>}
                <TextArea value={article.cover_brief || "暂无封面提示词"} readOnly rows={5} style={{ marginTop: 8 }} />
                <Space style={{ marginTop: 8 }} wrap>
                  <Button type="primary" icon={<PictureOutlined />} loading={coverBusy} onClick={() => void generateCover()}>
                    {coverAsset ? "重新生成 16:9 公众号封面" : "生成 16:9 公众号封面"}
                  </Button>
                  <Text type="secondary">封面生成只使用上方封面提示词，不会重新生成正文配图提示词。</Text>
                </Space>
              </Col>
              <Col xs={24} lg={9}>
                <Card size="small" title="封面预览" styles={{ body: { padding: 8 } }}>
                  {coverAsset ? (
                    <img src={coverAsset.public_url} alt="公众号封面" style={{ width: "100%", aspectRatio: "16 / 9", objectFit: "cover", display: "block", borderRadius: 6 }} />
                  ) : (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还未生成封面" />
                  )}
                </Card>
              </Col>
            </Row>
          </Card>
          {prompts.length === 0 ? <Empty description={skill === "none" ? "已跳过正文提示词和正文生图费用。" : "未发现值得配图的正文内容，本次未生成装饰性配图。"} /> : prompts.map((prompt) =>
            {
              const isGenerating = activeImagePromptId === prompt.id;
              const isQueued = !isGenerating && imageQueue.includes(prompt.id);
              const promptAsset = assets.find((asset) => asset.prompt_id === prompt.id && asset.role !== "cover");
              const imageButtonText = isGenerating
                ? "生成中"
                : isQueued
                  ? "排队中"
                  : promptAsset || prompt.status === "generated"
                    ? "重新生成正文图片"
                    : "生成正文图片";
              const character = resolveCharacterMention(characters, prompt.character_id, prompt.skill_name, prompt.editable_prompt);
              const isIgnored = prompt.status === "ignored";
              const visualPlan = prompt.visual_plan as {
                kind?: string;
                columns?: string[];
                rows?: Array<{ label: string; values: string[] }>;
                nodes?: string[];
                relations?: Array<{ from: string; to: string; label: string }>;
              } | undefined;
              const characterMentionBadge = character ? (
                <Tooltip title={<div><strong>{character.name}</strong><div>{character.is_available ? "四视图已确认" : "待确认四视图"}</div><div>{character.prompt}</div></div>}>
                  <Tag color={character.is_available ? "blue" : "gold"}>
                    主角：@{character.name}
                  </Tag>
                </Tooltip>
              ) : null;
              return <Card
                id={`wechat-prompt-${prompt.id}`}
                key={prompt.id}
                size="small"
                title={`段落 #${prompt.section_id}`}
                extra={<Space><Tag>{isGenerating ? "generating" : isQueued ? "queued" : prompt.status}</Tag>{isQueued && <Text type="secondary">排队中</Text>}</Space>}
                style={focusPromptId === prompt.id ? { borderColor: "#faad14", boxShadow: "0 0 0 1px rgba(250,173,20,0.45)" } : undefined}
              >
              <Row gutter={[16, 12]}>
                <Col xs={24} lg={15}>
                  {characterMentionBadge && <div style={{ marginBottom: 8 }}>{characterMentionBadge}</div>}
                  <TextArea value={prompt.editable_prompt} onChange={(event) => setPrompts((items) => items.map((item) => item.id === prompt.id ? { ...item, editable_prompt: event.target.value } : item))} rows={5} />
                  {visualPlan?.kind && (
                    <Card size="small" title={`视觉规划 · ${visualPlan.kind}`} style={{ marginTop: 8 }}>
                      {visualPlan.nodes?.length ? <Text>{visualPlan.nodes.join(" → ")}</Text> : null}
                      {visualPlan.columns?.length ? <Text strong>{visualPlan.columns.join(" / ")}</Text> : null}
                      {visualPlan.rows?.map((row) => <div key={row.label}><Text type="secondary">{row.label}：</Text>{row.values.join(" ｜ ")}</div>)}
                      {visualPlan.relations?.map((relation) => <div key={`${relation.from}-${relation.to}`}><Tag color="blue">{relation.from} → {relation.to}</Tag>{relation.label}</div>)}
                    </Card>
                  )}
                  <Space style={{ marginTop: 8 }} wrap>
                    <Select
                      size="small"
                      placeholder="@已确认形象"
                      style={{ minWidth: 150 }}
                      value={undefined}
                      options={characters.filter((character) => character.is_available && character.skill_name !== "none").map((character) => ({ value: character.skill_name, label: `@${character.name}` }))}
                      onChange={(skillName) => skillName && void selectCharacter(prompt, skillName)}
                    />
                    {isIgnored ? (
                      <Button onClick={() => void restorePrompt(prompt)}>恢复当前提示词</Button>
                    ) : (
                      <>
                        <Button onClick={() => void regenerate(prompt)} loading={promptBusy}>重新生成提示词</Button>
                        <Button danger onClick={() => void ignorePrompt(prompt, "current")}>只忽略本条</Button>
                        <Button danger type="primary" onClick={() => void ignorePrompt(prompt, "future_similar")}>以后忽略类似内容</Button>
                      </>
                    )}
                    <Button
                      type="primary"
                      icon={<PictureOutlined />}
                      disabled={isIgnored || prompt.skill_name === "none" || isGenerating || isQueued}
                      loading={isGenerating}
                      onClick={() => enqueueImage(prompt)}
                    >
                      {imageButtonText}
                    </Button>
                  </Space>
                  <Text type="secondary" style={{ display: "block", marginTop: 8 }}>提示词会自动保存在当前文章下；点击生成图片前会先同步最新修改。</Text>
                </Col>
                <Col xs={24} lg={9}>
                  <Card size="small" title="段落配图预览" styles={{ body: { padding: 8 } }}>
                    {promptAsset ? (
                      <img src={promptAsset.public_url} alt="公众号正文配图" style={{ width: "100%", aspectRatio: "16 / 9", objectFit: "cover", display: "block", borderRadius: 6 }} />
                    ) : (
                      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={prompt.skill_name === "none" ? "none 模式不生成正文图" : "还未生成图片"} />
                    )}
                  </Card>
                </Col>
              </Row>
            </Card>;
            }
          )}
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => setWorkflowStep(2)}>返回生成提示词</Button>
            <Button type="primary" icon={<ArrowRightOutlined />} onClick={() => setWorkflowStep(4)}>下一步：同步草稿/发布</Button>
          </Space>
        </Space>
      </Card>}

    {article && workflowStep === 4 && <Card title="5. 同步草稿与发布">
        <Paragraph>写作流程已完成。发布前需要至少生成封面；如果正文仍有未生成占位符，同步草稿时会提示具体缺少的 prompt。</Paragraph>
        <Space wrap>
          <Tag color={coverAsset ? "green" : "orange"}>{coverAsset ? "封面已生成" : "还未生成封面"}</Tag>
          <Tag>{inlineImageCount} 张正文图</Tag>
          <Tag>{prompts.length} 条提示词</Tag>
        </Space>
        <div style={{ marginTop: 16 }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => setWorkflowStep(3)}>返回生图</Button>
            <Button icon={<SendOutlined />} href={`/platforms/wechat-mp/publish?article=${article.id}`}>前往发布中心</Button>
          </Space>
        </div>
      </Card>}
  </WechatMpLayout>;
}
