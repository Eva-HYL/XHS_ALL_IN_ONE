import type { PlatformUser } from "../types";

const OWNER_USERNAMES = new Set(["huangyilundada@gmail.com"]);

export function canViewInternalBilling(user: PlatformUser | null): boolean {
  return Boolean(user && (user.id === 1 || OWNER_USERNAMES.has(user.username)));
}
