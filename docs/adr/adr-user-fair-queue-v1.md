# ADR-001: 用户公平队列架构

## Status

**Proposed** | **Accepted** | **Rejected** | **Deprecated**

*Status: Proposed - 等待 T24 任务评审和接受*

## Context

客户版 V3 需要支持多用户场景下的公平任务调度。当前实现（`generation.py::acquire_generation_task_lease`）采用全局 FIFO 机制，所有用户任务混排在同一个优先级队列中，由 Worker 按 `created_at, id` 顺序领取。

### 问题

在以下场景中，全局 FIFO 存在明显不足：

1. **资源饥饿**：单个用户可以创建大量任务，占据队列头部，导致其他用户任务长时间得不到处理
2. **并发不透明**：无法控制每个用户的并发度，可能导致单用户占用过多计算资源
3. **计费不公平**：付费用户在任务堆积时无法获得应有的优先级保证
4. **多实例协调困难**：在多 Worker 环境下，缺乏用户维度的任务分配可见性

### 设计目标

基于 T24 任务要求，新方案需要满足：

- 按 `user_id` 轮转，确保每个用户都有机会获得任务
- 默认每用户并发数为 1（可配置）
- 支持 A1000/B100/C10 等不同规格的用户持续获得机会
- 四 Worker 环境不重复领取同一任务
- 保持 Provider 提交的不确定性处理逻辑
- 不使用 Redis/消息队列，仅依赖 PostgreSQL 原生能力

## Decision

### 整体架构

采用**用户游标 + 行锁**的公平调度机制，所有状态保存在 PostgreSQL。

### 数据模型

新增表 `user_queue_cursors`：

```sql
CREATE TABLE user_queue_cursors (
    code_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_dispatched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    running_tasks_count INT NOT NULL DEFAULT 0,
    CONSTRAINT valid_running_tasks CHECK (running_tasks_count >= 0 AND running_tasks_count <= 1)
);

-- 热路径索引
CREATE INDEX idx_user_queue_cursors_last_dispatched 
ON user_queue_cursors(last_dispatched_at DESC);

CREATE UNIQUE INDEX idx_user_queue_cursors_code_active 
ON user_queue_cursors(code_id) 
WHERE running_tasks_count > 0;
```

字段说明：
- `code_id`: 激活码唯一标识（业务主键）
- `user_id`: 用户 ID（用于权限校验和资源隔离）
- `last_dispatched_at`: 最后一次分发任务的时间（轮转排序依据）
- `running_tasks_count`: 当前运行中的任务数（限制最大并发）

### 事务边界

#### 用户候选检查 + 任务领取

```sql
-- Step 1: 获取下一个待分发的用户（SKIP LOCKED 防止重复）
SELECT code_id, user_id
FROM user_queue_cursors
WHERE running_tasks_count < 1
ORDER BY last_dispatched_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;

-- Step 2: 更新计数并标记任务为 SUBMITTING
UPDATE user_queue_cursors
SET running_tasks_count = running_tasks_count + 1,
    last_dispatched_at = NOW()
WHERE code_id = $1
RETURNING code_id;

UPDATE generation_tasks
SET status = 'SUBMITTING',
    locked_by = $2,
    locked_until = $3,
    updated_at = NOW()
WHERE id = $4
RETURNING generation_tasks.id;
```

#### 任务完成回滚计数

```sql
UPDATE user_queue_cursors
SET running_tasks_count = GREATEST(running_tasks_count - 1, 0)
WHERE code_id = $1;
```

### 轮转策略

- 使用 `last_dispatched_at` 升序排列，优先处理最早获得机会的用户
- 每次成功领取任务后更新时间戳，使其排到队列尾部
- `FOR UPDATE SKIP LOCKED` 确保多 Worker 不会重复领取同一用户

### 并发控制

- 通过 PG 行锁 (`FOR UPDATE`) 保证线程安全
- `running_tasks_count` 的 CHECK 约束防止越界
- User dimension 的锁粒度比 global lock 更细，减少 contention

### 迁移策略

- 从现有 `generation_tasks` 聚合统计每个用户的 `running_tasks_count`
- `last_dispatched_at` 初始化为最近一次任务提交时间或 NOW()
- 历史未完成的任务继续保留原有锁机制，新生成任务走新路径

## Consequences

### 正面影响

- ✅ 用户维度公平：每个用户都有稳定的任务处理机会
- ✅ 并发可控：通过数据库约束强制执行 per-user 上限
- ✅ 零外部依赖：仅使用 PostgreSQL 原生的 SELECT FOR UPDATE 机制
- ✅ 可观测性强：`user_queue_cursors` 提供实时用户维度的调度可见性
- ✅ 向后兼容：不影响现有 Provider 重试和不确定处理逻辑

### 风险与挑战

- ⚠️ 冷启动问题：新用户首次获得机会前无历史行为记录（需初始化逻辑）
- ⚠️ 长尾用户：某些用户可能长期不活跃但占用 cursor 记录（需 cleanup 策略）
- ⚠️ 锁竞争热点：高峰时段 `user_queue_cursors` 表的 UPDATE 可能存在 contention
- ⚠️ 查询计划变化：需要针对新索引进行 EXPLAIN ANALYZE 调优

### 监控指标建议

- 每个用户的 `running_tasks_count` 分布直方图
- `user_queue_cursors` 表的锁等待时间
- 任务领取延迟：从 QUEUED 到 SUBMITTING 的时长
- 用户饥饿检测：连续 N 分钟未获得机会的用户数量

## Alternatives Considered

### Alternative 1: 多队列分级 priority queues

为不同付费等级维护独立队列，Worker 按权重轮询。

**Pros**: 付费用户优先；**Cons**: 复杂度过高，违背"简单可靠"原则

### Alternative 2: Token bucket 限流器

使用令牌桶算法控制每个用户的任务发放速率。

**Pros**: 更平滑的流量控制；**Cons**: 需要额外状态机，增加复杂度

### Alternative 3: Redis + Lua 脚本

使用 Redis 原子操作实现调度器。

**Pros**: 性能更好；**Cons**: **违反禁止引入 Redis 的红线**，且增加运维依赖

## Implementation Notes

### T24 交付物

- [x] `docs/adr/adr-user-fair-queue-v1.md` - 本文档
- [x] `docs/adr/t24-user-fair-queue-pseudo-sql.md` - 伪 SQL + 边界条件分析

### T25 后续工作

- [ ] 实现迁移 030 `user_fair_queue`
- [ ] 修改 `acquire_generation_task_lease` 集成新逻辑
- [ ] Worker 并发测试（4 Worker × N 用户 × M 任务）
- [ ] 压测报告（10,000 任务规模）

## References

- T24 Task Spec: `docs/客户版任务清单-V3.md` §5 P4
- Current Implementation: `server/app/generation.py::acquire_generation_task_lease` (L3512)
- PostgreSQL Documentation: [SELECT FOR UPDATE](https://www.postgresql.org/docs/current/sql-select.html)

---

*Created: 2026-08-25 for T24 用户公平队列 ADR 冻结任务*
*Maintained by: Architecture Team*
