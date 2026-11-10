# Good and Bad Tests

## Good Tests

**Integration-style**: Test through real interfaces, not mocks of internal parts.

```typescript
// GOOD: Tests observable behavior
test("user can checkout with valid cart", async () => {
  const cart = createCart();
  cart.add(product);
  const result = await checkout(cart, paymentMethod);
  expect(result.status).toBe("confirmed");
});
```

Characteristics:

- Tests behavior users/callers care about
- Uses public API only
- Survives internal refactors
- Describes WHAT, not HOW
- One logical assertion per test

## Bad Tests

**Implementation-detail tests**: Coupled to internal structure.

```typescript
// BAD: Tests implementation details
test("checkout calls paymentService.process", async () => {
  const mockPayment = jest.mock(paymentService);
  await checkout(cart, payment);
  expect(mockPayment.process).toHaveBeenCalledWith(cart.total);
});
```

Red flags:

- Mocking internal collaborators
- Testing private methods
- Asserting on call counts/order
- Test breaks when refactoring without behavior change
- Test name describes HOW not WHAT
- Verifying through external means instead of interface

```typescript
// BAD: Bypasses interface to verify
test("createUser saves to database", async () => {
  await createUser({ name: "Alice" });
  const row = await db.query("SELECT * FROM users WHERE name = ?", ["Alice"]);
  expect(row).toBeDefined();
});

// GOOD: Verifies through interface
test("createUser makes user retrievable", async () => {
  const user = await createUser({ name: "Alice" });
  const retrieved = await getUser(user.id);
  expect(retrieved.name).toBe("Alice");
});
```

**Tautological tests**: Expected value restates the implementation, so the test passes by construction.

```typescript
// BAD: Expected value is recomputed the way the code computes it
test("calculateTotal sums line items", () => {
  const items = [{ price: 10 }, { price: 5 }];
  const expected = items.reduce((sum, i) => sum + i.price, 0);
  expect(calculateTotal(items)).toBe(expected);
});

// GOOD: Expected value is an independent, known literal
test("calculateTotal sums line items", () => {
  expect(calculateTotal([{ price: 10 }, { price: 5 }])).toBe(15);
});
```

**Secret-echoing assertions in environment/redaction tests**: Container assertions like `unittest.TestCase.assertNotIn(secret, full_output)` dump the entire `full_output` on failure, leaking real environment variables or unredacted transcripts into test logs and subagent JSONL during the red phase.

```python
# BAD: On RED failure, unittest prints the entire full_env_output (including real secrets)
self.assertNotIn(os.environ["ANTHROPIC_API_KEY"], full_env_output)

# GOOD: Inject synthetic fake values and use a boolean assertion with a short message
fake_key = "sk-ant-synthetic-test-only"
self.assertFalse(fake_key in full_env_output, "synthetic secret leaked into child env output")
```

**Vacuous negative or invariance assertions**: Asserting that a value/call is absent (`not.toContain`, `not.toHaveBeenCalledWith`, `assertIsNone(regex.search(url))`, `! grep`) or that a collection was not mutated, while leaving the collection empty, never passing the input into the SUT, or anchoring a regex/URL matcher so narrowly (`^https://.../v1/legacy$` when real URLs carry `?tenant=...`) that the assertion can never fail.

```python
# BAD: outbox is empty so "no corrupted rows" is vacuously true; anchored regex misses ?tenant=...
db = {"outbox": [], "logs": []}
handle_delivery(db, {"id": "evt_1"})
self.assertFalse(any(r["status"] == "corrupted" for r in db["outbox"]))
self.assertIsNone(re.search(r"^https://api\.example\.com/v1/legacy$", url))

# GOOD: Pre-seed the state under guard, and pair the negative matcher with a positive control
db = {"outbox": [{"id": "msg_1", "status": "pending"}], "logs": []}
handle_delivery(db, {"id": "evt_1"})
self.assertEqual(db["outbox"], [{"id": "msg_1", "status": "pending"}])

legacy_re = re.compile(r"^https://api\.example\.com/v1/legacy(?:[/?#]|$)")
self.assertIsNotNone(legacy_re.search("https://api.example.com/v1/legacy?tenant=acme"))  # positive control
self.assertIsNone(legacy_re.search(url))
```

**Hollow read or envelope-only assertions**: Asserting only outer status, container length, or element existence (`res.status === "ok"`, `expect(items).toHaveLength(1)`, `expect(row).toBeDefined()`, `locator("tbody tr").first().toBeVisible()`) on a read or list query without asserting at least one concrete domain field on a returned item, so a broken projection or mapper that returns `[{}]` or a blank/skeleton row still passes.

