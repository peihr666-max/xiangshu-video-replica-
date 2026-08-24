# T24: 用户公平队列 - 伪 SQL 与边界条件分析

## 状态

- **任务 ID**: T24
- **名称**: 冻结公平队列 ADR 和伪 SQL
- **阶段**: M4 (后续充值与用户公平队列)
- **优先级**: P1 (关键路径依赖)
- **规模**: S (0.5–1 人日)
- **Status**: [~] IN_PROGRESS

## 交付物清单

### ✅ 已完成

- [x] `.omx/plans/adr-user-fair-queue-v1.md` - ADR 架构设计文档
- [x] 本文档 - 伪 SQL + 边界条件详细分析

### 🚧 待完成 (T25)

- [ ] Migration 030 `user_fair_queue.py` 实现
- [ ] `generation.py::acquire_generation_task_lease` 重构
- [ ] `test_customer_queue_fairness.py` 专项测试
- [ ] 压测报告（10,000 任务）

---

## 伪 SQL 规范

### 1. Schema DDL

```sql
-- ================================
-- Table: user_queue_cursors
-- Purpose: Per-user queue cursor for fair scheduling
-- Owner: T24/T25 (M4 Fair Queue)
-- ================================

CREATE TABLE IF NOT EXISTS user_queue_cursors (
    -- Primary key: Bound to activation code (business key)
    code_id UUID PRIMARY KEY,
    
    -- Foreign key to users table (for access control)
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Last time this user was given a task opportunity (round-robin key)
    last_dispatched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Current running tasks count for this user (per-user concurrency limit)
    running_tasks_count INT NOT NULL DEFAULT 0,
    
    -- Constraint: Cannot have negative or >1 running tasks (configurable)
    CONSTRAINT valid_running_tasks 
        CHECK (running_tasks_count >= 0 AND running_tasks_count <= 1),
    
    -- Audit fields (append-only principle)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ================================
-- Indexes for hot path performance
-- ================================

-- Critical for ORDER BY last_dispatched_at in queue selection
CREATE INDEX CONCURRENTLY IF NOT EXISTS 
    idx_user_queue_cursors_rotation 
    ON user_queue_cursors(last_dispatched_at ASC)
    WHERE running_tasks_count < 1;

-- For UPDATE ... FOR UPDATE SKIP LOCKED efficiency
CREATE INDEX CONCURRENTLY IF NOT EXISTS 
    idx_user_queue_cursors_active_lock 
    ON user_queue_cursors(code_id) 
    WHERE running_tasks_count > 0;

-- Covering index for common select pattern (code_id + user_id projection)
CREATE INDEX CONCURRENTLY IF NOT EXISTS 
    idx_user_queue_cursors_covering 
    ON user_queue_cursors(code_id) 
    INCLUDE (user_id, running_tasks_count, last_dispatched_at)
    WHERE running_tasks_count < 1;

-- ================================
-- Triggers for updated_at maintenance
-- ================================

-- Reuse existing trigger mechanism from db.py if available
-- Otherwise define inline:
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER trg_user_queue_cursors_updated_at
    BEFORE UPDATE ON user_queue_cursors
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

```

### 2. Core Transaction Patterns

#### Pattern A: User Candidate Check + Task Lease Acquisition

**Use Case**: Worker 领取任务时的核心事务，保证原子性的用户检查和任务锁定

```sql
-- Transaction Start (SERIALIZABLE or REPEATABLE READ)
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;

-- Step 1: Get next user candidate with row-level lock
-- Uses covering index for minimal IO
SELECT code_id, user_id, last_dispatched_at
INTO cur_cursor, cur_user_id, cur_last_dispatched
FROM user_queue_cursors
WHERE running_tasks_count < 1
ORDER BY last_dispatched_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED
WITH HOLD;

-- If no cursor found, rollback and return None
IF cur_cursor IS NULL THEN
    ROLLBACK;
    RETURN NULL;
END IF;

-- Step 2: Acquire generation task lease (still using global FIFO within user)
UPDATE generation_tasks
SET status = 'SUBMITTING',
    locked_by = v_worker_id,
    locked_until = (NOW() + INTERVAL '60 seconds'),
    updated_at = NOW()
WHERE id = (
    SELECT id FROM generation_tasks
    WHERE batch_id IN (
        SELECT id FROM generation_batches WHERE created_by_user_id = cur_user_id
    )
    AND status IN ('PENDING', 'QUEUED')
    AND (locked_until IS NULL OR datetime(locked_until) <= CURRENT_TIMESTAMP)
    AND (next_poll_at IS NULL OR next_poll_at <= CURRENT_TIMESTAMP)
    ORDER BY created_at, id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING id INTO v_task_id;

-- Step 3: Update cursor counter and rotation timestamp
UPDATE user_queue_cursors
SET running_tasks_count = running_tasks_count + 1,
    last_dispatched_at = NOW()
WHERE code_id = cur_cursor
RETURNING code_id INTO verified_cursor;

-- Verify step 3 succeeded (defensive programming)
IF verified_cursor IS NULL THEN
    -- Rollback step 2 via delete or state restore
    UPDATE generation_tasks SET status = 'QUEUED' WHERE id = v_task_id;
    ROLLBACK;
    RETURN NULL;
END IF;

-- Step 4: Commit success
COMMIT;

-- Return task details to worker
RETURN load_worker_task(v_task_id);

```

