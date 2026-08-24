# T24: 用户公平队列伪 SQL 实现方案

## Overview

本文档提供 ADR-024 中定义的用户公平队列调度系统的详细 SQL 设计方案，用于指导 T25 的实际实现。

---

## Schema Changes

### 1. New Table: `user_queue_cursors`

Tracks each user's current position in their fair queue, enabling cursor-based task selection without full table scan.

```sql
CREATE TABLE IF NOT EXISTS user_queue_cursors (
    id BIGSERIAL PRIMARY KEY,
    
    -- Which user this cursor belongs to
    user_id TEXT NOT NULL,
    
    -- Optional: track which batch they're currently processing (for multi-batch users)
    batch_id TEXT NULL,  -- REFERENCES generation_batches(id) ON DELETE CASCADE
    
    -- Current cursor position: number of tasks THIS USER has claimed from PENDING/QUEUED state
    -- Starts at 0; increments by 1 per successful acquisition
    claim_count INTEGER NOT NULL DEFAULT 0,
    
    -- Metadata for debugging/monitoring
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Uniqueness constraint: one active cursor per user
    CONSTRAINT user_queue_cursor UNIQUE (user_id)
);

-- Indexes for efficient lookups
CREATE INDEX idx_user_queue_cursors_user_id ON user_queue_cursors(user_id);
CREATE INDEX idx_user_queue_cursors_claim_count ON user_queue_cursors(claim_count DESC);

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_user_queue_cursors_updated_at
BEFORE UPDATE ON user_queue_cursors
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
```

---

### 2. Backfill Existing Pending Tasks

Populate cursors for all users who already have pending/queued tasks:

```sql
INSERT INTO user_queue_cursors (user_id, claim_count)
SELECT DISTINCT 
    gb.created_by_user_id AS user_id,
    0 AS claim_count
FROM generation_tasks gt
JOIN generation_batches gb ON gt.batch_id = gb.id
WHERE gt.status IN ('PENDING', 'QUEUED')
ON CONFLICT (user_id) DO NOTHING;
```

This ensures users with existing work aren't disadvantaged when fair queue activates.

---

### 3. Fair Queue Task Acquisition Logic

The core function that replaces the global FIFO logic:

```sql
-- Creates a "next available task for user X" query that respects:
-- 1. User's own queue order (by creation time)
-- 2. User's cumulative claim count
-- 3. Global concurrency limits

WITH RECURSIVE candidate_selection AS (
    -- Step 1: Find N users who should be eligible for slot allocation
    -- N = max_concurrent_h3_tasks (from runtime_limits configuration)
    SELECT 
        uqc.user_id,
        COUNT(*) FILTER (
            WHERE gt.status IN ('PENDING', 'QUEUED')
            AND (gt.locked_until IS NULL OR gt.locked_until < CURRENT_TIMESTAMP)
        ) AS available_for_this_user
    FROM user_queue_cursors uqc
    JOIN generation_batches gb ON gb.created_by_user_id = uqc.user_id
    LEFT JOIN generation_tasks gt ON gt.batch_id = gb.id
                                    AND gt.status IN ('PENDING', 'QUEUED', 'ARCHIVE_FAILED')
    GROUP BY uqc.user_id
    HAVING COUNT(*) FILTER (...) > 0
    ORDER BY uqc.claim_count ASC, uqc.created_at ASC  -- Prioritize users who've waited longest
    LIMIT :max_global_concurrent_slots
),

task_selection AS (
    -- Step 2: For each candidate user, pick next unclaimed task
    SELECT 
        cs.user_id,
        gt.id AS task_id,
        gt.batch_id,
        gt.created_at AS task_created_at
    FROM candidate_selection cs
    JOIN generation_batches gb ON gb.created_by_user_id = cs.user_id
    JOIN generation_tasks gt ON gt.batch_id = gb.id
                                AND gt.status IN ('PENDING', 'QUEUED', 'ARCHIVE_FAILED')
                                -- Lock ordering: specific task row
    WHERE 
        -- Only pick task if user hasn't exceeded their per-user concurrency
        (
            SELECT COUNT(*) FROM generation_tasks t2
            WHERE t2.batch_id = gb.id
              AND t2.status IN ('SUBMITTING', 'QUEUED', 'RUNNING', 'ARCHIVING')
        ) < :max_concurrent_per_user
        -- Task is not locked or expired
        AND (gt.locked_until IS NULL OR gt.locked_until < CURRENT_TIMESTAMP)
        -- No poll timeout blocking
        AND (gt.next_poll_at IS NULL OR gt.next_poll_at < CURRENT_TIMESTAMP)
    ORDER BY gt.created_at ASC, gt.id ASC  -- Keep FIFO within user's own tasks
    LIMIT 1
    FOR UPDATE OF gt NOWAIT  -- Prevent deadlock on lock contention
)

-- Final UPDATE: acquire task and increment cursor
UPDATE generation_tasks gt SET
    status = 'SUBMITTING',
    locked_by = :worker_id,
    locked_until = :locked_until,
    submitted_at = COALESCE(gt.submitted_at, CURRENT_TIMESTAMP),
    updated_at = CURRENT_TIMESTAMP
FROM task_selection ts
WHERE gt.id = ts.task_id
RETURNING gt.id;

-- Concurrent cursor increment (in same transaction):
UPDATE user_queue_cursors uqc
SET 
    claim_count = claim_count + 1,
    updated_at = CURRENT_TIMESTAMP
WHERE uqc.user_id = :selected_user_id
AND uqc.claim_count = :expected_old_value  -- Optimistic locking guard
RETURNING uqc.claim_count;
```