```typescript
// BAD: Passes even when listProducts() maps every item to {} or drops all fields
const res = await service.listProducts();
expect(res.status).toBe("ok");
expect(res.items).toHaveLength(1);

// GOOD: Pins concrete domain fields on the returned item alongside the envelope/count
const res = await service.listProducts();
expect(res.status).toBe("ok");
expect(res.items).toEqual([
  expect.objectContaining({ id: "p1", sku: "SKU-01", label: "Sensor Pro", priceCents: 2500 }),
]);
```

**Swallowed mid-script failures in shell test runners**: Piping a test command into `tail`/`head`/`cat` without `set -o pipefail`, chaining multiple checks with `;`, or wrapping a test runner with `|| true` and only asserting `Ran N tests` instead of `OK`/exit code `0`, so a failing test in the middle is masked by the final command's `exit 0`.

```bash
# BAD: tail and py_compile overwrite unittest's non-zero exit code
python3 -m unittest discover -v 2>&1 | tail -n 5
python3 -m py_compile app.py

# GOOD: Enable strict pipefail so any stage or command failure fails the runner
set -euo pipefail
python3 -m unittest discover -v
python3 -m py_compile app.py
```

## Conditional Property-Based Testing (PBT)

When the spec's `Testing Decisions` includes conditional PBT invariants (`P1..Pn`), match the test shape to the module's category instead of forcing every property into an action-sequence loop:

- **Shape 1 — Multi-step state machines or interlocking transitions**: generate action sequences, apply each action step-by-step from a fresh state, check `P1..Pn` against an **Independent Oracle** after *every individual step* (not only at sequence end), and persist the shrunken `shrunkActions` array for replay.
- **Shapes 2–4 — Single-call conservation/accounting invariants (balances, totals, quotas, streaks), encode/decode round-trips, or idempotent/order-insensitive merges**: generate valid domain inputs directly, check `P1..Pn` against the **Independent Oracle** on the call or merge result, and persist the shrunken concrete input arguments for replay.

Structure the suite into three roles (when each role is written follows the active batch's testing mode):

1. **Concrete Capability Examples**: Deterministic examples verifying that valid inputs produce expected outputs/transitions and invalid inputs are rejected. (In `tdd` mode, missing-capability RED before implementation applies to this role.)
2. **Safety Property Guardians (`fc.property`)**: Inside `fc.property`, evaluate *only* the safety invariants `P1..Pn` over the declared applicability domain and return `false` immediately when any `Pi` fails. Do **not** assert `blockedCount > 0` or `appliedCount > 0` inside a single `fc.property` run (a valid short random run may never hit a blocked branch and would falsely fail); verify **Reachability Witnesses** (`appliedCount > 0`, `blockedCount > 0`) in Role 1 concrete examples or as an aggregate counter check *after* `fc.assert(...)` completes across the batch.
3. **Oracle Calibration & Counterexample Replay**: When an independent oracle is newly introduced, modified, or suspect, calibrate it using a **test-only known-bad state or test-local mutation** (or reuse existing control evidence from the same task) and verify that each targeted `Pi` *individually* evaluates to `false` (never test only a combined `P1 && P2` boolean). **Never add a `FAULTY_PRESET` or fault-injection switch to production code solely for testing.** When persisting a counterexample replay test, pin the complete replay context: initial state/config, concrete shrunken input (`shrunkActions` for Shape 1, concrete input arguments for Shapes 2–4, never an RNG seed alone), and expected outcome.

**Masked secondary invariant in property tests (`return true` on violation)**: Never return `true` when a secondary invariant fails inside `fc.property` to steer shrinking toward another invariant — returning `true` tells `fast-check` the run passed and silently disables that invariant.

```typescript
// BAD: Returning true on !p2StreakMonotonic masks P2 violations as passing runs
fc.property(sequenceArb, (actions) => {
  let state = createInitialState();
  for (const action of actions) {
    state = applyAlertStep(state, action);
    const { p1NoDuplicateSms, p2StreakMonotonic } = evaluateOracle(state);
    if (!p1NoDuplicateSms) return false;
    if (!p2StreakMonotonic) return true; // BUG: P2 violations are treated as PASS!
  }
  return true;
});

// GOOD: Every invariant violation returns false; calibrate P1 and P2 individually in test-local controls
fc.property(sequenceArb, (actions) => {
  let state = createInitialState();
  for (const action of actions) {
    state = applyAlertStep(state, action);
    const { p1NoDuplicateSms, p2StreakMonotonic } = evaluateOracle(state);
    if (!p1NoDuplicateSms || !p2StreakMonotonic) {
      return false;
    }
  }
  return true;
});
```