#### Pattern B: Task Completion - Increment Cursor Counter

**Use Case**: Provider 提交成功，归档完成

```sql
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;

-- Decrement running count and update timestamp
UPDATE user_queue_cursors
SET running_tasks_count = GREATEST(running_tasks_count - 1, 0),
    last_dispatched_at = NOW()
WHERE code_id = v_code_id;

-- Assert constraint violation won't happen (PG handles this automatically)
-- IF affected_rows = 0 THEN RAISE EXCEPTION 'Cursor not found'; END IF;

COMMIT;

```

#### Pattern C: Task Failure - Release Without Decrement

**Use Case**: Provider 返回失败，RESERVE 阶段回滚

```sql
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;

-- Just clear the lock, don't decrement counter (task still "running" from user perspective)
UPDATE user_queue_cursors
SET last_dispatched_at = NOW()
WHERE code_id = v_code_id AND running_tasks_count > 0;

UPDATE generation_tasks
SET status = 'FAILED',
    locked_by = NULL,
    locked_until = NULL,
    updated_at = NOW()
WHERE id = v_task_id AND locked_by = v_worker_id;

COMMIT;

```

#### Pattern D: Cold Start - Initialize New User Cursor

**Use Case**: 新用户首次激活时创建 cursor 记录

```sql
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;

-- Upsert cursor for new user (idempotent on code activation)
INSERT INTO user_queue_cursors (code_id, user_id, last_dispatched_at, running_tasks_count)
VALUES (v_code_id, v_user_id, NOW(), 0)
ON CONFLICT (code_id) DO NOTHING
RETURNING code_id;

-- If already exists, do nothing (race condition guard)
-- The existing record will naturally appear in queue after current task completes

COMMIT;

```

#### Pattern E: Cleanup Long-tail Inactive Users

**Use Case**: Maintenance job for idle users without recent activity

```sql
-- Risk: Over-cleanup can create fairness holes → Only run during low-traffic window
-- Safety: Use conservative timeout (e.g., 7 days) + dry-run mode first

BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;

DELETE FROM user_queue_cursors
WHERE code_id IN (
    SELECT code_id FROM user_queue_cursors
    WHERE last_dispatched_at < (NOW() - INTERVAL '7 days')
    AND running_tasks_count = 0
    LIMIT 1000  -- Batch cleanup to avoid long transactions
    FOR UPDATE SKIP LOCKED
)
RETURNING code_id, user_id;

-- Audit trail for compliance (append-only principle)
INSERT INTO user_queue_cleanup_audit (code_id, user_id, cleaned_at, reason)
SELECT code_id, user_id, NOW(), 'idle_timeout'
FROM deleted;

COMMIT;

```

### 3. Migration Data Seeding Strategy

**Use Case**: 从现有数据初始化 `user_queue_cursors`

