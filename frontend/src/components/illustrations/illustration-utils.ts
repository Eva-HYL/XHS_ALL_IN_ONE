import type { IllustrationCharacter, IllustrationShot } from "../../types";

export function slugify(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, "-") || `character-${Date.now()}`;
}

export function isCharacterConfirmed(character: IllustrationCharacter): boolean {
  return character.reference_image_asset_ids.length > 0;
}

export function buildIllustrationPrompt(shot: IllustrationShot, character: IllustrationCharacter): string {
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
