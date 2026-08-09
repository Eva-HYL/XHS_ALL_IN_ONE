import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  hasWritingSource,
  hasMaterialSelectionChanged,
  isWritingBriefReady,
  isWritingBriefStale,
  WECHAT_WRITER_STEPS,
  writingSourceFingerprint,
} from "../src/pages/platforms/wechat-mp/writing-flow.ts";

test("writing source accepts either selected materials or a nonblank idea", () => {
  assert.equal(hasWritingSource([1], ""), true);
  assert.equal(hasWritingSource([], " 一句话想法 "), true);
  assert.equal(hasWritingSource([], "   "), false);
});

test("source fingerprint preserves confirmed material order and normalizes the idea", () => {
  assert.equal(writingSourceFingerprint([3, 1], "  复习重点  "), "3,1|复习重点");
});

test("clearing a previously confirmed material selection remains a confirmable change", () => {
  assert.equal(hasMaterialSelectionChanged([], [7]), true);
  assert.equal(hasMaterialSelectionChanged([7], [7]), false);
});

test("brief readiness requires an editable title and topic", () => {
  assert.equal(isWritingBriefReady("标题", "主题"), true);
  assert.equal(isWritingBriefReady("", "主题"), false);
  assert.equal(isWritingBriefReady("标题", "  "), false);
});

test("a prepared brief becomes stale only when its confirmed source changes", () => {
  const prepared = writingSourceFingerprint([3, 1], "复习重点");

  assert.equal(isWritingBriefStale(null, [3, 1], "复习重点"), false);
  assert.equal(isWritingBriefStale(prepared, [3, 1], " 复习重点 "), false);
  assert.equal(isWritingBriefStale(prepared, [3, 2], "复习重点"), true);
  assert.equal(isWritingBriefStale(prepared, [3, 1], "换一个角度"), true);
});

test("writer navigation contains the five simplified stages", () => {
  assert.deepEqual(WECHAT_WRITER_STEPS, [
    "选择素材与写作要求",
    "编辑与预览",
    "生成提示词",
    "编辑提示词并生图",
    "同步草稿/发布",
  ]);
});

test("writer page uses the material-first brief entry and removes the redundant generation stage", () => {
  const writerSource = readFileSync(
    new URL("../src/pages/platforms/wechat-mp/writer-page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(writerSource, /使用选中素材/);
  assert.match(writerSource, /智能补全写作简报/);
  assert.match(writerSource, /prepareWechatMpWritingBrief/);
  assert.doesNotMatch(writerSource, /下一步：生成文章/);
  assert.doesNotMatch(writerSource, /2\. 生成文章/);
});
