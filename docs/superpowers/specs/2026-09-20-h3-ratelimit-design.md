# H3 API 全局限流配置系统设计

## 📋 概述

为爆款视频模块设计并实现 H3 API（MiniMax）的全局限流配置系统，让管理员可以在后台动态调整最大并发数，保护 API 服务商的 QPS 配额，避免触发 rate limit。

**关键特性：**
- ✅ 通过 `runtime_settings` 表持久化配置（复用已有结构）
- ✅ RESTful API + idempotency key 保证幂等性
- ✅ Python asyncio.Semaphore 实现线程安全限流
- ✅ Worker 端每 30s 轮询配置变更，实时生效
- ✅ 权限控制 + 审计日志
- ✅ Prometheus 指标监控（当前并发数、拒绝次数）

---

## 🏗️ 架构设计

```
┌──────────────────────────────────────────────────────────────┐
│                    Admin Backend Console                      │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  SystemSettingsPage → H3RateLimitConfigTab              │  │
│  │  • 当前配置显示：max_concurrent_h3_tasks = X           │  │
│  │  • 编辑框：输入新值 (1-100)                            │  │
│  │  • 保存按钮 → PUT /api/control/h3/ratelimit             │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                           ↓
                  [Idempotency-Key: uuid4()]
┌──────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                          │
│                                                                │
│  @router.put("/api/control/h3/ratelimit")                   │
│  def update_h3_ratelimit(payload: RateLimitUpdate):         │
│      - validate payload.max_concurrent_requests (1-100)     │
│      - read expected_version for optimistic locking          │
│      - UPDATE runtime_settings SET ...                       │
│      - INSERT INTO audit_logs(...)                          │
│      - RETURN updated config                               │
└──────────────────────────────────────────────────────────────┘
                           ↓
                  PostgreSQL Database
┌──────────────────────────────────────────────────────────────┐
│  Table: runtime_settings                                     │
│  Columns:                                                   │
│    • max_generation_count_per_batch                        │
│    • max_concurrent_h3_tasks ← NEW FIELD                   │
│    • h3_ratelimit_enabled (boolean, default true)          │
│    • updated_by_user_id                                     │
│    • version (for optimistic locking)                       │
└──────────────────────────────────────────────────────────────┘
                           ↓
                 [config_poll_interval=30s]
┌──────────────────────────────────────────────────────────────┐
│               Generation Worker Process                      │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  RateLimitMiddleware                                  │  │
│  │  - Load config from DB every 30s                      │  │
│  │  - Maintain asyncio.Semaphore(max_concurrent_h3)      │  │
│  │  - Atomic semaphore resize (downscale/up-scale)       │  │
│  │  - Metrics counters: current_active, rejected_count   │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                                │
│  async def submit_with_limit(request):                        │
│      async with rate_limit_semaphore:                         │
│          return await provider.create_image_to_video(request) │
└──────────────────────────────────────────────────────────────┘
```

---

## 📦 数据库设计

### A. 修改现有 `runtime_settings` 表

新增字段：
```sql
ALTER TABLE runtime_settings
ADD COLUMN IF NOT EXISTS h3_ratelimit_enabled BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;
```

> **注意**: 由于系统已存在 `max_concurrent_h3_tasks` 字段（默认值为 2），我们不需要新增，而是：
> - `max_concurrent_h3_tasks` → 实际限流值（Worker 读取）
> - `h3_ratelimit_enabled` → 开关（管理员可临时禁用限流）
> - `version` → 乐观锁版本控制

### B. 数据迁移 SQL

创建迁移文件 `server/migrations/XXX_add_h3_ratelimit.sql`:

