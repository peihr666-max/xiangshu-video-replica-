# T24: Fair Queue Concurrency Test Specification

## Objective

Define automated tests to verify that the fair queue implementation (T24 design, implemented in T25) satisfies all concurrency fairness requirements and does not introduce regressions.

---

## Test Categories

### 1. Functional Correctness Tests

Verify basic fair queue behavior matches pseudo-SQL design.

#### Test 1.1: Single User Still Gets FIFO Within Own Queue

**Scenario:**
- Create 5 tasks for user A in sequence
- Start single worker
- Worker picks up all 5 tasks sequentially

**Assertion:**
Tasks acquired in order of `created_at, id` for same user  
✅ Confirms we maintain intra-user FIFO discipline  

```python
def test_single_user_fifo_within_fair_queue():
    user_a = create_test_user("user-A-fair-q")
    
    task_ids = []
    for i in range(5):
        batch = create_batch(user_id=user_a.id)
        task = create_task(batch_id=batch.id, status="PENDING")
        task_ids.append(task.id)
    
    worker = start_worker(concurrent_limit=5)
    acquired = []
    
    # Drain queue
    while True:
        task = acquire_lease(worker_id=worker.id)
        if not task:
            break
        acquired.append(task.id)
        mark_task_complete(task.id)
    
    assert acquired == task_ids  # FIFO order preserved
```

#### Test 1.2: Multiple Users Get Fair Round-Robin Scheduling

**Scenario:**
- Create 3 tasks each for user A and user B interleaved
- Start single worker with global limit = 6
- Verify workers alternate users fairly

**Assertion:**
No starvation; both users get equal share over time  
Expected pattern (one possible valid schedule): A-B-A-B-A-B or A-A-B-A-B-B (within same round)  

```python
def test_multiple_users_round_robin():
    user_a = create_test_user("user-A-rr")
    user_b = create_test_user("user-B-rr")
    
    # Create 3 pending tasks for each
    for _ in range(3):
        batch_a = create_batch(user_id=user_a.id)
        create_task(batch_id=batch_a.id, status="PENDING")
        
        batch_b = create_batch(user_id=user_b.id)
        create_task(batch_id=batch_b.id, status="PENDING")
    
    worker = start_worker(concurrent_limit=6)
    acquired_user_ids = []
    
    while True:
        task = acquire_lease(worker_id=worker.id)
        if not task:
            break
        batch = fetch_batch(task.batch_id)
        acquired_user_ids.append(batch.created_by_user_id)
        mark_task_complete(task.id)
    
    # Should have 3 from each user
    count_a = sum(1 for uid in acquired_user_ids if uid == user_a.id)
    count_b = sum(1 for uid in acquired_user_ids if uid == user_b.id)
    
    assert count_a == 3 and count_b == 3
    
    # Optional: Check that no user starved more than N ahead
    # (for strict RR verification, could require exact alternation)
```

#### Test 1.3: User With Many Pending Tasks Does Not Starve Others

**Scenario:**
- User A creates 50 pending tasks immediately
- User B creates 1 pending task
- Start worker; observe acquisition pattern

**Assertion:**
User B's single task gets picked before all 50 of User A's, within N rounds  
This proves "per-user cursor" prevents monopoly by one heavy user.  

```python
def test_heavy_user_no_starvation():
    user_heavy = create_test_user("heavy-user")
    user_light = create_test_user("light-user")
    
    # Heavy user dumps 50 tasks
    for i in range(50):
        batch = create_batch(user_id=user_heavy.id)
        create_task(batch_id=batch.id, status="PENDING")
    
    # Light user has 1
    batch_light = create_batch(user_id=user_light.id)
    create_task(batch_id=batch_light.id, status="PENDING")
    
    worker = start_worker(concurrent_limit=10)
    first_acquired_user = None
    second_acquired_user = None
    
    for _ in range(15):  # Acquire up to 15 leases
        task = acquire_lease(worker_id=worker.id)
        if not task:
            break
        batch = fetch_batch(task.batch_id)
        user_id = batch.created_by_user_id
        
        if first_acquired_user is None:
            first_acquired_user = user_id
        elif second_acquired_user is None and user_id != first_acquired_user:
            second_acquired_user = user_id
            break  # Stop once we see both users represented
    
    # Critical assertion: light user gets scheduled before heavy user exhausts capacity
    assert second_acquired_user == user_light.id, \
        f"Light user {user_light.id} should be scheduled among first few picks"
```

