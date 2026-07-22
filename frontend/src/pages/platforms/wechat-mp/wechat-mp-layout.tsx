import type { ReactNode } from "react";

export function WechatMpLayout({ children }: { children: ReactNode }) {
  return <div style={{ maxWidth: 1440, margin: "0 auto" }}>{children}</div>;
}