**Usage in application code (Python pseudo-code):**

```python
def acquire_generation_task_lease_fair(conn: BusinessConnection, worker_id: str) -> dict | None:
    """
    Acquire next task using fair queue algorithm instead of global FIFO.
    
    Transactional boundary: everything in one SERIALIZABLE transaction.
    """
    locked_until = datetime.now(UTC) + timedelta(seconds=GENERATION_LEASE_SECONDS)
    
    with conn.cursor() as cur:
        # Start transaction (SERIALIZABLE)
        cur.execute("BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        
        try:
            # Acquire global slot allocation lock
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(:lock_key))",
                {"lock_key": "fair_queue_global_allocation"}
            )
            
            # Execute the complex CTE query above with parameters
            cur.execute("""
                WITH RECURSIVE ... -- See full query above
            """, {
                "max_global_concurrent_slots": read_runtime_limits(conn)["max_concurrent_h3_tasks"],
                "max_concurrent_per_user": 1,  # Configurable later based on tier
                "worker_id": worker_id,
                "locked_until": locked_until.isoformat(),
            })
            
            result = cur.fetchone()
            if not result:
                conn.commit()
                return None
            
            task_id = result["id"]
            selected_user_id = result["user_id"]
            
            # Increment cursor atomically (optimistic locking included)
            expected_cursor = read_user_cursor(cur, selected_user_id)
            cur.execute(
                "UPDATE user_queue_cursors SET claim_count = $1 WHERE user_id = $2 AND claim_count = $3",
                (expected_cursor + 1, selected_user_id, expected_cursor)
            )
            
            if cur.rowcount != 1:
                raise RuntimeError(f"Cursor desynchronized! Expected {expected_cursor}, got conflict")
            
            conn.commit()
            
            # Load full task payload
            return load_worker_task(conn, task_id)
            
        except Exception:
            conn.rollback()
            raise
```

---

### 4. Lease Recovery (Crash Handling)

If Worker crashes without renewing lease, tasks need automatic recovery:

```sql
-- Mark expired leases needing attention
UPDATE generation_tasks SET
    status = CASE 
        WHEN archive_status = 'ARCHIVE_FAILED' AND provider_result_url IS NOT NULL
        THEN 'RECOVERING_FROM_ARCHIVE_FAILURE'  -- Special retry path
        ELSE 'QUEUED'  -- Reset to pool for re-selection
    END,
    locked_by = NULL,
    locked_until = NULL,
    updated_at = CURRENT_TIMESTAMP
WHERE locked_until < CURRENT_TIMESTAMP - INTERVAL '15 minutes'
  AND status IN ('SUBMITTING', 'RUNNING', 'ARCHIVING');

-- Optional: notify monitoring system of crashed assignments
INSERT INTO audit_log (event_type, entity_type, entity_id, details)
SELECT 
    'LEASE_EXPIRED_RECOVERY',
    'task',
    gt.id::TEXT,
    jsonb_build_object(
        'old_locked_by', gt.locked_by,
        'expired_at', gt.locked_until,
        'recovered_at', CURRENT_TIMESTAMP
    )
FROM generation_tasks gt
WHERE status = 'RECOVERING_FROM_ARCHIVE_FAILURE';
```

