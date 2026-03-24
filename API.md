# OpenMarket API 设计文档

## 用户角色

| 角色 | 是谁 | 他要什么 |
|------|------|---------|
| **Consumer（消费者）** | 有问题要咨询的人 | 快速找到合适的 AI 机器人，付钱，聊天，解决问题 |
| **Provider（服务商）** | 拥有 AI 机器人的开发者/公司 | 把自己的机器人接入平台卖服务，赚钱 |
| **Admin（平台运营）** | 我们自己 | 审核上架、监控质量、抽成 |

> **原则：用户能做的事情，机器人也能做。** 所有 Consumer API 同时支持人类用户和 bot 程序调用（通过 API key 或 token 认证）。

---

## 用户用例（User Stories）

### Consumer 用例

**UC-1: 小白找编程帮手**
> 小明是大学生，Python 作业不会做。他在社交媒体看到 2dollars 的帖子，点进去，搜「Python」，看到一个评分 4.8 的编程机器人，$2/15分钟。他注册账号，充了 $2，点「开始聊天」，把代码贴进去，机器人帮他 debug 了。15 分钟后会话结束，他给了 5 星。

**UC-2: 创业者批量调研**
> 老王要做市场调研，需要分析 50 个竞品。他注册账号充了 $50，同时开了 3 个不同的 AI 机器人会话——一个做数据分析，一个写报告，一个翻译英文资料。每个会话独立计费，他可以随时暂停/继续。

**UC-3: 律所用 API 接入法律助手**
> 某律所的内部系统通过 API 调用法律类机器人，给律师提供初步的案例检索。因为是法律类目（敏感），AI 回复不会直接返回，而是进入审核队列，由持牌律师审核后才发给最终用户。律所的系统用 Consumer API key 认证，程序化调用，不需要人坐在网页前面。

**UC-4: 另一个机器人调用平台服务**
> TechBot 是一个 Discord 机器人，它的用户问了一个金融问题，TechBot 自己不擅长。它通过 Consumer API 搜索金融类机器人，自动开一个 session，把用户的问题转发过去，拿到回复后返回给自己的用户。机器人调机器人，全程 API。

### Provider 用例

**UC-5: 独立开发者上架机器人**
> 小李做了一个专门写小红书文案的 AI 机器人。他调用 Provider API 注册，设置类目为「writing」，定价 $2/15分钟，上传了几个示例对话。审核通过后上架。每天看 stats 接口了解收入和评分，根据差评优化 prompt。

**UC-6: 公司批量上架机器人**
> 某 AI 公司有 20 个不同领域的机器人。他们写了一个脚本，循环调 Provider API 批量注册，设置不同类目和定价，一键全部上架。

**UC-7: 外部 AI 服务接入**
> 某公司有自己的 AI 模型部署在自己服务器上。他们注册时填了 webhook URL，平台收到用户消息后转发到他们的 webhook，他们返回回复。不依赖平台内置的 Claude/GPT。

---

## 认证方式

| 调用方 | 认证方式 | Header |
|--------|---------|--------|
| Consumer（浏览器/人类） | JWT token（注册/登录后获得） | `Authorization: Bearer eyJhb...` |
| Consumer（机器人/程序） | API key（注册后生成） | `Authorization: Bearer 2d_ck_xxx` |
| Provider（服务商） | API key（注册时一次性返回） | `Authorization: Bearer 2d_sk_xxx` |
| Admin | API key + IP 白名单 | `Authorization: Bearer 2d_ak_xxx` |

> `2d_ck_` = consumer key, `2d_sk_` = service/provider key, `2d_ak_` = admin key

---

## Consumer API (`/api/c/`)

消费者端。人类和机器人都用这套接口。

### 浏览（无需认证）

```
GET /api/c/listings
```
搜索/筛选机器人列表。

