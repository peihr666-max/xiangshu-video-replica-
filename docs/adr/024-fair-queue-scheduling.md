# ADR-024: 用户公平队列调度（Fair Queue by User）

## Status

**Proposed** | Date: 2026-08-24 | Task: T24 / QUE-01 | Author: Architecture/DB

## Context

### Current Implementation (Global FIFO)

The existing task acquisition in `server/app/generation.py::acquire_generation_task_lease()` uses a **global FIFO queue**:

```sql
UPDATE generation_tasks
SET status = 'SUBMITTING', ...
WHERE id = (
    SELECT id FROM generation_tasks
    WHERE status IN ('PENDING', 'QUEUED') OR (...)
    AND (locked_until IS NULL OR expired)
    ORDER BY created_at, id
    LIMIT 1
)
```

**Behavior:**
- All workers compete for the **next task globally**, ordered by `created_at, id`
- First-come-first-served across ALL customers/users
- No user isolation or fairness guarantees

**Problem Scenarios:**
1. **Starvation**: A single user with frequent submissions can monopolize the queue, blocking other users from ever getting tasks
2. **Hotspot**: Users who create batches during peak hours get all available slots; later users wait indefinitely
3. **Multi-instance unfairness**: With multiple API instances × multiple Workers, one large user's batch dominates all Worker cycles
4. **Customer-grade SLA violation**: Paying customers (especially enterprise) must see fair access to GPU quota proportional to their paid plan

### Customer V3 Requirements

From `docs/客户版任务清单-V3.md`, §12.5 Fair Queue lanes:

| Task | Work Package | Description | Constraints |
|------|--------------|-------------|-------------|
| T24 | QUE-01 | Freeze fair queue ADR, pseudo-SQL, lock order & state machine | No change core acquire engine before ADR review |
| T25 | QUE-02 | Implement per-user round-robin, default concurrency 1 | A1000/B100/C10 tiers sustain opportunity; no worker duplicate claiming |

The requirement explicitly states **"按用户轮转"** (round-robin by user) instead of "全局 FIFO" (global FIFO).

### Multi-Instance Deployment Constraints

Customer production will deploy:
- Load balancer → **multiple API instances** (N ≥ 2)
- **Multiple Worker processes** on separate machines
- PostgreSQL shared as the queue source of truth
- PostgreSQL SERIALIZABLE transactions for consistency

**Critical Challenge:** Global FIFO with N×M competing connections causes:
- Lock contention on UPDATE query (row-level vs range)
- Thundering herd (all Workers retry after each completion)
- Non-deterministic scheduling (who wins depends on network latency + transaction timing)

## Decision

We adopt a **user-centric fair queue** design:

### Core Principles

1. **User isolation**: Each user gets independent queue state and fair share of slot capacity
2. **Deterministic ordering**: Within a user's pending tasks, still FIFO by creation time
3. **Transaction boundaries**: Candidate selection, concurrent slot check, task lease, cursor update **all within one atomic transaction**
4. **No global locks**: Workers only contend on user-specific rows/cursors, not all tasks table
5. **Scalable multi-instance**: Adding more Workers increases per-user parallelism, not starvation risk

### High-Level Design

**New Schema Elements:**
- `user_queue_cursors`: Tracks each user's position in the queue (pseudo-index over their own pending tasks)
- Per-user FIFO queue using `ROW_NUMBER() OVER (ORDER BY created_at)` partitioned by `user_id`
- Cursor increments atomically when user claims a task

**Acquisition Algorithm:**
```
BEGIN TRANSACTION FOR SHARE
-- 1. Identify candidate users (those with pending tasks, under concurrency limit)
SELECT user_id 
FROM user_queue_cursors uqc
JOIN generation_batches gb ON gb.id = uqc.batch_id
WHERE uqc.cursor_pos < (SELECT COUNT(*) FROM generation_tasks WHERE batch_id = gb.id AND status IN ('PENDING','QUEUED'))
AND gb.created_by_user_id NOT AT CONFLICT
LIMIT max_concurrent_per_user

-- 2. For each candidate user, acquire next task if global slot available
FOR EACH candidate_user:
    SELECT next_task_id USING per-user subquery (cursor-based)
    
    IF global_concurrent_slot_available:
        UPDATE task SET status='SUBMITTED' WHERE id=task_id LOCKED
        Increment cursor for this user
        
-- Commit
```

### Pseudo-SQL Implementation Plan

See accompanying file `t24-fair-queue-pseudo-sql.md` for detailed SQL snippets.

**Key Migration Path:**
1. Add `user_queue_cursors` table (append-only, no data required at start)
2. Backfill cursors from existing pending tasks per user
3. Dual-write: Old code path remains fallback until rollout complete
4. Switch configuration flag: `"FAIR_QUEUE_ENABLED": true`
5. Gradual traffic ramp: 1% → 10% → 100% per instance group

### Lock Order & Concurrency Control