**Key point:** Cursor remains pointing at same position – we don't increment it when task expires, allowing another task from that user to be picked up.

---

### 5. Configuration / Feature Flag

Add runtime config to enable/disable fair queue gradually:

```sql
ALTER TABLE runtime_config ADD COLUMN IF NOT EXISTS fair_queue_enabled BOOLEAN DEFAULT FALSE;

-- Toggle during deployment:
UPDATE runtime_config SET value = 'true' WHERE key = 'fair_queue_enabled';

-- Or use PostgreSQL table:
CREATE TABLE IF NOT EXISTS feature_flags (
    flag_name TEXT PRIMARY KEY,
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    version INT8 NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO feature_flags (flag_name, is_enabled) VALUES ('fair_queue', true)
ON CONFLICT (flag_name) DO UPDATE SET 
    is_enabled = EXCLUDED.is_enabled,
    updated_at = CURRENT_TIMESTAMP;
```

Application checks:

```python
FAIR_QUEUE_ENABLED = read_feature_flag('fair_queue', default=False)

def acquire_generation_task_lease(conn, worker_id):
    if FAIR_QUEUE_ENABLED:
        return acquire_generation_task_lease_fair(conn, worker_id)
    else:
        # Fall back to original global FIFO implementation
        return acquire_generation_task_lease_fifo(conn, worker_id)
```

---

### 6. Monitoring & Observability

Track fairness metrics via SQL views:

```sql
CREATE VIEW v_user_queue_stats AS
SELECT 
    uqc.user_id,
    uqc.claim_count AS total_tasks_claimed,
    COUNT(DISTINCT gt.id) AS total_pending_tasks_in_system,
    (
        SELECT COUNT(*) FROM generation_tasks t2
        WHERE t2.status IN ('SUBMITTING', 'RUNNING', 'ARCHIVING')
          AND t2.batch_id IN (SELECT id FROM generation_batches WHERE created_by_user_id = uqc.user_id)
    ) AS currently_active_tasks,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - uqc.created_at)) AS seconds_since_registration,
    CASE 
        WHEN uqc.created_at < CURRENT_TIMESTAMP - INTERVAL '1 hour' AND uqc.claim_count = 0
        THEN 'STARVATED'
        ELSE 'ACTIVE'
    END AS starvation_check
FROM user_queue_cursors uqc
CROSS JOIN generation_batches gb
LEFT JOIN generation_tasks gt ON gt.batch_id = gb.id 
                               AND gt.status IN ('PENDING', 'QUEUED');

-- Alert queries (run every minute via external monitor):
SELECT user_id FROM v_user_queue_stats WHERE starvation_check = 'STARVATED';
```

---

## Migration Checklist

1. ✅ Create `user_queue_cursors` table  
2. ✅ Backfill cursors from existing pending tasks  
3. ✅ Add `v_user_queue_stats` view for monitoring  
4. ✅ Implement dual-path acquire engine (fair vs fallback FIFO)  
5. ✅ Deploy with `"fair_queue_enabled": false` initially  
6. ✅ Run parallel tests: compare outputs of both paths match for first week  
7. ✅ Gradual rollout: 1% traffic → 10% → 50% → 100% over multiple releases  
8. ✅ Monitor `v_user_queue_stats` for starvation anomalies during ramp  
9. ✅ Retire old FIFO code after 2 release cycles (optional technical debt cleanup)  

---

## Dependencies for T25

T25 implementation depends on:
- ✅ This pseudo-SQL design document approved  
- ✅ Schema migration scripts created (based on above)  
- ✅ Code integration points identified (`generation.py::acquire_generation_task_lease`)  
- ✅ Test fixtures defined (see separate test design doc)  

---

## References

- ADR reference: `docs/adr/024-fair-queue-scheduling.md`
- Current implementation: `server/app/generation.py::acquire_generation_task_lease()` (lines 3512–3578)
- PostgreSQL advisory lock docs: https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-ADMIN-LOCKING
- T24 task requirement: `docs/客户版任务清单-V3.md` §12.5 QUE-01
