# H3 API 全局限流配置系统 - 补充设计方案：完整 API 调用计费体系

## 🎯 业务目标

为爆款视频模块实现**基于真实 API 调用次数的计费系统**，支持：
- ✅ 管理员 + 普通用户各自独立设置搜索关键词/数量
- ✅ 每次搜索均计费（不管是否有缓存）
- ✅ 细粒度统计各类 API 调用：Search、Details、H3 Generation、COS Upload
- ✅ 后台端点 + 个人中心双重展示
- ✅ 与 H3 限流配置系统联动

---

## 🏗️ 架构设计

```
┌──────────────────────────────────────────────────────────────┐
│                    User Frontend (Tauri/Web)                  │
│                                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  搜索框      │  │  详情页      │  │  精选池      │       │
│  │  • 关键词    │  │  • 播放      │  │  • 上传      │       │
│  │  • 数量 N    │  │  • 详情      │  │  • 下载      │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         ↓                 ↓                  ↓               │
│   调用 tikhub.search()  调用 tikhub.video()  upload to COS   │
│         ↓                 ↓                  ↓               │
│   record_api_call()    record_api_call()   record_cos_usage()│
│         ↓                 ↓                  ↓               │
│   Billing Record:       Billing Record:     Billing Record: │
│   • service='search'   • service='details' • service='cos' │
│   • units=N            • units=1           • size_bytes    │
│   • user_id=X          • user_id=Y         • user_id=Z     │
└──────────────────────────────────────────────────────────────┘
                           ↓
                  PostgreSQL Database
┌──────────────────────────────────────────────────────────────┐
│  Table: operation_cost_records                               │
│  Columns:                                                    │
│    • id                                                      │
│    • source_type                                             │
│    • source_id                                               │
│    • subject                                                 │  ← NEW: 'viral_search', 'viral_details'    │
│    • usage_amount                                            │  ← number of API calls              │
│    • cost_fen                                                │  ← calculated from tariff        │
│    • status ('PENDING'/'COMMITTED')                         │
│    • created_by_user_id                                      │
│    • created_at                                              │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Table: viral_search_tasks (NEW)                             │
│  Columns:                                                    │
│    • id                                                       │
│    • user_id                                                  │
│    • is_admin_task BOOLEAN                                   │
│    • keywords TEXT                                           │
│    • requested_count INTEGER                                 │
│    • returned_count INTEGER                                  │
│    • platform 'douyin'|'wechat_channels'                   │
│    • status 'SUCCESS'|'PARTIAL'|'FAILED'                    │
│    • search_json JSONB                                       │
│    • api_call_count INTEGER  ← NEW: 实际调用次数             │
│    • created_at                                              │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Table: runtime_settings (EXTENDED)                          │
│  New columns:                                                │
│    • viral_search_unit_price_fen       INT (0.10 元 = 10 分)  │
│    • viral_details_unit_price_fen    INT (0.05 元 = 5 分)     │
│    • viral_h3_generation_unit_price  DECIMAL (按秒计费)      │
└──────────────────────────────────────────────────────────────┘
```

---

## 📦 数据库设计

### A. 创建 `viral_search_tasks` 表