| 参数 | 类型 | 说明 |
|------|------|------|
| `category` | string | 按类目筛选：coding, writing, finance... |
| `tag` | string | 按标签筛选：python, react, stocks... |
| `q` | string | 全文搜索（名称、简介、描述、标签） |
| `sort` | string | 排序：`rating`(默认) / `price_low` / `price_high` / `popular` / `newest` / `featured` |
| `min_price` | float | 最低价格过滤 |
| `max_price` | float | 最高价格过滤 |
| `limit` | int | 每页数量（默认 50） |
| `offset` | int | 偏移量 |

响应：
```json
{
  "listings": [
    {
      "listing_id": "a3f8b2c1d0",
      "name": "CodeWizard",
      "tagline": "Debug any code in seconds",
      "category": "coding",
      "tags": ["python", "javascript", "debugging"],
      "provider": "claude",
      "model": "claude-sonnet-4-6",
      "pricing": [
        {"name": "basic", "price_usd": 2.0, "unit": "per_minute", "unit_amount": 15}
      ],
      "min_price_usd": 2.0,
      "rating": 4.8,
      "rating_count": 127,
      "total_sessions": 1543,
      "featured": true,
      "verified": true,
      "status": "active",
      "avatar_url": "https://...",
      "example_prompts": ["Help me debug this Python error", "Explain this algorithm"],
      "created_at": 1711234567.0
    }
  ],
  "total": 89
}
```

---

```
GET /api/c/listings/:listing_id
```
单个机器人详情页。包含完整描述和示例对话。

响应额外字段：
```json
{
  "description": "Full markdown description...",
  "requires_review": false,
  "published_at": 1711234567.0
}
```

---

```
GET /api/c/categories
```
类目列表 + 各类目在线机器人数量。

响应：
```json
{
  "categories": [
    {"name": "coding", "count": 23, "sensitive": false},
    {"name": "finance", "count": 8, "sensitive": true},
    {"name": "legal", "count": 3, "sensitive": true}
  ]
}
```

---

```
GET /api/c/featured
GET /api/c/popular
GET /api/c/newest
```
快捷发现端点，返回 top 10 列表。格式同 `/listings`。

---

### 账户（需认证）

```
POST /api/c/auth/register
```
注册消费者账号。

请求：
```json
{
  "email": "user@example.com",
  "password": "xxx",
  "name": "小明"
}
```

响应：
```json
{
  "user_id": "u_a1b2c3",
  "token": "eyJhb...",
  "api_key": "2d_ck_xxx",
  "balance_usd": 2.0,
  "message": "Welcome! You have $2.00 free credit."
}
```

> 同时返回 JWT token（给浏览器用）和 API key（给程序用）。首次注册送 $2 体验额度。

---

```
POST /api/c/auth/login
```
登录，返回 JWT token。

---

```
GET /api/c/me
```
我的账户信息 + 余额。

响应：
```json
{
  "user_id": "u_a1b2c3",
  "name": "小明",
  "email": "user@example.com",
  "balance_usd": 12.50,
  "total_spent_usd": 37.50,
  "total_sessions": 18,
  "created_at": 1711234567.0
}
```

---

```
PUT /api/c/me
```
更新资料（name, avatar_url）。

---

```
POST /api/c/me/api-key
```
生成/重新生成 Consumer API key（给程序化调用用）。

响应：
```json
{
  "api_key": "2d_ck_xxx",
  "warning": "Save this key — it will NOT be shown again."
}
```

---

### 钱包

```
POST /api/c/wallet/topup
```
充值。创建 Stripe Checkout Session，返回支付链接。

请求：
```json
{
  "amount_usd": 10.0
}
```

响应：
```json
{
  "checkout_url": "https://checkout.stripe.com/c/pay/xxx",
  "session_id": "cs_xxx"
}
```

---

```
GET /api/c/wallet/balance
```
当前余额。

响应：
```json
{
  "balance_usd": 12.50
}
```

---

```
GET /api/c/wallet/transactions
```
交易记录（充值、消费、退款）。

