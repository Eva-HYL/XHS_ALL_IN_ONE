import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Form, Input, Row, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { PageHeader } from "../../../components/layout/app-shell";
import { createWechatMpIllustrationCharacter, fetchWechatMpIllustrationCharacters } from "../../../lib/api";
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
                    <Card size="small" title={character.name} extra={<Tag color={character.is_builtin ? "blue" : "green"}>{character.is_builtin ? "内置" : "自定义"}</Tag>}>
                      <Space direction="vertical" size={8} style={{ width: "100%" }}>
                        <Text code>{character.skill_name}</Text>
                        <Paragraph ellipsis={{ rows: 4, expandable: true, symbol: "展开" }} style={{ marginBottom: 0 }}>
                          {character.prompt || "系统内置形象，无自定义提示词。"}
                        </Paragraph>
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