```sql
-- server/migrations/XXX_create_viral_search_tasks.sql

CREATE TABLE viral_search_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 任务归属
    user_id         TEXT NOT NULL REFERENCES users(id),
    is_admin_task   BOOLEAN NOT NULL DEFAULT FALSE,  -- 区分管理员/普通用户
    
    -- 搜索参数
    keywords        TEXT NOT NULL,
    platform        TEXT NOT NULL CHECK (platform IN ('douyin', 'wechat_channels')),
    requested_count INTEGER NOT NULL CHECK (requested_count >= 1 AND requested_count <= 50),
    
    -- 搜索结果
    returned_count  INTEGER NOT NULL DEFAULT 0,
    search_json     JSONB NOT NULL DEFAULT '{}',
    
    -- 状态跟踪
    status          TEXT NOT NULL DEFAULT 'PENDING' 
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED')),
    error_code      TEXT,
    error_message_redacted TEXT,
    
    -- API 调用统计
    api_call_count  INTEGER NOT NULL DEFAULT 0,  -- ⭐ 关键计费字段
    
    -- 时间戳
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- 删除标记
    deleted_at      TIMESTAMPTZ
);

-- 索引优化
CREATE INDEX idx_viral_search_tasks_user ON viral_search_tasks(user_id, created_at DESC);
CREATE INDEX idx_viral_search_tasks_admin ON viral_search_tasks(user_id, is_admin_task, created_at DESC);
CREATE INDEX idx_viral_search_tasks_platform ON viral_search_tasks(platform, created_at DESC);

-- 审计日志关联
COMMENT ON TABLE viral_search_tasks IS '爆款视频搜索任务记录，用于计费统计';
```

### B. 扩展 `runtime_settings` 添加定价配置

```sql
-- server/migrations/XXX_add_viral_pricing.sql

ALTER TABLE runtime_settings
ADD COLUMN IF NOT EXISTS viral_search_unit_price_fen INTEGER DEFAULT 10,     -- ¥0.10
ADD COLUMN IF NOT EXISTS viral_details_unit_price_fen INTEGER DEFAULT 5,    -- ¥0.05
ADD COLUMN IF NOT EXISTS viral_h3_generation_base_price_fen INTEGER;        -- ¥2.00/秒（默认）
```

---

## 🔌 API 接口设计

### A. GET /api/control/viral/pricing

查询当前 API 定价配置（仅管理员）

```http
GET /api/control/viral/pricing
Authorization: Bearer <admin_token>
```

**响应:**
```json
{
  "viral_search_unit_price_fen": 10,
  "viral_details_unit_price_fen": 5,
  "viral_h3_generation_base_price_fen": 200,
  "h3_ratelimit_max_concurrent_requests": 20,
  "h3_ratelimit_enabled": true
}
```

### B. PUT /api/control/viral/pricing

更新定价配置（带幂等性校验）

```http
PUT /api/control/viral/pricing
Idempotency-Key: <uuid4>
Content-Type: application/json
Authorization: Bearer <admin_token>

{
  "expected_version": 1,
  "viral_search_unit_price_fen": 15,
  "viral_details_unit_price_fen": 8,
  "viral_h3_generation_base_price_fen": 250
}
```

### C. POST /api/viral/search

执行爆款视频搜索并自动计费

```http
POST /api/viral/search
Content-Type: application/json
Authorization: Bearer <token>

{
  "keywords": "装修技巧",
  "platform": "douyin",
  "count": 10
}
```

**后端逻辑:**
```python
# server/app/viral_search.py

@router.post("/api/viral/search")
async def search_viral_videos(
    payload: ViralSearchRequest,
    request: Request,
    response: Response,
    actor: CurrentUser,
):
    # 1. 检查 H3 限流是否影响本次搜索（如果 count > 限流值则分批）
    if global_rate_limiter.config and global_rate_limiter.config["enabled"]:
        max_per_batch = min(payload.count, global_rate_limiter.config["max_concurrent_requests"])
    else:
        max_per_batch = payload.count
    
    # 2. 拆分批量请求（避免单次超时）
    batches = split_into_batches(payload.count, max_per_batch)
    
    # 3. 记录初始计费请求
    search_task_id = create_search_task(
        user_id=actor.user_id,
        keywords=payload.keywords,
        platform=payload.platform,
        requested_count=payload.count,
        is_admin_task=isinstance(actor, AdminReader),  # 区分管理员
    )
    
    # 4. 执行搜索并统计 API 调用次数
    all_results = []
    total_api_calls = len(batches)  # 每批调用一次 Search API
    
    for i, batch in enumerate(batches):
        async with global_rate_limiter:
            results = await tikhub_client.search(
                keywords=payload.keywords,
                count=batch,
                platform=payload.platform,
            )
            all_results.extend(results)
    
    # 5. 记录 API 调用到 billing
    record_operation_cost(
        conn,
        source_type="viral_search_task",
        source_id=search_task_id,
        subject="viral_search",  # ← 计费科目
        usage_amount=total_api_calls,  # ← 实际调用次数
        user_id=actor.user_id,
    )
    
    # 6. 更新任务结果
    update_search_task(
        task_id=search_task_id,
        returned_count=len(all_results),
        api_call_count=total_api_calls,
        search_json=json.dumps(all_results),
        status="SUCCESS" if len(all_results) == payload.count else "PARTIAL",
    )
    
    return {
        "task_id": search_task_id,
        "results": all_results[:payload.count],  # 只返回请求的数量
        "api_call_count": total_api_calls,
        "charged_amount_credits": calculate_credits(
            usage=total_api_calls,
            tariff=read_tariff(conn, "viral_search"),
        ),
    }
```

