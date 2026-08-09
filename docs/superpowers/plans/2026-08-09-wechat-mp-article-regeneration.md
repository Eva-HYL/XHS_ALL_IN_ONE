# 公众号文章返回修改与原文重新生成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让公众号文章从编辑预览返回写作要求，并在同一文章 ID 上安全重新生成正文。

**Architecture:** 后端新增文章级 regenerate 接口，复用现有写作模型和素材加载逻辑，在模型成功后原子替换文章并失效旧提示词、当前图片和微信草稿。前端保留写作来源状态，在有文章时把主操作切换为重新生成。

**Tech Stack:** FastAPI、SQLAlchemy、React 19、TypeScript、Ant Design、Pytest、Node test runner。

## Global Constraints

- 仅修改用户 fork 的 `codex/wechat-shotlist-atlas-integration` 分支。
- 文章、素材和形象必须按当前用户校验；跨用户统一返回 404。
- 重新生成保留文章 ID，修订号只增加一次，不创建重复文章。
- 历史 AI 图片文件和资产记录保留；旧当前封面标记为 `stale`。
- 模型失败或事务失败不得覆盖旧文章。
- 正文调用继续记录 `platform="wechat_mp"`、`step="write_article"` 并累计文章费用。

---

### Task 1: 后端同文章重新生成

**Files:**
- Modify: `backend/app/services/wechat_mp_writer_service.py`
- Modify: `backend/app/api/platforms/wechat_mp/articles.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:**
- Consumes: `WechatMpArticleCreateRequest`、`reset_inline_illustrations(...)`、`invalidate_synced_drafts(...)`、`add_article_cost(...)`。
- Produces: `regenerate_wechat_article(*, db, user_id, article, request) -> WechatMpArticle`、`POST /articles/{article_id}/regenerate`。

- [ ] **Step 1: 写失败测试**

增加测试，构造含素材、提示词、正文资产、封面和已同步草稿的文章，调用 regenerate 后断言：响应 200、ID 不变、revision + 1、正文和素材关系替换、旧提示词删除、正文资产 `prompt_id is None`、旧封面 `status == "stale"`、草稿同步 `status == "stale"`、正文用量新增且费用累计。增加跨用户文章返回 404 测试。

- [ ] **Step 2: 运行测试确认 RED**

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py::test_regenerate_wechat_mp_article_replaces_current_revision_and_retires_outputs \
  tests/backend/test_wechat_mp.py::test_regenerate_wechat_mp_article_hides_foreign_article
```

Expected: 路由不存在，测试返回 405 或 404。

- [ ] **Step 3: 提取模型结果准备函数并实现原位更新**

将模型调用、形象解析、素材加载和响应校验收敛到内部准备函数，供首次创建和重新生成复用。`regenerate_wechat_article` 在模型成功后执行：

```python
reset_inline_illustrations(db, article, html_body=next_html, preserve_prompt_identity=False)
for cover in current_covers:
    cover.status = "stale"
db.execute(delete(WechatMpArticleMaterial).where(WechatMpArticleMaterial.article_id == article.id))
# 更新文章字段并重建素材关联
invalidate_synced_drafts(db, article, next_status="layout_ready")
usage = record_text_usage(..., step="write_article", resource_id=article.id, commit=False)
add_article_cost(article, usage.cost_yuan)
db.commit()
```

- [ ] **Step 4: 注册所有者隔离路由**

在动态文章 GET/PATCH 路由附近增加 `POST /{article_id}/regenerate`，先调用 `_get_owned_article`，映射素材 404、形象 400 和模型 502。

- [ ] **Step 5: 运行测试确认 GREEN**

重复 Step 2 命令，Expected: `2 passed`。

- [ ] **Step 6: 提交后端任务**

```bash
git add backend/app/services/wechat_mp_writer_service.py backend/app/api/platforms/wechat_mp/articles.py tests/backend/test_wechat_mp.py
git commit -m "feat: regenerate wechat article in place"
```

### Task 2: 前端返回与重新生成

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/platforms/wechat-mp/writer-page.tsx`
- Modify: `frontend/tests/wechat-mp-writing-flow.test.ts`

**Interfaces:**
- Consumes: 当前 `CreateWechatMpArticlePayload` 和文章 ID。
- Produces: `regenerateWechatMpArticle(articleId, payload)`；编辑预览返回按钮；同页重新生成分支。

- [ ] **Step 1: 写失败的前端契约测试**

断言 writer 包含 `返回修改写作要求` 和 `regenerateWechatMpArticle`，`applyCreatedArticle` 不再清空 `selectedMaterialIds`，有 `article ? regenerateWechatMpArticle(...) : createWechatMpArticle(...)` 分支。

- [ ] **Step 2: 运行测试确认 RED**

```bash
cd frontend && npm run test:wechat-writing-flow
```

Expected: 新断言失败。

- [ ] **Step 3: 实现 API 与页面状态**

在 API 客户端增加：

```ts
export async function regenerateWechatMpArticle(articleId: number, payload: CreateWechatMpArticlePayload): Promise<WechatMpArticle> {
  const response = await http.post(`/platforms/wechat-mp/articles/${articleId}/regenerate`, payload, { timeout: WECHAT_MP_ARTICLE_TIMEOUT_MS });
  return response.data;
}
```

首次生成后保留素材、想法和简报；编辑页按钮调用 `setWorkflowStep(0)`。正文按钮根据 `article` 显示 `生成文章` 或 `重新生成文章`，成功后刷新当前文章、清空当前提示词/当前资产并回到步骤 1。

- [ ] **Step 4: 运行前端测试和构建**

```bash
cd frontend && npm run test:wechat-writing-flow
cd frontend && npm run test:wechat-image-queue
cd frontend && npm run build
```

Expected: 两组测试和构建均退出 0。

- [ ] **Step 5: 提交前端任务**

```bash
git add frontend/src/lib/api.ts frontend/src/pages/platforms/wechat-mp/writer-page.tsx frontend/tests/wechat-mp-writing-flow.test.ts
git commit -m "feat: return and regenerate wechat article"
```

### Task 3: 回归与 Atlas 部署

**Files:**
- Verify only.

**Interfaces:**
- Consumes: Tasks 1-2。
- Produces: 推送分支和健康的 Atlas 新容器。

- [ ] **Step 1: 运行定向回归**

运行重新生成后端测试、写作简报测试、writer 源码契约、图片队列测试和生产构建。

- [ ] **Step 2: 差异与工作区检查**

```bash
git diff --check
git status --short --branch
```

- [ ] **Step 3: 推送并部署**

```bash
git push origin codex/wechat-shotlist-atlas-integration
ssh Atlas 'cd /root/xhs-all-in-one && git fetch eva-fork codex/wechat-shotlist-atlas-integration && git merge --ff-only FETCH_HEAD && docker compose up -d --build app'
```

- [ ] **Step 4: 线上验收**

核对 Atlas HEAD、`spider-xhs` `running healthy`、OpenAPI regenerate 路径、生产 bundle 的 `返回修改写作要求`，以及 `http://10.50.48.1:8000/platforms/wechat-mp/writer` 返回 200。