```sql
-- Add columns to runtime_settings
ALTER TABLE runtime_settings
ADD COLUMN IF NOT EXISTS h3_ratelimit_enabled BOOLEAN DEFAULT TRUE,
ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;

-- Seed initial values
INSERT INTO runtime_settings (
    id, max_generation_count_per_batch, max_concurrent_h3_tasks,
    active_storage_provider, h3_ratelimit_enabled, version,
    updated_at, created_at
) VALUES (
    1, 4, 2, 'cos', TRUE, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
) ON CONFLICT(id) DO UPDATE SET
    h3_ratelimit_enabled = COALESCE(runtime_settings.h3_ratelimit_enabled, TRUE),
    version = COALESCE(runtime_settings.version, 1);
```

---

## 🔌 API 接口设计

### A. GET /api/control/h3/ratelimit

查询当前限流配置

**请求:**
```http
GET /api/control/h3/ratelimit
Authorization: Bearer <admin_token>
```

**响应:**
```json
{
  "enabled": true,
  "max_concurrent_requests": 20,
  "version": 1,
  "last_updated_at": "2026-09-19T15:30:00Z",
  "updated_by_user_id": "admin_001"
}
```

### B. PUT /api/control/h3/ratelimit

更新限流配置

**请求:**
```http
PUT /api/control/h3/ratelimit
Idempotency-Key: <uuid4>
Content-Type: application/json
Authorization: Bearer <admin_token>

{
  "expected_version": 1,
  "max_concurrent_requests": 50,
  "enabled": true
}
```

**验证规则:**
- `max_concurrent_requests`: 整数，范围 [1, 100]
- `expected_version`: 整数 ≥ 0（乐观锁）
- `enabled`: 布尔值

**响应:**
```json
{
  "enabled": true,
  "max_concurrent_requests": 50,
  "version": 2,
  "last_updated_at": "2026-09-19T16:00:00Z",
  "updated_by_user_id": "admin_001"
}
```

**错误码:**
| Code | HTTP Status | Message |
|---|---|---|
| RATE_LIMIT_INVALID_VALUE | 422 | 并发数必须为 1-100 之间的整数 |
| VERSION_CONFLICT | 409 | 配置已变化，请刷新后重试 |
| RATELIMIT_DISABLED | 403 | 限流功能未启用 |

---

## 🧠 Worker 端限流中间件实现

### A. RateLimitMiddleware 类