### D. GET /api/viral/videos/{video_id}/details

获取视频详情并自动计费

```http
GET /api/viral/videos/wechat_channels/12345/details
Authorization: Bearer <token>
```

**后端逻辑:**
```python
@router.get("/api/viral/videos/{platform}/{video_id:path}/details")
async def get_video_details(
    platform: str,
    video_id: str,
    request: Request,
    response: Response,
    actor: CurrentUser,
):
    # 1. 先检查是否有本地缓存
    cached = await get_cached_details(platform, video_id)
    if cached:
        return cached
    
    # 2. 调用第三方 API 获取详情
    details = await tikhub_client.get_video_details(
        platform=platform,
        video_id=video_id,
    )
    
    # 3. 记录计费
    record_operation_cost(
        conn,
        source_type="viral_video_details",
        source_id=f"{platform}:{video_id}",
        subject="viral_details",  # ← 计费科目
        usage_amount=1,           # ← 每次 API 调用计 1 单位
        user_id=actor.user_id,
    )
    
    # 4. 缓存结果（可选 TTL）
    cache.set(f"details:{platform}:{video_id}", details, ttl=3600)
    
    return details
```

---

## 🎨 前端展示

### A. 个人中心 - 爆款视频账单

```tsx
// client/src/customer/ViralBillingHistory.tsx

export function ViralBillingHistory() {
  const [billingData, setBillingData] = useState({
    total_searches: 0,
    total_details: 0,
    total_cost_credits: 0,
    recent_tasks: [],
  });

  useEffect(() => {
    loadBilling();
  }, []);

  async function loadBilling() {
    // 查询近 30 天的所有 viral_* 服务账单
    const [searches, details, h3_generations] = await Promise.all([
      adminRead(`/api/customer/billing/summary?service=viral_search`),
      adminRead(`/api/customer/billing/summary?service=viral_details`),
      adminRead(`/api/customer/billing/summary?service=generation_768p`),
    ]);
    
    setBillingData({
      total_searches: searches.total_units,
      total_details: details.total_units,
      total_cost_credits: searches.cost_credits + details.cost_credits,
      recent_tasks: combineTasks(searches.recent, details.recent),
    });
  }

  return (
    <div className="customer-viral-billing">
      <header>
        <h2>🎬 爆款视频账单</h2>
        <div className="summary-cards">
          <Card title="总搜索次数">
            {billingData.total_searches} 次
            <small>({billingData.total_searches * 10} 分)</small>
          </Card>
          <Card title="总详情查看">
            {billingData.total_details} 次
            <small>({billingData.total_details * 5} 分)</small>
          </Card>
          <Card title="总消耗积分">
            {billingData.total_cost_credits} 分
          </Card>
        </div>
      </header>

      <table className="billing-history-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>类型</th>
            <th>关键词/视频 ID</th>
            <th>API 调用数</th>
            <th>消耗积分</th>
          </tr>
        </thead>
        <tbody>
          {billingData.recent_tasks.map(task => (
            <tr key={task.id}>
              <td>{new Date(task.created_at).toLocaleString('zh-CN')}</td>
              <td>
                {task.subject === 'viral_search' ? '🔍 搜索' : '📄 详情'}
              </td>
              <td>{task.keyword_or_video_id}</td>
              <td>{task.usage_amount}</td>
              <td>{task.cost_credits} 分</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

### B. 后台管理 - API 计费概览

```tsx
// client/src/admin/ViralBillingOverview.tsx