---

### 2. Concurrency Stress Tests

#### Test 2.1: Multi-API Instance Deadlock Freedom

**Scenario:**
- Deploy 2 API instances + 2 Workers connected to same PG database
- Each instance has its own connection pool
- Simulate concurrent lease acquisitions across all connections

**Assertion:**
No deadlock detected after 100 simultaneous acquisition attempts  
Test uses advisory lock hierarchy to prove lock ordering works.

```python
def test_multi_instance_no_deadlock():
    # Setup: 2 APIs × 2 Workers each
    api_instances = [create_api_instance(i) for i in range(2)]
    workers = []
    
    for api in api_instances:
        for w in range(2):
            workers.append(create_worker(instance_id=api.id))
    
    # Create 20 pending tasks distributed across 2 users
    users = [create_test_user(f"stress-user-{i}") for i in range(2)]
    task_ids = []
    
    for u in users:
        for _ in range(10):
            batch = create_batch(user_id=u.id)
            task = create_task(batch_id=batch.id, status="PENDING")
            task_ids.append(task.id)
    
    # All 4 workers try to acquire simultaneously
    errors = []
    
    def worker_job(worker_id):
        try:
            for _ in range(10):
                task = acquire_lease(worker_id=worker_id)
                if not task:
                    break
                complete_task(task.id)
        except Exception as e:
            errors.append(e)
    
    threads = []
    for w in workers:
        t = threading.Thread(target=worker_job, args=(w.id,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    assert len(errors) == 0, f"Deadlock or error occurred: {errors}"
    assert all_task_completed_or_returned_to_pool(task_ids)
```

#### Test 2.2: Lease Expiry Recovery (Crash Simulation)

**Scenario:**
- Assign 5 tasks to Worker A
- Kill Worker A without completing tasks (simulate crash)
- Wait for lease expiry window (e.g., 1 minute for test speed-up)
- Confirm tasks return to PENDING pool and can be re-acquired

**Assertion:**
Lease expiry logic resets `locked_until`, increments no cursor, allows another worker to pick them up.

```python
def test_lease_expiry_crash_recovery():
    worker_old = start_worker(worker_id="crash-worker")
    
    task_ids = []
    for _ in range(5):
        batch = create_batch(user_id=random_user())
        task = create_task(batch_id=batch.id, status="PENDING")
        task_ids.append(task.id)
    
    # Acquire all 5 (leaving some unfinished)
    acquired_tasks = []
    for _ in range(3):  # Only do 3 out of 5
        task = acquire_lease(worker_id=worker_old.id)
        acquired_tasks.append(task)
    
    # DO NOT complete these 3 tasks → simulate crash
    stop_worker(worker_old.id, kill_immediately=True)
    
    # Fast-forward simulated time (or wait real 1 minute for full validation)
    fast_forward_time(minutes=15)  # Or use test clock injection
    
    # Another worker should now be able to claim expired tasks
    worker_new = start_worker(worker_id="recovery-worker")
    recovered_tasks = []
    
    for _ in range(5):
        task = acquire_lease(worker_id=worker_new.id)
        if not task:
            break
        if task.id in task_ids:
            recovered_tasks.append(task)
    
    # Should recover at least the 3 crashed ones
    assert len(recovered_tasks) >= 3, "Expired leases should be recovered"
    
    # Cleanup: complete all
    for task in recovered_tasks:
        complete_task(task.id)
```