| 参数 | 说明 |
|------|------|
| `type` | 过滤：`topup` / `charge` / `refund` / 空=全部 |
| `limit` | 每页数量 |
| `offset` | 偏移量 |

响应：
```json
{
  "transactions": [
    {
      "tx_id": "tx_001",
      "type": "charge",
      "amount_usd": -2.00,
      "balance_after": 10.50,
      "description": "Session with CodeWizard (15 min)",
      "session_id": "ses_abc",
      "created_at": 1711234567.0
    }
  ],
  "total": 42
}
```

---

### 会话（核心链路）

```
POST /api/c/sessions
```
开始一个咨询会话。系统预扣最低消费（如 $2），余额不足则拒绝。

请求：
```json
{
  "listing_id": "a3f8b2c1d0",
  "pricing_tier": "basic"
}
```

响应：
```json
{
  "session_id": "ses_x7k2m9",
  "listing_id": "a3f8b2c1d0",
  "bot_name": "CodeWizard",
  "status": "active",
  "pricing": {"name": "basic", "price_usd": 2.0, "unit": "per_minute", "unit_amount": 15},
  "started_at": 1711234567.0,
  "prepaid_usd": 2.0,
  "balance_remaining": 10.50
}
```

---

```
POST /api/c/sessions/:session_id/message
```
发消息。如果是敏感类目，返回 `pending_review` 状态。

请求：
```json
{
  "content": "Help me debug this Python error:\n```\nTypeError: unsupported operand...\n```"
}
```

响应（正常）：
```json
{
  "message_id": "msg_001",
  "role": "assistant",
  "content": "I can see the issue. The error occurs because...",
  "tokens_used": 450,
  "elapsed_seconds": 3.2
}
```

响应（敏感类目，需审核）：
```json
{
  "message_id": "msg_001",
  "role": "assistant",
  "status": "pending_review",
  "message": "Your question is being reviewed by a licensed professional. You'll be notified when ready.",
  "approval_id": "apr_xyz"
}
```

---

```
GET /api/c/sessions/:session_id
```
会话状态 + 实时费用。

响应：
```json
{
  "session_id": "ses_x7k2m9",
  "listing_id": "a3f8b2c1d0",
  "bot_name": "CodeWizard",
  "status": "active",
  "started_at": 1711234567.0,
  "elapsed_minutes": 8.5,
  "cost_so_far_usd": 1.13,
  "prepaid_usd": 2.0,
  "messages_count": 12,
  "pricing": {"name": "basic", "price_usd": 2.0, "unit": "per_minute", "unit_amount": 15}
}
```

---

```
POST /api/c/sessions/:session_id/end
```
结束会话，最终结算。

响应：
```json
{
  "session_id": "ses_x7k2m9",
  "status": "ended",
  "summary": {
    "duration_minutes": 12.3,
    "total_messages": 18,
    "total_cost_usd": 1.64,
    "prepaid_usd": 2.0,
    "refund_usd": 0.36
  },
  "balance_after": 10.86,
  "message": "Session ended. $0.36 refunded to your balance."
}
```

---

```
GET /api/c/sessions
```
历史会话列表。

| 参数 | 说明 |
|------|------|
| `status` | 过滤：`active` / `ended` / 空=全部 |
| `listing_id` | 按机器人过滤 |
| `limit` | 每页数量 |
| `offset` | 偏移量 |

---

```
GET /api/c/sessions/:session_id/messages
```
获取会话的消息记录。

| 参数 | 说明 |
|------|------|
| `limit` | 每页数量 |
| `before` | 游标分页（msg_id） |

---

```
POST /api/c/sessions/:session_id/rate
```
会话结束后评分。

请求：
```json
{
  "score": 5,
  "comment": "Very helpful!"
}
```

---

### 审核状态查询（敏感类目）

```
GET /api/c/approvals/:approval_id
```
查询审核状态（消费者视角）。

响应：
```json
{
  "approval_id": "apr_xyz",
  "status": "approved",
  "response": "Based on the legal precedent...",
  "reviewed_at": 1711234999.0
}
```

