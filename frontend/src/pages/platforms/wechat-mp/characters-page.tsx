import { CheckOutlined, PlusOutlined, ReloadOutlined, UploadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Form, Input, Row, Space, Spin, Tag, Typography, Upload } from "antd";
import { useEffect, useState } from "react";

import { PageHeader } from "../../../components/layout/app-shell";
import { confirmWechatMpCharacterView, createWechatMpIllustrationCharacter, fetchWechatMpIllustrationCharacters, generateWechatMpCharacterView, uploadWechatMpCharacterView } from "../../../lib/api";
import type { WechatMpIllustrationCharacter } from "../../../types";
import { WechatMpLayout } from "./wechat-mp-layout";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

export function WechatMpCharactersPage() {
  const [form] = Form.useForm<{ name: string; prompt: string }>();
  const [characters, setCharacters] = useState<WechatMpIllustrationCharacter[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [viewBusy, setViewBusy] = useState<string | null>(null);

  async function loadCharacters() {
    setLoading(true);
    setError(null);
    try {
      setCharacters(await fetchWechatMpIllustrationCharacters());
    } catch {
      setError("公众号形象库加载失败。");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCharacters();
  }, []);

  async function submit(values: { name: string; prompt: string }) {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createWechatMpIllustrationCharacter({
        name: values.name.trim(),
        prompt: values.prompt.trim(),
      });
      setCharacters((items) => [...items, created]);
      form.resetFields();
      setNotice(`形象「${created.name}」已创建，可在写作页选择使用。`);
    } catch {
      setError("自定义形象创建失败。");
    } finally {
      setSaving(false);
    }
  }

  async function refreshAfterView(action: () => Promise<unknown>, label: string) {
    setViewBusy(label);
    setError(null);
    try {
      await action();
      await loadCharacters();
      setNotice(`${label}已完成，请继续确认其余视图。`);
    } catch {
      setError(`${label}失败，请检查图片模型或文件格式。`);
    } finally {
      setViewBusy(null);
    }
  }

  return (
    <WechatMpLayout>
      <PageHeader
        eyebrow="WeChat MP / Characters"
        title="公众号形象"
        description="管理公众号配图主角形象。可以自己写提示词，生成文章配图提示词时会套用对应形象设定。"
        action={<Button icon={<ReloadOutlined />} onClick={() => void loadCharacters()}>刷新</Button>}
      />
      {error && <Alert type="error" message={error} showIcon closable onClose={() => setError(null)} style={{ marginBottom: 16 }} />}
      {notice && <Alert type="success" message={notice} showIcon closable onClose={() => setNotice(null)} style={{ marginBottom: 16 }} />}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card title="新增形象">
            <Form form={form} layout="vertical" onFinish={(values) => void submit(values)}>
              <Form.Item name="name" label="形象名称" rules={[{ required: true, message: "请填写形象名称" }]}>
                <Input placeholder="如：小护士、验收小猫、产品经理兔" />
              </Form.Item>
              <Form.Item name="prompt" label="自定义形象提示词" rules={[{ required: true, message: "请填写形象提示词" }]}>
                <TextArea rows={8} placeholder="描述外观、性格、固定风格、动作边界和禁止项。例如：圆脸小护士，蓝白制服，手绘科普风，不写实，不复杂背景。" />
              </Form.Item>
              <Button type="primary" icon={<PlusOutlined />} htmlType="submit" loading={saving}>新增形象</Button>
            </Form>
          </Card>
        </Col>
        <Col xs={24} lg={16}>
          <Card title="形象库">
            {loading ? <Spin /> : characters.length === 0 ? (
              <Empty description="暂无公众号形象" />
            ) : (
              <Row gutter={[12, 12]}>
                {characters.map((character) => (
                  <Col xs={24} md={12} key={character.skill_name}>
                    <Card size="small" title={character.name} extra={<Space><Tag color={character.is_available ? "green" : "gold"}>{character.is_available ? "四视图已确认" : "待确认四视图"}</Tag><Tag color={character.is_builtin ? "blue" : "green"}>{character.is_builtin ? "内置" : "自定义"}</Tag></Space>}>
                      <Space direction="vertical" size={8} style={{ width: "100%" }}>
                        <Text code>{character.skill_name}</Text>
                        <Paragraph ellipsis={{ rows: 4, expandable: true, symbol: "展开" }} style={{ marginBottom: 0 }}>
                          {character.prompt || "系统内置形象，无自定义提示词。"}
                        </Paragraph>
                        {character.id && <Row gutter={[8, 8]}>
                          {(character.views ?? []).map((view) => {
                            const key = `${character.id}-${view.view}`;
                            const busy = viewBusy === key;
                            return <Col span={12} key={view.view}>
                              <Card size="small" title={view.view === "front" ? "正面" : view.view === "back" ? "背面" : view.view === "left" ? "左侧" : "右侧"} extra={<Tag color={view.status === "confirmed" ? "green" : "default"}>{view.status === "confirmed" ? "已确认" : "待确认"}</Tag>}>
                                {view.public_url ? <img src={view.public_url} alt={`${character.name}${view.view}`} style={{ width: "100%", height: 100, objectFit: "contain", background: "#111" }} /> : <Text type="secondary">尚无视图</Text>}
                                <Space wrap style={{ marginTop: 8 }}>
                                  <Button size="small" loading={busy} onClick={() => void refreshAfterView(() => generateWechatMpCharacterView(character.id!, view.view), key)}>{view.public_url ? "重新生成" : "生成"}</Button>
                                  <Upload accept="image/jpeg,image/png,image/webp" showUploadList={false} beforeUpload={(file) => { void refreshAfterView(() => uploadWechatMpCharacterView(character.id!, view.view, file), key); return false; }}><Button size="small" icon={<UploadOutlined />}>替换</Button></Upload>
                                  <Button size="small" icon={<CheckOutlined />} disabled={!view.public_url || view.status === "confirmed"} onClick={() => void refreshAfterView(() => confirmWechatMpCharacterView(character.id!, view.view), key)}>确认</Button>
                                </Space>
                              </Card>
                            </Col>;
                          })}
                        </Row>}
                      </Space>
                    </Card>
                  </Col>
                ))}
              </Row>
            )}
          </Card>
        </Col>
      </Row>
    </WechatMpLayout>
  );
}
