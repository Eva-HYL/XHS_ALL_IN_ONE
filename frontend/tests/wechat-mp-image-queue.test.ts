import assert from "node:assert/strict";
import test from "node:test";

import {
  appendUniquePromptIds,
  createNextQueueLifecycle,
  isQueueLifecycleCurrent,
  nextQueuedPromptId,
  removeQueuedPromptId,
  resetImageQueueForArticle,
  selectEligibleImagePromptIds,
} from "../src/pages/platforms/wechat-mp/image-queue.ts";

const prompt = (
  id: number,
  status: string = "prompt_ready",
  skillName: string = "xiaomao-illustrations",
) => ({ id, article_id: 10, status, skill_name: skillName });

test("selectEligibleImagePromptIds preserves prompt order and filters ineligible status, skill, assets, active, and queued IDs", () => {
  const prompts = [
    prompt(11),
    prompt(12, "failed"),
    prompt(13, "generated"),
    prompt(14, "ignored"),
    prompt(15, "prompt_ready", "none"),
    prompt(16),
    prompt(17),
    prompt(18),
  ];
  const assets = [
    { prompt_id: 16, role: "inline" },
    { prompt_id: 999, role: "cover" },
  ];

  assert.deepEqual(selectEligibleImagePromptIds(prompts, assets, 17, [18]), [11, 12]);
});

test("appendUniquePromptIds deduplicates against live queue state and duplicate candidates", () => {
  assert.deepEqual(appendUniquePromptIds([21, 22], [22, 23, 23, 24]), [21, 22, 23, 24]);
});

test("removeQueuedPromptId removes the active prompt by identity without dropping its successor", () => {
  const queueAfterActiveIgnore = removeQueuedPromptId([31, 32, 33], 31);
  const queueAfterWorkerFinally = removeQueuedPromptId(queueAfterActiveIgnore, 31);

  assert.deepEqual(queueAfterWorkerFinally, [32, 33]);
});

test("a failed item can be removed and the next item remains eligible for serial continuation", () => {
  const lifecycle = createNextQueueLifecycle({ articleId: null, token: 0 }, 10);
  const queueAfterFailure = removeQueuedPromptId([41, 42], 41);

  assert.equal(nextQueuedPromptId(queueAfterFailure, lifecycle, lifecycle), 42);
});

test("article lifecycle changes invalidate old workers and prevent more old work", () => {
  const articleA = createNextQueueLifecycle({ articleId: null, token: 0 }, 10);
  const switched = resetImageQueueForArticle([51, 52], articleA, 20);

  assert.deepEqual(switched.queue, []);
  assert.equal(isQueueLifecycleCurrent(articleA, switched.lifecycle), false);
  assert.equal(nextQueuedPromptId([51, 52], articleA, switched.lifecycle), null);
});

test("a new token invalidates an earlier worker even for the same article ID", () => {
  const firstLoad = createNextQueueLifecycle({ articleId: null, token: 0 }, 10);
  const nextLoad = createNextQueueLifecycle(firstLoad, 10);

  assert.equal(isQueueLifecycleCurrent(firstLoad, nextLoad), false);
});

test("a current-article batch can start after an old in-flight worker is invalidated", () => {
  const articleA = createNextQueueLifecycle({ articleId: null, token: 0 }, 10);
  const articleB = createNextQueueLifecycle(articleA, 20);
  const currentQueue = appendUniquePromptIds([], [61, 62]);

  assert.equal(nextQueuedPromptId(currentQueue, articleA, articleB), null);
  assert.equal(nextQueuedPromptId(currentQueue, articleB, articleB), 61);
});
