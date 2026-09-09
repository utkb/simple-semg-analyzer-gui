# AI-Assisted Development Disclosure

This statement discloses the use of generative AI tools in the development of
**Simple sEMG Analyzer GUI**, as required by JOSS's AI Usage Policy.

---

## 1. Tools Used

| Tool | Provider | Where used |
|---|---|---|
| Claude Haiku 4.5, Claude Sonnet 4.6, Claude Sonnet 5, Claude Opus 4.6, Claude Opus 5 (conversational chat assistants) | Anthropic | Code (all modules under `simple_semg_analyzer/`), architecture documentation (`docs/ARCHITECTURE.md`), planning/handoff notes, GitHub issue drafting |
| Claude Fable 5 (conversational chat assistant) | Anthropic | Limited use, for general code review only |

Multiple Claude models were used across the development period as newer
versions became available; no single model was used exclusively throughout.

No other generative AI tools (e.g. GitHub Copilot, ChatGPT) were used in this
project's development.

---

## 2. Nature and Scope of Assistance

AI assistance was used throughout development, in the following ways:

- **Code generation and refactoring** — implementation of processing functions
  across `loader.py`, `pipeline.py`, `filters.py`, `ecg.py`, `detection.py`,
  `protocol.py`, `flagging.py`, `dropout.py`, `sync.py`, `features.py`, and
  `gui.py`, produced through an iterative, staged process: each development
  stage was scoped to a single concern, a rationale was discussed before any
  code was written, and the resulting code was tested against real recordings
  before being accepted.
- **Bug identification during review**, including but not limited to: the
  linear-envelope edge-curl divisor bug (§9 of `docs/ARCHITECTURE.md`), the
  requirement that dropout interpolation run before DC-offset removal, and a
  cross-correlation `mode` bug in `sync.py`'s coarse-lock alignment.
- **Documentation drafting** — `docs/ARCHITECTURE.md` was synthesized and
  drafted by the AI tool from six prior internal project documents and the
  history of development conversations, then reviewed line-by-line by the
  author, who corrected factual errors (e.g. product naming, storage format,
  attribution of specific behavior to the wrong module) before acceptance.
- **Planning and project management artifacts** — session handoff notes and a
  draft GitHub issue list, both reviewed and edited by the author before use.
- **Test scaffolding** — AST-based headless tests for GUI layout verification,
  used to check widget structure without requiring a full display.

AI was **not** used for:
- Domain-specific research decisions — electrode placement protocols (SCM,
  upper trapezius), the CCFM protocol design, and choice of processing methods
  (e.g. selecting Filtered Template Subtraction over alternatives) were
  directed by the author based on the cited literature; AI was used to help
  implement and document these decisions, not to make them.
- Any conversational interaction with JOSS editors or reviewers.

---

## 3. Confirmation of Review

I, Utku Berberoğlu, the author of this software, confirm that:

- I reviewed, tested, and validated all AI-assisted code against real
  recorded data before accepting it into the codebase.
- I made all architectural and design decisions recorded in
  `docs/ARCHITECTURE.md`, including method selection (e.g. FTS for ECG
  artifact removal), module boundaries, and data contracts; AI-generated text
  and code proposing these were accepted, modified, or rejected by me.
- I am responsible for the accuracy, originality, and correctness of all
  submitted code and documentation, regardless of whether a given passage was
  originally drafted with AI assistance.

---

*Prepared for JOSS submission alongside `docs/ARCHITECTURE.md` §14.*