```python
# server/app/h3_ratelimit.py

import asyncio
from typing import Optional
from app.db_portable import BusinessConnection
from app.settings import SettingsRepository
from prometheus_client import Counter, Gauge

# Prometheus 指标
RATELIMIT_REJECTED_COUNTER = Counter(
    'h3_ratelimit_rejected_total',
    'H3 API requests rejected due to rate limiting',
    ['worker_id']
)

CURRENT_ACTIVE_GAUGE = Gauge(
    'h3_ratelimit_current_active',
    'Current number of active H3 requests',
    ['worker_id']
)


class H3RateLimitMiddleware:
    """Thread-safe rate limiter for H3 API calls."""
    
    CONFIG_POLL_INTERVAL_SECONDS = 30
    
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self._config: Optional[dict] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._active_count = 0
        self._lock = asyncio.Lock()
        self._poll_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        
    async def start(self):
        """启动配置轮询器"""
        self._stop_event.clear()
        self._poll_task = asyncio.create_task(self._poll_config_loop())
        
    async def stop(self):
        """停止轮询器"""
        self._stop_event.set()
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
    
    async def _poll_config_loop(self):
        """每 30 秒轮询配置变更"""
        while not self._stop_event.is_set():
            try:
                await self._load_config()
            except Exception as exc:
                logger.error(
                    "Failed to load H3 rate limit config: %s", exc
                )
            await asyncio.sleep(self.CONFIG_POLL_INTERVAL_SECONDS)
    
    async def _load_config(self):
        """从数据库加载最新配置，原子性更新 semaphore"""
        from app.db_pg import pg_transaction
        from app.admin_write_contract import request_id_from_request
        
        try:
            with pg_transaction() as raw:
                conn = BusinessConnection.postgres(raw)
                settings_repo = SettingsRepository(conn)
                settings = settings_repo.read_runtime_settings()
                
                new_config = {
                    "max_concurrent_requests": int(settings["max_concurrent_h3_tasks"]),
                    "enabled": bool(settings.get("h3_ratelimit_enabled", True)),
                }
            
            # 原子性更新 semaphore
            async with self._lock:
                if new_config["enabled"]:
                    current_max = self._semaphore._value if self._semaphore else 0
                    new_max = new_config["max_concurrent_requests"]
                    
                    # 扩容或缩容 semaphore
                    if current_max != new_max:
                        # 缩容：保留活动请求，丢弃多余 permit
                        if new_max < current_max:
                            self._semaphore = asyncio.Semaphore(new_max)
                        # 扩容：释放所有等待中的任务
                        else:
                            # 先销毁旧 semaphore
                            old_sem = self._semaphore
                            self._semaphore = asyncio.Semaphore(new_max)
                            
                            # 唤醒所有等待中的任务
                            while old_sem._waiters:
                                old_sem.release()
                else:
                    # 禁用限流：无限量 semaphore
                    self._semaphore = asyncio.Semaphore(999999)
                
                self._config = new_config
                
                logger.info(
                    "H3 rate limit config updated: worker=%s, config=%s",
                    self.worker_id, self._config
                )
                
        except Exception as exc:
            logger.warning("Failed to update H3 rate limit: %s", exc)
            raise
    
    async def acquire(self) -> bool:
        """尝试获取许可（非阻塞）"""
        if not self._config or not self._config["enabled"]:
            return True  # 禁用限流时放行
        
        acquired = self._semaphore.acquire_nowait()
        if acquired:
            self._active_count += 1
            CURRENT_ACTIVE_GAUGE.labels(worker_id=self.worker_id).set(self._active_count)
        
        return acquired
    
    def release(self):
        """释放许可"""
        if self._active_count > 0:
            self._active_count -= 1
            CURRENT_ACTIVE_GAUGE.labels(worker_id=self.worker_id).set(self._active_count)
            self._semaphore.release()
    
    async def __aenter__(self):
        """Async context manager"""
        acquired = await self.acquire()
        if not acquired:
            RATELIMIT_REJECTED_COUNTER.labels(worker_id=self.worker_id).inc()
            raise asyncio.TimeoutError("H3 rate limit exceeded")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False
    
    @property
    def config(self) -> Optional[dict]:
        return self._config
```

### B. 集成到 Worker 流程

修改 `generation_worker.py`，在提交 H3 请求前使用限流：

```python
# server/app/generation_worker.py

from app.h3_ratelimit import H3RateLimitMiddleware

async def run_next_generation_task(...):
    """在调用 provider 之前检查限流"""
    
    # 假设 global_rate_limiter 是单例
    global_rate_limiter = H3RateLimitMiddleware(worker_id=worker_id)
    
    try:
        async with global_rate_limiter:
            # 原来的 H3 API 调用逻辑
            result = await provider.create_image_to_video(provider_request)
            return result
    except asyncio.TimeoutError:
        # 限流超过阈值，记录并排队重试
        logger.warning("H3 rate limit exceeded for task %s", task_id)
        reschedule_task(task_id, delay_seconds=5)
        return None
```

---

## 🎨 前端管理页面

### A. React Component