```sql
-- Run as part of migration 030 (dry-run first, then apply)

-- Step 1: Dry-run analysis (DO NOT COMMIT)
SELECT 
    gb.created_by_user_id AS user_id,
    ac.code_id,
    COUNT(gt.id) AS total_tasks,
    SUM(CASE WHEN gt.status IN ('SUBMITTING', 'RUNNING', 'ARCHIVING') THEN 1 ELSE 0 END) AS running_count,
    MAX(gt.created_at) AS last_task_created_at
FROM generation_batches gb
JOIN activation_codes ac ON ac.batch_id = gb.id
LEFT JOIN generation_tasks gt ON gt.batch_id = gb.id
GROUP BY gb.created_by_user_id, ac.code_id
ORDER BY running_count DESC, last_task_created_at DESC;

-- Step 2: Apply seeding (once verified safe)
INSERT INTO user_queue_cursors (code_id, user_id, last_dispatched_at, running_tasks_count)
SELECT 
    ac.code_id,
    gb.created_by_user_id AS user_id,
    COALESCE(MAX(gt.created_at), NOW()) AS last_dispatched_at,
    SUM(CASE WHEN gt.status IN ('SUBMITTING', 'RUNNING', 'ARCHIVING') THEN 1 ELSE 0 END) AS running_tasks_count
FROM generation_batches gb
JOIN activation_codes ac ON ac.batch_id = gb.id
LEFT JOIN generation_tasks gt ON gt.batch_id = gb.id
GROUP BY ac.code_id, gb.created_by_user_id
ON CONFLICT (code_id) DO UPDATE SET
    last_dispatched_at = EXCLUDED.last_dispatched_at,
    running_tasks_count = EXCLUDED.running_tasks_count;

-- Verify results
SELECT COUNT(*) FROM user_queue_cursors;
SELECT SUM(running_tasks_count) FROM user_queue_cursors;

```

---

## 边界条件与竞态处理

### 1. Cold Start Race (多 Worker 同时领取新用户任务)

**Scenario**: 两个 Worker 几乎同时发起查询，都找到同一个空闲 cursor

**Solution**: PG `FOR UPDATE SKIP LOCKED` 确保串行化

```sql
-- Worker 1: Acquires lock on code_id X
SELECT ... FOR UPDATE SKIP LOCKED;  -- OK, gets lock

-- Worker 2: Skips X because it's locked
SELECT ... FOR UPDATE SKIP LOCKED;  -- SKIPS X, moves to next user

-- Result: Only one worker proceeds, other retries later
```

### 2. Stuck Cursor (任务长时间不释放)

**Scenario**: Worker crash 后 cursor 的 `running_tasks_count` 无法自动降低

**Solution**: 结合 `generation_tasks.locked_until` + 后台维护任务

```sql
-- Maintenance timer runs every 5 minutes
UPDATE user_queue_cursors uqc
SET running_tasks_count = GREATEST(running_tasks_count - 1, 0),
    last_dispatched_at = NOW()
WHERE code_id IN (
    SELECT DISTINCT code_id FROM user_queue_cursors
    WHERE code_id IN (
        SELECT gt.code_id
        FROM generation_tasks gt
        JOIN generation_batches gb ON gb.id = gt.batch_id
        JOIN activation_codes ac ON ac.batch_id = gb.id
        WHERE gt.status IN ('SUBMITTING', 'RUNNING')
        AND gt.locked_until < (NOW() - INTERVAL '5 minutes')
    )
)
RETURNING code_id;

-- Alert if stuck count exceeds threshold
SELECT COUNT(*) FROM user_queue_cursors
WHERE code_id IN (SELECT ... stuck logic ...)
HAVING COUNT(*) > 10;
```

### 3. Starvation Prevention (防止某些用户长期得不到机会)

**Scenario**: 活跃用户不断有新的任务提交，导致老用户被持续忽略

**Solution**: 
- Base implementation: FIFO by `last_dispatched_at` 已足够（每完成一个任务就轮换）
- Enhanced (optional): Add bonus weight for users who haven't received tasks in >N minutes

```sql
-- Optional bonus scoring for starvation prevention
SELECT code_id, user_id,
    last_dispatched_at,
    EXTRACT(EPOCH FROM (NOW() - last_dispatched_at)) / 60.0 AS minutes_idle,
    CASE 
        WHEN EXTRACT(EPOCH FROM (NOW() - last_dispatched_at)) / 60.0 > 30 THEN 1000
        WHEN EXTRACT(EPOCH FROM (NOW() - last_dispatched_at)) / 60.0 > 10 THEN 100
        ELSE 0
    END AS starvation_bonus
FROM user_queue_cursors
WHERE running_tasks_count < 1
ORDER BY last_dispatched_at ASC + starvation_bonus DESC;  -- Custom sort priority
```

### 4. Migration Safety (迁移过程中的双轨运行)

**Scenario**: 旧任务继续使用全局 FIFO，新任务走公平队列

**Solution**: Feature flag + 时间窗口过渡

```sql
-- Add column to gate migration (safe rollout)
ALTER TABLE user_queue_cursors ADD COLUMN IF NOT EXISTS active_migration BOOLEAN DEFAULT FALSE;

-- During transition, only process cursors marked active
SELECT code_id FROM user_queue_cursors
WHERE running_tasks_count < 1
AND active_migration = TRUE  -- Gate
ORDER BY last_dispatched_at ASC
FOR UPDATE SKIP LOCKED;

-- After all tests pass, enable globally
UPDATE user_queue_cursors SET active_migration = TRUE WHERE active_migration = FALSE;

```