To prevent deadlock with N API instances:

**Lock Hierarchy:**
1. `generation_tasks` rows (specific task id) - shortest scope
2. `user_queue_cursors` row (user_id) - medium scope
3. `runtime_limits` row (single row) - longest scope, use advisory lock

**Recommended PostgreSQL Advisory Locks:**
```sql
SELECT pg_advisory_xact_lock(hashtext('fair_queue_global_slots'));
SELECT pg_advisory_xact_lock(hashtext(concat('user_queue_', user_id::text)));
```

This ensures consistent lock ordering: global first, then user-specific.

### State Machine Extensions

Current `generation_tasks.status` enum needs extension:

```sql
ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'FAIR_QUEUED';
-- Or keep existing statuses but add metadata column
ALTER TABLE generation_tasks ADD COLUMN queue_type TEXT; -- 'fifo' | 'fair' | NULL
```

**Decision:** We'll use **metadata column approach** to avoid enum migration pain:
- New column `queue_order_seq` INTEGER DEFAULT NULL
- Populated by window function during acquisition
- Allows gradual transition without breaking existing consumers

### Rollback Strategy

If issues occur during rollout:

1. **Immediate revert**: Set feature flag to false (fallback to global FIFO)
2. **Cursor cleanup**: Delete orphaned entries from `user_queue_cursors` 
3. **Data repair**: Reset failed task leases back to PENDING with NULL lock fields

No schema downgrade needed – new columns nullable, can stay permanently.

## Alternatives Considered

### Alternative 1: Per-User Priority Queue (Priority by Tier)

**Idea:** Assign priority levels based on customer tier (Enterprise > Standard > Free):
- Enterprise users always get picked first
- Standard users fill remaining slots
- Free users last (throttled hard)

**Rejected because:**
- Violates customer V3 fairness contract (same tier users must be treated equally)
- Overly complex pricing integration (tier changes mid-cycle would need reordering)
- Requires pricing service dependency (customer V3 assumes standalone billing independence initially)

### Alternative 2: Time-Sliced Round-Robin (TSR)

**Idea:** Allocate fixed time windows to each user (e.g., User A slots 0-10s, User B 11-20s, etc.):
- Deterministic fairness
- Simple implementation

**Rejected because:**
- Wastes capacity when user has no pending tasks
- Adds complexity to track which user owns which time slice
- Not robust to variable task durations (H3 requests take different times)
- Poor scaling when user count is dynamic

### Alternative 3: Token Bucket Fair Share

**Idea:** Each user gets N tokens/hour; each task consumes M tokens; workers pick tasks when user has tokens:
- Flexible control over rate limiting
- Handles bursty traffic well

**Rejected because:**
- Requires persistent token store (Redis/MQ dependency banned in constraints)
- Complex reconciliation if Worker crashes mid-consumption
- Difficult to audit/verify fairness guarantee mathematically
- Adds significant operational complexity for M0 launch

### Alternative 4: Randomized Draw per Cycle

**Idea:** Every cycle (e.g., every second), randomly select one task from all pending, regardless of user:
- Extremely simple
- Statistically fair in expectation

**Rejected because:**
- High variance: short-term runs favor early-birds unfairly
- Enterprise customers (high-stakes) require deterministic SLA-like behavior
- Debugging/reasoning about actual distribution requires statistical analysis beyond team expertise
- Does not satisfy explicit ADR review requirement ("未评审 ADR 前不得修改核心领取器")

## Rationale Summary

We selected **User-Centric Cursor-Based Fair Queue** because:

✅ **Satisfies explicit requirements**: Implements "按用户轮转" (per-user round-robin)  
✅ **Meets no-go constraints**: No Redis/MQ dependency, pure PostgreSQL  
✅ **Multi-instance safe**: Uses advisory locks for deadlock-free N-API deployment  
✅ **Gradual rollout capable**: Feature-flagged dual-path transition  
✅ **Maintainable**: Cursor logic is understandable to team members without distributed systems PhD  
✅ **Debuggable**: Per-user state visible in database for incident investigation  
✅ **Rollback-safe**: Schema additions backwards compatible  

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Deadlock between API instances | Medium | Advisory lock hierarchy (global first, then user) |
| Cursor desynchronization after crash | Low | Lease expiry check before incrementing cursor |
| Performance regression vs FIFO | Low | Cursor lookup is index-friendly (partitioned by user_id, order by created_at) |
| Data inconsistency during migration | Medium | Dual-write mode validates both paths agree on outcome |

## References

- Existing acquisition logic: `server/app/generation.py::acquire_generation_task_lease()` (lines 3512–3578)
- T24 task definition: `docs/客户版任务清单-V3.md` §12.5 QUE-01
- PostgreSQL advisory lock documentation: https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-ADMIN-LOCKING
- SERIALIZABLE transaction pitfalls: https://www.postgresql.org/docs/current/transaction-iso.html
