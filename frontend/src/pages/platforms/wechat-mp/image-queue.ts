export type ImageQueuePrompt = {
  id: number;
  article_id: number;
  skill_name: string;
  status: string;
};

export type ImageQueueAsset = {
  prompt_id?: number | null;
  role: string;
};

export type ImageQueueLifecycle = {
  articleId: number | null;
  token: number;
};

export function selectEligibleImagePromptIds(
  prompts: readonly ImageQueuePrompt[],
  assets: readonly ImageQueueAsset[],
  activePromptId: number | null,
  queuedPromptIds: readonly number[],
): number[] {
  const completedPromptIds = new Set(
    assets
      .filter((asset) => asset.role !== "cover" && asset.prompt_id !== null && asset.prompt_id !== undefined)
      .map((asset) => asset.prompt_id as number),
  );
  const queuedIds = new Set(queuedPromptIds);

  return prompts
    .filter((prompt) => prompt.status === "prompt_ready" || prompt.status === "failed")
    .filter((prompt) => prompt.skill_name !== "none")
    .filter((prompt) => !completedPromptIds.has(prompt.id))
    .filter((prompt) => prompt.id !== activePromptId && !queuedIds.has(prompt.id))
    .map((prompt) => prompt.id);
}

export function appendUniquePromptIds(queue: readonly number[], candidateIds: readonly number[]): number[] {
  const seen = new Set(queue);
  const nextQueue = [...queue];
  for (const promptId of candidateIds) {
    if (seen.has(promptId)) continue;
    seen.add(promptId);
    nextQueue.push(promptId);
  }
  return nextQueue;
}

export function removeQueuedPromptId(queue: readonly number[], promptId: number): number[] {
  return queue.filter((queuedPromptId) => queuedPromptId !== promptId);
}

export function createNextQueueLifecycle(
  lifecycle: ImageQueueLifecycle,
  articleId: number | null,
): ImageQueueLifecycle {
  return { articleId, token: lifecycle.token + 1 };
}

export function resetImageQueueForArticle(
  _queue: readonly number[],
  lifecycle: ImageQueueLifecycle,
  articleId: number | null,
): { queue: number[]; lifecycle: ImageQueueLifecycle } {
  return {
    queue: [],
    lifecycle: createNextQueueLifecycle(lifecycle, articleId),
  };
}

export function isQueueLifecycleCurrent(
  expected: ImageQueueLifecycle,
  current: ImageQueueLifecycle,
): boolean {
  return expected.articleId === current.articleId && expected.token === current.token;
}

export function nextQueuedPromptId(
  queue: readonly number[],
  workerLifecycle: ImageQueueLifecycle,
  currentLifecycle: ImageQueueLifecycle,
): number | null {
  if (!isQueueLifecycleCurrent(workerLifecycle, currentLifecycle)) return null;
  return queue[0] ?? null;
}