### 5. Idempotency Guard (幂等性保证)

**Scenario**: 重试请求可能多次更新同一个 cursor

**Solution**: Version stamp + optimistic locking

```sql
-- Add version column to detect conflicts
ALTER TABLE user_queue_cursors ADD COLUMN IF NOT EXISTS version INT DEFAULT 0;

-- Optimistic lock update
UPDATE user_queue_cursors
SET running_tasks_count = running_tasks_count + 1,
    last_dispatched_at = NOW(),
    version = version + 1
WHERE code_id = $1 AND version = $2
RETURNING version AS new_version;

-- Retry if affected_rows = 0 (version mismatch)
IF new_version IS NULL THEN
    WAIT 10ms;  -- Backoff
    RETRY;
END IF;

```

---

## Test Matrix (T25 专项测试覆盖)

### Core Functionality Tests

| Test Name | Scenario | Expected Outcome | Assert |
| --- | --- | --- | --- |
| `test_fair_queue_single_user` | Single user, multiple tasks | Tasks processed sequentially | `running_tasks_count = 1` at peak |
| `test_fair_queue_multi_user_round_robin` | 4 users × 3 tasks each | Each user gets exactly 1 task before repeat | Round-robin order confirmed |
| `test_fair_queue_concurrent_workers` | 4 Workers × 10 tasks | No duplicate assignments | Unique task assignments across workers |
| `test_fair_queue_idle_user_cleanup` | User inactive for 7 days | Cursor removed from table | Count reduced after cleanup job |

### Edge Case Tests

| Test Name | Scenario | Expected Outcome | Assert |
| --- | --- | --- | --- |
| `test_fair_queue_worker_crash_recovery` | Worker dies mid-task | Cursor count auto-recovered | `running_tasks_count` resets after timeout |
| `test_fair_queue_new_user_onboarding` | New user activates code | Cursor created automatically | Record exists in table |
| `test_fair_queue_starvation_prevention` | Power user floods queue | Regular users still get opportunities | Response time variance < 2x |
| `test_fair_queue_migration_safety` | Mixed old/new task paths | Both work correctly | Zero data loss during transition |

### Stress Tests (T27)

| Test Name | Scale | Target Metric | Pass Criteria |
| --- | --- | --- | --- |
| `test_fair_queue_10k_tasks` | 10,000 tasks, 100 users | p95 latency | < 100ms per task acquisition |
| `test_fair_queue_lock_contention` | 10 Workers competing | Lock wait time | < 5ms average, < 50ms p99 |
| `test_fair_queue_memory_leak` | 1 hour continuous run | Memory growth | < 100MB/hour increase |

---

## Security & Compliance Considerations

### Data Privacy
- `user_queue_cursors` contains only foreign keys to users (no PII directly stored)
- Access controlled via FK cascade + RBAC layer (T21 fencing)

### Audit Requirements
- All updates logged via `updated_at` timestamp
- Append-only audit table recommended: `user_queue_operations_audit`
- Migration history tracked via Alembic revisions (030)

### Rate Limiting Integration
- Existing `security_rate_limits` schema (T15) must NOT conflict with fair queue locks
- Recommended: Separate tables for authentication rate limiting vs. queue coordination

---

## Operational Runbook

### Monitoring Dashboards

1. **Real-time Metrics**
   - `user_queue_cursors` row count by `running_tasks_count` value
   - Average lock wait time (pg_stat_activity)
   - Task acquisition latency histogram

2. **Alert Thresholds**
   - P1: `running_tasks_count > 1` detected (constraint violation)
   - P2: Average lock wait > 10ms
   - P3: Any user idle > 24 hours without cursor cleanup

### Rollback Plan

**If migration fails:**

1. Disable new cursor usage immediately:
   ```sql
   ALTER TABLE user_queue_cursors DISABLE TRIGGER ALL;
   DROP INDEX IF EXISTS idx_user_queue_cursors_rotation;
   ```

2. Restore from backup (if needed):
   ```bash
   pg_restore -d customer_v3_test backup_pre_migration.sql
   ```

3. Notify stakeholders and schedule maintenance window

---

*Document Created: 2026-08-25 by Architecture Team*
*T24 Owner: TBD | Reviewer: TBD*
*Dependencies: T21 (fencing) completed before implementation*