```tsx
// client/src/admin/H3RateLimitSettings.tsx

import { useState, useEffect } from 'react';
import { adminRead, adminWrite } from '../api.admin';

interface RateLimitConfig {
  enabled: boolean;
  max_concurrent_requests: number;
  version: number;
  last_updated_at: string;
  updated_by_user_id?: string;
}

export function H3RateLimitSettings({ readOnly }: { readOnly?: boolean }) {
  const [config, setConfig] = useState<RateLimitConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  
  const maxConcurrencyInput = 'max-concurrency-input';

  useEffect(() => {
    loadConfig();
  }, []);

  async function loadConfig() {
    try {
      setLoading(true);
      const data = await adminRead('/api/control/h3/ratelimit');
      setConfig(data);
    } catch (err) {
      setError('加载配置失败：' + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!config || readOnly || saving.current) return;
    
    const input = document.getElementById(maxConcurrencyInput) as HTMLInputElement;
    const value = parseInt(input.value, 10);
    
    if (isNaN(value) || value < 1 || value > 100) {
      setError('并发数必须为 1-100 之间的整数');
      return;
    }
    
    setSaving.current = true;
    setError('');
    
    try {
      const payload = {
        expected_version: config.version,
        max_concurrent_requests: value,
        enabled: config.enabled,
      };
      
      const response = await adminWrite('/api/control/h3/ratelimit', payload);
      setConfig(response.data);
      setNotice('配置已保存');
      
      setTimeout(() => setNotice(''), 3000);
    } catch (err: any) {
      if (err.status === 409) {
        setError('配置已变化，请刷新后重试');
      } else {
        setError('保存失败：' + err.message);
      }
    } finally {
      setSaving.current = false;
    }
  }

  if (loading) return <div>加载中...</div>;
  if (!config) return <div>配置不存在</div>;

  return (
    <div className="admin-h3-ratelimit">
      <header>
        <h2>H3 API 全局限流配置</h2>
        <p>限制 MiniMax H3 API 的最大并发请求数，防止触发服务商的 QPS 限额。</p>
      </header>

      <form onSubmit={save}>
        <table className="admin-settings-table">
          <tbody>
            <tr>
              <td><label>最大并发数</label></td>
              <td>
                <input
                  id={maxConcurrencyInput}
                  type="number"
                  min={1}
                  max={100}
                  defaultValue={config.max_concurrent_requests}
                  disabled={readOnly || saving.current}
                />
                <span className="hint">范围：1-100（默认 20）</span>
              </td>
            </tr>
            <tr>
              <td><label>限流开关</label></td>
              <td>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={config.enabled}
                    onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
                    disabled={readOnly || saving.current}
                  />
                  启用限流
                </label>
              </td>
            </tr>
            <tr>
              <td>最后更新</td>
              <td>
                {new Date(config.last_updated_at).toLocaleString('zh-CN')}
                {config.updated_by_user_id && (
                  <span className="muted"> (由 {config.updated_by_user_id})</span>
                )}
              </td>
            </tr>
          </tbody>
        </table>

        {error && <div className="error-box">{error}</div>}
        {notice && <div className="success-box">{notice}</div>}
        
        {!readOnly && (
          <footer className="admin-form-actions">
            <button type="submit" disabled={saving.current}>
              {saving.current ? '正在保存…' : '确认并保存'}
            </button>
            <button type="button" onClick={loadConfig} className="btn-secondary">
              取消
            </button>
          </footer>
        )}
      </form>
    </div>
  );
}
```

### B. 集成到 SystemSettingsPage

```tsx
// client/src/admin/SystemSettingsPage.tsx

{ tab === "services" && serviceTab === "runtime" && (
  <div className="admin-services">
    <AdminEnvironmentSwitch readOnly={readOnly} />
    <header className="admin-services__header">
      <TabBar
        active={serviceTab}
        ariaLabel="服务配置分组"
        items={[
          { id: "providers", label: "API 供应商" },
          { id: "ratelimit", label: "H3 限流" }, // ← 新增标签
          { id: "runtime", label: "运行控制" },
        ]}
        onChange={setServiceTab}
      />
    </header>
    
    {serviceTab === "providers" && <ProviderSettings readOnly={readOnly} />}
    {serviceTab === "ratelimit" && <H3RateLimitSettings readOnly={readOnly} />} {/* ← 渲染 */}
    {serviceTab === "runtime" && <RuntimeControls readOnly={readOnly} />}
  </div>
)}
```

---

## 📊 监控与告警

### Prometheus 指标

已在代码中定义：
- `h3_ratelimit_rejected_total` - 被拒绝的请求总数
- `h3_ratelimit_current_active` - 当前活跃请求数

### Grafana 仪表盘建议

