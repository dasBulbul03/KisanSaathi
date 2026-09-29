# The AI boundary

KisanSaathi's assistant is a **reading and explaining layer over data the
platform already has**. It looks things up, does arithmetic, and phrases the
result. It does not decide anything, and it is not a source of truth.

This document exists because an assistant in an agriculture marketplace can do
real harm if its limits are unclear. A farmer acting on a fabricated price loses
a season. So the boundary is stated here, enforced in code, and tested.

## What it actually is

`/api/v1/ai/chat` resolves the caller's question to one of five deterministic
tools, runs it against the database, and gets back a data structure. That
structure is then turned into an answer, either by the deterministic formatter
or by a language model. The tool result is what the answer is allowed to be
based on, and it is stored on the message row as `_tool_result_summary` so any
answer can be traced to the data that produced it.

| Intent | Tool | Data it reads |
| --- | --- | --- |
| price | `_tool_price` | The caller's own lots, market prices, arrivals, open demand |
| demand | `_tool_demand` | Open buyer demands relevant to the caller's lots |
| orders | `_tool_orders` | The caller's orders and their status |
| quality | `_tool_quality` | Grade and inspection data for the caller's lots |
| logistics | `_tool_logistics` | The caller's logistics requests and quotes |

Two other endpoints exist and are also deterministic:

- `/ai/price-discovery` estimates a fair price for a lot against mandi rates,
  arrivals and open demand. Every contribution is itemised in `factors` so the
  number can be argued with.
- `/ai/recommendations` returns cached suggestions per user and kind.

## What it is not

- **Not a price guarantee.** The estimate is a range built from historical and
  seeded data. Mandi prices move on the day.
- **Not financial, legal or agronomic advice.** The system prompt says so, and
  every response carries the disclaimer regardless of which provider answered.
- **Not able to invent anything.** The prompt instructs the model to answer only
  from the supplied data block and to say plainly when the data does not answer
  the question. This is a strong instruction, not a guarantee, which is exactly
  why the deterministic path exists.
- **Not a decision maker.** Nothing in the trade lifecycle consults the
  assistant. Offers, orders, payments and inspections never depend on model
  output. The assistant reads the platform; the platform never reads the
  assistant.

## When the model is unavailable, the product still works

This is the part that actually matters.

`settings.ai_enabled` is true only when both `AI_ASSISTANT_ENABLED` is set and
`NVIDIA_API_KEY` is present. With no key, `AssistantService._client` is `None`
and `_compose` returns the deterministic formatter's answer with
`is_fallback=True`. The response is a normal 200 with a real answer, real data
cards and a real disclaimer. The frontend does not surface a degraded mode,
because there is nothing to degrade: the user asked "what is my best market" and
got the answer, computed from the database.

If a provider call fails mid-flight, the exception is caught, logged as
`assistant.llm.failed`, and the same deterministic answer is returned. A
provider outage is invisible to the user.

In production, a missing key is deliberately **not** fatal. Startup validation
requires `JWT_SECRET_KEY`; `NVIDIA_API_KEY` is noted and skipped, so a
deployment without AI is a valid deployment.

## Provider

`AI_PROVIDER` defaults to `nvidia`, with `NVIDIA_BASE_URL`,
`NVIDIA_MODEL` (`meta/llama-3.3-70b-instruct`) and
`NVIDIA_EMBEDDING_MODEL` configurable. Timeouts (45s) and retries (2) are set,
and the retry is inside the client, not the request path, so a slow provider
cannot hold a worker open indefinitely.

## Honest limitations

- The intent matcher is keyword-based. A question phrased in an unexpected way
  falls through to the general answer, which is a summary of the caller's
  current state rather than a response to their actual question. It says so.
- The demo dataset is synthetic. A price insight computed from it is a
  demonstration of the mechanism, not information about a real mandi.
- There is no live provider test in this repository. The deterministic path is
  tested; the `NVIDIA_API_KEY` path is not, because testing it needs a key and
  network access that CI should not depend on.
- Answers are English. The endpoint accepts a `language` field and stores it,
  but the deterministic formatter does not yet produce Marathi output.