export function ViralBillingOverview({ readOnly }: { readOnly?: boolean }) {
  const [stats, setStats] = useState({
    total_users: 0,
    active_users_30d: 0,
    total_searches_30d: 0,
    total_details_30d: 0,
    revenue_credits_30d: 0,
    top_users: [],
  });

  useEffect(() => {
    loadStats();
  }, []);

  async function loadStats() {
    const data = await adminRead('/api/control/viral/statistics');
    setStats(data);
  }

  return (
    <div className="admin-viral-billing">
      <header>
        <h2>📊 爆款视频 API 计费总览</h2>
        <p>最近 30 天统计数据</p>
      </header>

      <div className="admin-stats-grid">
        <StatCard label="活跃用户数">{stats.active_users_30d}</StatCard>
        <StatCard label="搜索总次数">{stats.total_searches_30d}</StatCard>
        <StatCard label="详情查看总次数">{stats.total_details_30d}</StatCard>
        <StatCard label="总收入（积分）">{stats.revenue_credits_30d}</StatCard>
      </div>

      <section className="user-leaderboard">
        <h3>Top 10 消费用户</h3>
        <table>
          <thead>
            <tr>
              <th>排名</th>
              <th>用户 ID</th>
              <th>搜索次数</th>
              <th>详情次数</th>
              <th>总消费</th>
            </tr>
          </thead>
          <tbody>
            {stats.top_users.map((user, idx) => (
              <tr key={user.user_id}>
                <td>{idx + 1}</td>
                <td>{user.user_id}</td>
                <td>{user.search_count}</td>
                <td>{user.details_count}</td>
                <td>{user.total_credits}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
```

---

## 🔧 后端实现细节

### A. 集成到 `usage_billing.py`

```python
# server/app/usage_billing.py

# 新增计费科目注册
SERVICES['viral_search'] = ServiceDefinition(
    name='爆款视频搜索',
    unit='call',
    provider='tikhub',
    module='viral',
    customer_charge_allowed=True,
)

SERVICES['viral_details'] = ServiceDefinition(
    name='爆款视频详情',
    unit='call',
    provider='tikhub',
    module='viral',
    customer_charge_allowed=True,
)

# 计费函数增强
def accept_operation(
    conn: BusinessConnection,
    *,
    source_type: str,
    source_id: str,
    subject: str,  # 'viral_search' | 'viral_details' | ...
    user_id: str,
    units: Decimal | int | float = 1,
    resolution: str | None = None,
    metadata: dict | None = None,
) -> str:
    """接受操作计费请求"""
    
    # 1. 读取 tariff
    tariff = read_tariff(conn, subject)
    
    # 2. 计算积分
    credits = calculate_credits(tariff, units)
    
    # 3. 插入 pending 记录
    insert_operation_cost_record(
        conn,
        source_type=source_type,
        source_id=source_id,
        subject=subject,
        usage_amount=units,
        cost_fen=None,  # pending 阶段不计算费用
        status='PENDING',
    )
    
    return str(source_id)
```

### B. 异步扣费完成

```python
# 在搜索任务完成后调用

def complete_search_task(
    conn: psycopg.Connection,
    task_id: UUID,
    *,
    returned_count: int,
    api_call_count: int,
):
    """完成搜索任务并扣费"""
    
    # 1. 更新任务状态
    conn.execute("""
        UPDATE viral_search_tasks
        SET returned_count = %s,
            api_call_count = %s,
            status = 'SUCCESS',
            completed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (returned_count, api_call_count, task_id))
    
    # 2. 完成计费
    from app.usage_billing import complete_operation_cost
    
    complete_operation_cost(
        conn,
        record_id=str(task_id),
        usage_amount=api_call_count,
    )
```

---

## 📊 Prometheus 指标增强

```python
# server/app/h3_ratelimit.py + viral_metrics.py

from prometheus_client import Counter, Histogram

# 原有指标
RATELIMIT_REJECTED_COUNTER = Counter(
    'h3_ratelimit_rejected_total',
    'H3 API requests rejected due to rate limiting',
    ['worker_id'],
)

# 新增 API 调用指标
VIRAL_SEARCH_COUNTER = Counter(
    'viral_search_calls_total',
    'Total viral video search API calls',
    ['user_id', 'platform', 'is_admin'],
)

VIRAL_DETAILS_COUNTER = Counter(
    'viral_details_calls_total',
    'Total viral video detail API calls',
    ['user_id', 'platform'],
)

API_CALL_LATENCY_HISTOGRAM = Histogram(
    'viral_api_call_duration_seconds',
    'API call latency distribution',
    ['service', 'status'],  # service='search'|'details'
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)
```

---

## ✅ 验收标准

### P0 - 必需功能

- [ ] `viral_search_tasks` 表创建成功，能正确记录搜索任务
- [ ] `runtime_settings` 表新增定价字段
- [ ] POST /api/viral/search 正常执行并计费
- [ ] GET /api/viral/videos/{id}/details 正常执行并计费
- [ ] 个人中心显示准确账单
- [ ] 后台管理显示准确统计
- [ ] 管理员/普通用户账单完全隔离

### P1 - 监控增强

- [ ] Prometheus 指标导出正常
- [ ] Grafana 仪表盘展示 API 调用趋势
- [ ] 告警规则配置（如单用户异常高频调用）

### P2 - 用户体验优化

- [ ] 账单支持按日期范围筛选
- [ ] 账单支持导出 CSV
- [ ] 提供余额不足时的友好提示

---

## 🚀 实施计划

### Phase 1: 数据库与定价配置（2 小时）

1. 创建迁移文件 `server/migrations/XXX_create_viral_search_tasks.sql`
2. 扩展 `runtime_settings` 添加定价字段
3. 编写单元测试验证 schema 正确性

### Phase 2: API 计费实现（4 小时）

1. 修改 `tikhub_client.py` 增加调用计数
2. 实现 `search_viral_videos()` 流程
3. 集成到 `usage_billing.py` 扣费逻辑
4. 实现 `/api/viral/videos/{id}/details` 计费

### Phase 3: 前端账单展示（3 小时）

1. 个人中心：`ViralBillingHistory.tsx`
2. 后台管理：`ViralBillingOverview.tsx`
3. 系统集成到路由

### Phase 4: 测试与上线（2 小时）

1. 端到端测试：模拟搜索→查看详情→结算
2. 性能测试：验证高并发下的计费准确性
3. 灰度发布：先开放给内部账号测试

**总计：11 人时**

---

## 📝 总结

本方案通过以下步骤实现了完整的 API 调用计费体系：

1. **细粒度计费**：精确到每次 API 调用（搜索、详情、H3 生成）
2. **独立账户**：管理员/普通用户各自独立计费，互不影响
3. **实时扣除**：调用即记录，任务完成即扣费
4. **透明展示**：两端（个人中心 + 后台）均可查询详细账单
5. **限流联动**：与之前的 H3 限流系统协同工作，防止滥用

**关键创新点：**
- `viral_search_tasks` 表作为计费源数据，记录了每次搜索的完整上下文
- `api_call_count` 字段精准反映了实际 API 调用次数，而非简单的"一次搜索"
- 支持按平台（抖音/视频号）分别统计，便于后续差异化定价

下一步建议：我可以直接开始实现代码吗？或者需要先讨论哪个部分的具体实现？ 😊