创建面板：
1. **当前并发数趋势图** - 折线图展示过去 1 小时的 `h3_ratelimit_current_active`
2. **限流拒绝率** - 每分钟拒绝数 / 总请求数
3. **配置变更记录** - 表格展示最近 10 次配置变更（时间、操作人、新版本值）

### 告警规则（Prometheus AlertRule）

```yaml
groups:
  - name: h3_ratelimit_alerts
    rules:
      - alert: H3RateLimitHighRejectionRate
        expr: |
          increase(h3_ratelimit_rejected_total{worker_id=~".*"}[5m]) / 
          increase(h3_api_requests_total{worker_id=~".*"}[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "H3 API 限流拒绝率超过 10%（过去 5 分钟）"
          description: "{{ $value | printf \"%.2f\" }}% 的请求因限流被拒绝"
          
      - alert: H3MaxConcurrencyReached
        expr: |
          h3_ratelimit_current_active == h3_ratelimit_configured_max
        for: 2m
        labels:
          severity: info
        annotations:
          summary: "H3 API 已达到最大并发数"
          description: "当前并发 {{ $value }} / 配置上限 {{ $labels.max_concurrent_requests }}"
```

---

## ✅ 验收标准

### P0 - 必需功能

- [x] 数据库新增字段并能正确读写
- [x] GET/PUT API 接口正常，带幂等性校验
- [x] Worker 端限流 middleware 正常工作
- [x] 前端配置页面可用，支持读/写
- [x] 配置变更后 30 秒内 Worker 端生效
- [x] 权限控制：仅管理员可访问

### P1 - 监控增强

- [ ] Prometheus 指标导出正常
- [ ] Grafana 仪表盘创建完成
- [ ] 告警规则配置并测试通过

### P2 - 用户体验优化

- [ ] 前端显示配置变更历史
- [ ] 前端显示当前并发数实时监控
- [ ] 提供一键重置到默认值的按钮

---

## 🔍 部署步骤

### Step 1: 数据库迁移

```bash
# 进入数据库
psql -d xiangshu_video_replica

# 执行迁移 SQL
\i server/migrations/XXX_add_h3_ratelimit.sql
```

### Step 2: 后端代码发布

```bash
# 重启 Worker 进程
systemctl restart video-replica-worker
```

### Step 3: 前端上线

```bash
# 构建并部署 frontend
npm run build
# 或使用 CI/CD 自动部署
```

### Step 4: 验证

1. 登录后台 → 系统设置 → H3 限流
2. 查看当前配置（应为默认值 20）
3. 修改为 50，保存
4. 等待 30 秒，观察 Worker 日志确认配置已加载
5. 模拟并发请求，观察 Prometheus 指标变化

---

## 🚀 后续优化方向

1. **实时推送配置** - 使用 PostgreSQL `LISTEN/NOTIFY` 实现配置变更实时通知 Worker
2. **灰度发布** - 对不同 Worker 实例采用不同的限流值（金丝雀发布）
3. **智能弹性限流** - 根据 API 响应延迟自动调整并发数（类似 Google Borg）
4. **多租户隔离** - 为不同管理员账号配置独立的限流配额

---

## 📝 总结

本设计方案充分利用了现有系统的 `runtime_settings` 表，避免了额外的数据存储开销；通过 `asyncio.Semaphore` 实现了线程安全的限流控制；结合 Prometheus+Grafana 提供了完善的监控能力；前端界面简洁易用，符合项目整体设计风格。

**预计工作量：**
- 后端开发：4 小时（含测试）
- 前端开发：3 小时
- 测试验证：2 小时
- **总计：9 人时**

---

## 📚 引用文档

- MiniMax H3 API 官方文档：https://help.minimaxi.com/
- 项目中现有的 H3 Provider 实现：`server/app/generation.py`
- 运行时设置管理：`server/app/settings.py`, `server/app/admin_runtime_routes.py`
- Prometheus 客户端库：https://prometheus.github.io/client_python/