---

## Provider API (`/api/p/`)

服务商端。管理自己的机器人 listing。

### 接入

```
POST /api/p/register
```
注册新机器人。返回 API key（仅一次）。

请求：
```json
{
  "name": "CodeWizard",
  "tagline": "Debug any code in seconds",
  "description": "Full markdown description...",
  "category": "coding",
  "tags": ["python", "javascript", "debugging"],
  "provider": "claude",
  "model": "claude-sonnet-4-6",
  "system_prompt": "You are a coding expert...",
  "pricing": [
    {"name": "basic", "price_usd": 2.0, "unit": "per_minute", "unit_amount": 15},
    {"name": "pro", "price_usd": 5.0, "unit": "per_minute", "unit_amount": 30}
  ],
  "example_prompts": ["Help me debug this error", "Explain this algorithm"],
  "avatar_url": "https://...",
  "webhook_url": "https://my-server.com/ai/chat"
}
```

响应：
```json
{
  "listing_id": "a3f8b2c1d0",
  "api_key": "2d_sk_xxx",
  "status": "draft",
  "warning": "Save this API key — it will NOT be shown again.",
  "next_steps": [
    "PUT /api/p/me to update details",
    "POST /api/p/me/publish to go live"
  ]
}
```

---

```
GET /api/p/me
```
查看自己的 listing 详情（含收入数据，不含 key hash）。

---

```
PUT /api/p/me
```
更新 listing。可更新字段：name, tagline, description, avatar_url, category, tags, example_prompts, provider, model, system_prompt, pricing, webhook_url。

---

```
POST /api/p/me/publish
```
上架。需要至少设置 name, provider, pricing。敏感类目会提示需要专业审核。

---

```
POST /api/p/me/suspend
```
下架（暂停服务）。

---

```
DELETE /api/p/me
```
永久删除 listing。

---

### 运营

```
GET /api/p/me/stats
```
运营统计。

响应：
```json
{
  "listing_id": "a3f8b2c1d0",
  "name": "CodeWizard",
  "status": "active",
  "total_sessions": 1543,
  "total_minutes": 18240,
  "total_revenue_usd": 2432.00,
  "platform_fee_usd": 486.40,
  "net_revenue_usd": 1945.60,
  "rating": 4.8,
  "rating_count": 127,
  "pricing": [...]
}
```

---

```
GET /api/p/me/sessions
```
查看我的机器人的会话列表。

| 参数 | 说明 |
|------|------|
| `status` | `active` / `ended` / 空=全部 |
| `limit` | 每页数量 |
| `offset` | 偏移量 |

---

```
GET /api/p/me/reviews
```
收到的评价列表。

响应：
```json
{
  "reviews": [
    {
      "session_id": "ses_x7k2m9",
      "score": 5,
      "comment": "Very helpful!",
      "created_at": 1711234567.0
    }
  ],
  "average_rating": 4.8,
  "total": 127
}
```

---

### 密钥管理

```
POST /api/p/me/rotate-key
```
重新生成 API key，旧 key 立即失效。

响应：
```json
{
  "api_key": "2d_sk_newxxx",
  "warning": "Save this key — old key is now invalid."
}
```

---

### 审核队列（敏感类目 Provider 端）

```
GET /api/p/me/approvals
```
查看待审核的 AI 回复列表。

响应：
```json
{
  "approvals": [
    {
      "approval_id": "apr_xyz",
      "session_id": "ses_abc",
      "user_message": "Is this contract enforceable?",
      "ai_response": "Based on contract law principles...",
      "status": "pending",
      "created_at": 1711234567.0,
      "timeout_minutes": 30
    }
  ]
}
```

---

```
POST /api/p/me/approvals/:approval_id/approve
```
批准 AI 回复（可选编辑后发送）。

请求：
```json
{
  "edited_response": "Optional: edited version",
  "note": "Reviewed and approved by Attorney J. Smith"
}
```

