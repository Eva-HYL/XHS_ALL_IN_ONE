export const WECHAT_WRITER_STEPS = [
  "选择素材与写作要求",
  "编辑与预览",
  "生成提示词",
  "编辑提示词并生图",
  "同步草稿/发布",
] as const;

export function hasWritingSource(materialIds: number[], idea: string): boolean {
  return materialIds.length > 0 || idea.trim().length > 0;
}

export function hasMaterialSelectionChanged(draftIds: number[], confirmedIds: number[]): boolean {
  return draftIds.length !== confirmedIds.length
    || draftIds.some((id, index) => id !== confirmedIds[index]);
}

export function writingSourceFingerprint(materialIds: number[], idea: string): string {
  return `${materialIds.join(",")}|${idea.trim()}`;
}

export function isWritingBriefReady(title: string, topic: string): boolean {
  return title.trim().length > 0 && topic.trim().length > 0;
}

export function isWritingBriefStale(
  preparedFingerprint: string | null,
  materialIds: number[],
  idea: string,
): boolean {
  return preparedFingerprint !== null
    && preparedFingerprint !== writingSourceFingerprint(materialIds, idea);
}