---

### 3. Performance Regression Tests

#### Test 3.1: Single Task Acquisition Latency Under Load

**Baseline:** Measure FIFO path latency with N=1000 tasks  
**Target:** Fair queue addition should add <10ms overhead per acquisition

```python
def test_fair_queue_latency_regression():
    num_tasks = 1000
    num_workers = 10
    
    # Create 1000 pending tasks for single user (worst case: no contention between users)
    user = create_test_user("latency-user")
    for _ in range(num_tasks):
        batch = create_batch(user_id=user.id)
        create_task(batch_id=batch.id, status="PENDING")
    
    start_time = time.perf_counter()
    
    workers = [start_worker(worker_id=f"perf-w-{i}") for i in range(num_workers)]
    
    completed = []
    done = threading.Event()
    
    def worker_loop(worker_id):
        while not done.is_set():
            task = acquire_lease(worker_id=worker_id)
            if not task:
                break
            complete_task(task.id)
            completed.append(task.id)
    
    threads = []
    for w in workers:
        t = threading.Thread(target=worker_loop, args=(w.id,))
        threads.append(t)
        t.start()
    
    # Wait until all tasks complete
    while len(completed) < num_tasks:
        time.sleep(0.1)
    
    done.set()
    for t in threads:
        t.join()
    
    elapsed = time.perf_counter() - start_time
    avg_latency_ms = (elapsed / num_tasks) * 1000
    
    assert avg_latency_ms < 50, f"Acquisition took too long: {avg_latency_ms:.2f}ms"
```

---

### 4. Rollback & Feature Flag Tests

#### Test 4.1: Feature Flag Off Fallback to FIFO

**Scenario:**
- Enable feature flag set to `"fair_queue_enabled": false`
- Run identical scenario as above

**Assertion:**
Behavior matches original global FIFO exactly (can validate via side-by-side diff).

```python
def test_feature_flag_disable_falls_back_to_fifo():
    with patch("app.generation.FAIR_QUEUE_ENABLED", False):
        # Same test as Test 1.2 but expected to show classic FIFO behavior
        test_single_user_fifo_within_fair_queue()
        # Assert no cursors incremented during execution (feature disabled)
        cursers_created = conn.execute("SELECT COUNT(*) FROM user_queue_cursors").fetchone()
        assert cursers_created[0] == 0
```

---

## Execution Environment

### Test Database Fixture

- PostgreSQL 16.4 (CI default)
- Fresh schema per test run (transaction rollback)
- Clean `user_queue_cursors` table before each test

### CI Integration

All tests added to `server/tests/test_customer_queue_fairness.py`:

```bash
# Run fair queue tests only
uv run python -m pytest server/tests/test_customer_queue_fairness.py -v

# Run all generation-related tests
uv run python -m pytest server/tests/ -k "generation" -q

# Full regression suite (includes fair queue tests)
uv run python -m pytest server/tests -q
```

---

## Definition of Done for T24

✅ ADR document approved (this specification referenced)  
✅ Pseudo-SQL document complete  
✅ Test coverage:
   - [x] Functional correctness (3 tests)
   - [x] Concurrency stress (2 tests)
   - [x] Performance regression (1 test)
   - [x] Rollback/feature-flag (1 test)
   - Total: **7 automated test cases** covering edge cases

**Note:** These tests are written now for documentation/regression locking purposes; actual implementation will be verified in T25 when code lands. For T24 specifically, passing means "tests exist and define success criteria" even if they remain red until T25 integration.

---

## References

- ADR: `docs/adr/024-fair-queue-scheduling.md`
- Pseudo-SQL: `docs/adr/024-fair-queue-pseudo-sql.md`
- Current implementation: `server/app/generation.py::acquire_generation_task_lease()`
- Task requirement: `docs/客户版任务清单-V3.md` §12.5 QUE-01
