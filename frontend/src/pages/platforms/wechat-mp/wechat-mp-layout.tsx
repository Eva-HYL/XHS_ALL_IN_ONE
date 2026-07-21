import { AppstoreOutlined, EditOutlined, PictureOutlined, SendOutlined, TeamOutlined } from "@ant-design/icons";
import { Segmented, Space } from "antd";
import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";

const sections = [
  { path: "/platforms/wechat-mp/dashboard", label: "总览", icon: <AppstoreOutlined /> },
  { path: "/platforms/wechat-mp/accounts", label: "账号", icon: <TeamOutlined /> },
  { path: "/platforms/wechat-mp/writer", label: "写作", icon: <EditOutlined /> },
  { path: "/platforms/wechat-mp/assets", label: "素材", icon: <PictureOutlined /> },
  { path: "/platforms/wechat-mp/publish", label: "发布", icon: <SendOutlined /> },
];

export function WechatMpLayout({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const selected = sections.find((section) => location.pathname.startsWith(section.path))?.path ?? sections[0].path;

  return (
    <div style={{ maxWidth: 1440, margin: "0 auto" }}>
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Segmented
          value={selected}
          onChange={(value) => navigate(String(value))}
          options={sections.map((section) => ({ value: section.path, label: <Space size={6}>{section.icon}{section.label}</Space> }))}
          block
        />
        {children}
      </Space>
    </div>
  );
}