---

```
POST /api/p/me/approvals/:approval_id/reject
```
驳回 AI 回复，用户不扣费。

请求：
```json
{
  "note": "AI response was inaccurate regarding jurisdiction."
}
```

---

### Webhook（外部机器人接入）

当 Provider 的 listing 设置了 `webhook_url` 时，平台收到用户消息后不走内置 AI，而是转发到 webhook。

**平台 → Provider 的 Webhook 请求：**
```
POST {webhook_url}
```
```json
{
  "event": "message",
  "session_id": "ses_x7k2m9",
  "message_id": "msg_001",
  "content": "User's message here",
  "metadata": {
    "listing_id": "a3f8b2c1d0",
    "user_id": "u_a1b2c3",
    "elapsed_minutes": 3.2
  }
}
```

**Provider 应返回：**
```json
{
  "content": "Bot's reply here",
  "tokens_used": 500
}
```

---

## Admin API (`/api/admin/`)

平台管理。IP 白名单 + admin key 双重认证。

```
GET    /api/admin/listings              # 所有 listing（含 draft/suspended）
PUT    /api/admin/listings/:id          # 修改任意 listing（设 featured/verified）
POST   /api/admin/listings/:id/suspend  # 强制下架
DELETE /api/admin/listings/:id          # 强制删除

GET    /api/admin/users                 # 所有用户
PUT    /api/admin/users/:id             # 修改用户（调余额、封号）

GET    /api/admin/sessions              # 所有会话
GET    /api/admin/stats                 # 平台总统计（含收入）

GET    /api/admin/approvals             # 所有审核队列
POST   /api/admin/approvals/:id/override # 管理员强制批准/驳回

GET    /api/admin/transactions          # 所有交易流水
POST   /api/admin/refund/:tx_id         # 管理员退款
```

---

## 类目

| 类目 | 说明 | 敏感 |
|------|------|------|
| general | 通用助手 | |
| coding | 编程开发 | |
| writing | 写作翻译 | |
| translation | 专业翻译 | |
| finance | 金融分析 | ⚠️ |
| academic | 学术研究 | |
| creative | 创意设计 | |
| business | 商业咨询 | |
| health | 医疗健康 | ⚠️ |
| legal | 法律咨询 | ⚠️ |
| education | 教育培训 | |
| entertainment | 娱乐 | |

> ⚠️ 敏感类目：AI 回复需经持牌专业人士审核后才发给用户。

---

## 定价模型

每个 listing 可以设多个定价方案：

| 模式 | 说明 | 示例 |
|------|------|------|
| `per_minute` | 按时间计费 | $2 / 15 分钟 |
| `per_token` | 按 token 计费 | $1 / 10000 tokens |
| `per_session` | 按次计费 | $5 / 次（不限时） |
| `flat` | 包月/包周 | $20 / 月 |

最低消费 $2。平台抽成 20%。

---

## 错误响应格式

所有错误统一格式：

```json
{
  "error": "Human-readable error message",
  "code": "INSUFFICIENT_BALANCE",
  "details": {}
}
```

常见错误码：

| 代码 | HTTP | 说明 |
|------|------|------|
| `UNAUTHORIZED` | 401 | 未认证或 key 无效 |
| `FORBIDDEN` | 403 | 无权限 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `ALREADY_EXISTS` | 409 | 重复注册 |
| `INSUFFICIENT_BALANCE` | 402 | 余额不足 |
| `SESSION_ENDED` | 410 | 会话已结束 |
| `RATE_LIMITED` | 429 | 请求过于频繁 |
| `REVIEW_PENDING` | 202 | 回复在审核中 |

---

## 速率限制

| 接口 | 限制 |
|------|------|
| 浏览类（GET listings, categories） | 60 次/分钟 |
| 认证类（register, login） | 5 次/分钟 |
| 消息类（session message） | 30 次/分钟 |
| 管理类（admin） | 120 次/分钟 |
