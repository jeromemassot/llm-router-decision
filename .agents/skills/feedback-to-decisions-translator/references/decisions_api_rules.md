# Gemini Decision 1 (`gemini-decision-1`) Strict Schema & Calibration Rules

Reference specification from `https://aistudio.google.com/docs/decisions-api`:

## Endpoint & Billing
- **SDK**: `google-genai >= 3.2` (`client = genai.Client(http_options={"api_version": "v1beta"})`, `client.decisions.create(model="gemini-decision-1", input=..., questions=...)`).
- **REST**: `POST https://generativelanguage.googleapis.com/v1beta/decisions` with header `x-goog-api-key`.
- **Output Tokens**: Always `0` output tokens. Up to `1,000` independent questions per request share the input prefill in one forward pass (~150–250 ms).

## Question Key & Option Key Constraints
- **Question keys**: `1..64` ASCII characters matching `^[A-Za-z0-9_-]+$`.
  - **CRITICAL**: The model NEVER sees question keys! Write the complete, unambiguous question inside `instructions`.
- **Option keys (`choice`)**: `1..128` characters, no leading/trailing spaces, no control characters.
  - **CRITICAL**: Before evaluation, `gemini-decision-1` sorts option keys alphabetically in UTF-8 byte order. Never use `"none_of_the_above"` (sorts before `"shipping"`, `"technical"`, etc.). Always use `"other"` with an explicit description like `"Anything outside these categories."`.

## Primitive Specifics

### 1. `noul` (Yes / No)
- Returns `noul` $\in [0.01, 0.99]$ and `confidence` $= \max(\text{noul}, 1 - \text{noul})$.
- **Threshold Rule**: Never set `threshold > 0.99` or `< 0.01` (a check `> 0.99` can never match). Keep practical routing gates inside `[0.05, 0.95]`.
- **Positive Phrasing Rule**: Never write negated questions like `"Is this prompt NOT complex?"`. Ask `"Is this prompt a simple single-fact lookup?"` and set `invert: true` ($1 - p_{\text{yes}}$) in code.

### 2. `choice` (Single-Select)
- `criteria`: map of `2..255` `{option_id: description}` entries.
- Returns `choice`, `probabilities` (summing to `1.0`), and `confidence`.
- Because `choice` always distributes `1.0` probability across options even on out-of-scope inputs, always check `confidence` and include `"other"`.

### 3. `score` (Ordered Rubric)
- `criteria`: list/array of `2..255` (`2..10` recommended) non-empty strings ordered strictly from **lowest (`0`) to highest (`K-1`)**.
- Returns probability-weighted expected `score` $= \sum_{k=0}^{K-1} k \cdot P(k) \in [0, K-1]$, `legend`, `probabilities`, and `confidence`.
- **Linearity Rule**: Keep adjacent rubric levels linearly spaced in complexity/severity so the expected index value is meaningful, and normalize to `[0, 1]` by dividing `score` by `K - 1`.
