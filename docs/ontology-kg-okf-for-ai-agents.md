# Ontologies, Knowledge Graphs and the Open Knowledge Format (OKF)
### How structured knowledge improves AI agents, RAG and LLM responses

*Written October 2026. OKF details are based on the v0.2 specification published in the GoogleCloudPlatform/knowledge-catalog repository (`okf/SPEC.md`).*

---

## 1. Executive summary

LLMs are fluent but not inherently *grounded*. They don't know your company's definition of "revenue," which table is the source of truth for orders, or whether a runbook was updated last week. Agents make this worse: they act on what they believe, so a wrong belief becomes a wrong action.

Three ideas address this at different layers:

| Layer | What it is | Role |
|---|---|---|
| **Ontology** | A formal vocabulary of concepts, properties and relationship types in a domain | Defines *what exists and what it means* |
| **Knowledge graph (KG)** | Instances of those concepts, connected by typed relationships | Stores *what is true* and lets you traverse it |
| **Open Knowledge Format (OKF)** | A minimal file format: a directory of markdown files with YAML frontmatter | Packages and ships knowledge so humans and agents can read, write and exchange it |

The key insight: **ontologies and KGs are about *structure and semantics*; OKF is about *portability, trust and maintainability* of knowledge in a form agents can consume with no special tooling.** They are complementary, not competing.

---

## 2. The problem these tools solve

Without curated knowledge, LLM-based systems typically suffer from:

1. **Hallucination**: plausible but invented facts, column names, metric definitions.
2. **Ambiguity**: "customer," "active user," or "margin" mean different things in different teams.
3. **Stale or unattributed context**: retrieved chunks have no indication of age, author or reliability.
4. **Weak multi-hop reasoning**: plain vector search finds *similar text*, not *connected facts* (e.g. "which dashboards depend on the table that failed last night?").
5. **Context bloat**: dumping large amounts of raw text into the prompt costs tokens and dilutes signal.
6. **Unverifiable numbers**: the agent writes its own SQL and nobody can tell whether it matches the sanctioned calculation.

---

## 3. Ontology

### What it is
An ontology is an explicit, shared model of a domain: the **classes** (Customer, Order, Metric), their **properties** (order has `total_usd`), and the **relationship types** allowed between them (Customer *places* Order; Metric *is computed from* Table). Formal ontologies (OWL, RDFS, SKOS, schema.org-style vocabularies) can also encode constraints and enable inference (e.g. every `PremiumCustomer` is a `Customer`).

### How it helps AI systems
- **Shared meaning**: gives humans, agents and tools one vocabulary, reducing ambiguity.
- **Query planning**: an agent that knows `Order → placed_by → Customer` can plan joins and lookups instead of guessing.
- **Validation**: output can be checked against allowed types and relations.
- **Entity linking**: mapping a user's phrase ("rev") to a canonical concept (`Metric: Recognized Revenue`).
- **Prompt scaffolding**: a compact ontology fragment in the prompt tells the model the "shape" of the world it's operating in.

### Limitation
Heavyweight ontologies are costly to design and maintain, and many teams never finish them. That's a major reason lightweight approaches are attractive.

---

## 4. Knowledge graphs

### What it is
A knowledge graph represents knowledge as **entities (nodes)** and **relationships (edges)**, often as triples such as `(Orders table) —joins_with→ (Customers table)`. The ontology is the schema; the KG is the populated data.

### How it helps AI systems
- **Multi-hop retrieval**: follow edges to gather connected context (dependency chains, lineage, ownership).
- **Disambiguation**: entities have stable identities, so "Apple" the company and "apple" the fruit don't collide.
- **Explainability**: the path from question to answer is inspectable.
- **Aggregation across sources**: documents, tables, APIs and people can all be nodes in one graph.
- **GraphRAG patterns**: retrieve a subgraph (neighbors, communities, paths) alongside or instead of text chunks, then give that to the LLM.

### Limitation
Building and syncing a graph requires extraction pipelines, a graph store, and ongoing curation. Stale edges are as harmful as stale documents.

---

## 5. Open Knowledge Format (OKF)

### 5.1 What the spec says

OKF (v0.2) is described as an open, human- and agent-friendly format for the *metadata, context and curated insight* that surrounds data and systems. Its design choices are deliberately minimal:

- A **bundle** is a directory tree of markdown files, distributable as a git repo, archive or subdirectory.
- Each **concept** is one markdown file with **YAML frontmatter** plus a free-form body.
- The only required frontmatter field is `type`. Everything else is optional.
- There's **no schema registry, no central authority and no required tooling**. If you can `cat` a file you can read OKF; if you can `git clone` you can ship it.
- Concept `type` values aren't centrally registered; consumers must tolerate unknown types.

The spec's stated motivation is that knowledge corpora are increasingly **written and maintained by agents**, which creates five questions a consumer needs answered:

1. **Provenance**: what was this created from?
2. **Trust**: how much should I trust it?
3. **Freshness**: is it still true?
4. **Lifecycle**: is it the current version?
5. **Attestation**: was this number produced the way we said it must be?

### 5.2 Core building blocks

| Element | Purpose |
|---|---|
| `type`, `title`, `description`, `resource`, `tags` | Identity and routing. `resource` is a URI to the underlying asset (e.g. a BigQuery table) |
| Markdown **links** between concepts | Express relationships (an untyped directed edge; the *kind* of relationship is conveyed by surrounding prose) |
| `index.md` | Directory listing for **progressive disclosure**, so an agent can see what's available before opening documents |
| `log.md` | Chronological update history |
| `sources` | Provenance, with optional credibility signals: `author`, `usage_count`, `last_modified` |
| Footnotes keyed to `sources[].id` | Per-claim attribution |
| `generated` / `verified` | Who wrote the content and who/what confirmed it (actors like `human:<id>`, `process:<id>`, `<producer>/<version>`) |
| **Trust tiers** (derived) | *unverified* → *machine-confirmed* → *human-reviewed*, derived from `verified` |
| `status` | `draft` / `stable` / `deprecated` |
| `stale_after` | Absolute timestamp after which content is considered stale |
| **Attested Computation** concept type | A sanctioned way to compute a value, with `runtime`, `parameters`, `executor` and `attester` |

### 5.3 Example concept

```markdown
---
type: BigQuery Table
title: Customer Orders
description: One row per completed customer order across all channels.
resource: https://console.cloud.google.com/bigquery?p=acme&d=sales&t=orders
tags: [sales, orders, revenue]
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-05-28T14:30:00Z }
---

# Schema

| Column        | Type      | Description                              |
|---------------|-----------|------------------------------------------|
| `order_id`    | STRING    | Globally unique order identifier.        |
| `customer_id` | STRING    | Foreign key into [customers](/tables/customers.md). |
| `total_usd`   | NUMERIC   | Order total in US dollars.               |

# Joins

Joined with [customers](/tables/customers.md) on `customer_id`.
```

### 5.4 Attested Computation: the standout idea

For numbers that matter (revenue, margin, churn), OKF lets you define a **sanctioned computation** as its own concept. The agent may only supply *values for declared parameters*; it must not author or edit the computation. After a run:

1. The **executor** runs the bound computation and returns a **receipt** (e.g. `job_id`, `executed_sql`, `result`).
2. A deterministic, no-LLM **attester** checks that what actually ran equals the sanctioned computation bound with the claimed parameters, and that the displayed value matches the authoritative source.
3. A consumer can **refuse to display a failing attestation**, and warn or refuse when `now >= stale_after`.

This turns "did the agent compute this correctly?" from a judgement call into a mechanical comparison. The spec notes that the full runtime protocol (receipt/verdict wire formats, attester ABI, sandboxing) is deferred to future revisions, so treat this as an emerging design rather than a finished standard.

### 5.5 Where OKF sits relative to ontologies and KGs

OKF is **not** an ontology language like OWL, and not a graph database. Its links are untyped, and it doesn't prescribe a taxonomy of concept types. What it gives you instead:

- A **lightweight, graph-shaped corpus**: concepts are nodes, markdown links are edges, and frontmatter carries typed attributes. A consumer can load a bundle into a real graph store if it wants typed edges.
- A **place to put an ontology's output**: the `type` field can mirror your ontology's classes, and prose or extra frontmatter keys can name the relationship kinds. Unknown keys are preserved by design, so this is allowed.
- **Operational metadata** (provenance, trust, freshness, lifecycle) that most ontologies and KGs leave to ad hoc conventions.

---

## 6. How they work together

| Concern | Ontology | Knowledge graph | OKF |
|---|---|---|---|
| Primary job | Define meaning and allowed structure | Store and traverse connected facts | Package, version, exchange and trust-annotate knowledge |
| Format | OWL/RDFS/SHACL, etc. | Triples / property graph | Markdown + YAML in a directory |
| Tooling needed | Reasoners, editors | Graph DB, query language | None required (git + text editor) |
| Formality | High | Medium | Low (intentionally) |
| Best at | Consistency, inference | Multi-hop queries, lineage | Human/agent co-authoring, portability, trust signals |
| Typical weakness | Heavy to build | Needs pipelines and curation | Untyped links; no built-in inference or query engine |

**A practical combination:**

1. Use a **light ontology** (even a one-page list of concept types and relationship names) to keep vocabulary consistent.
2. Store curated knowledge as an **OKF bundle** in git so humans and agents can both edit it and every change is diffable.
3. Optionally **project the bundle into a graph** (concepts → nodes, links → edges, `type`/`tags` → labels) for multi-hop retrieval.
4. Feed **both** to the agent: graph traversal for structure, OKF concept bodies for rich, citable detail.

---

## 7. Building AI agents

Agents need four things: to know what's available, to understand it, to act on it, and to know when to be careful. Each maps to these tools.

### 7.1 Discovery
- **`index.md` + progressive disclosure**: the agent reads a short listing first, then opens only relevant concepts. This is cheaper and more focused than loading an entire corpus.
- **`type` and `tags`**: cheap routing filters ("only `Playbook` concepts tagged `oncall`").

### 7.2 Understanding
- **Concept bodies** carry definitions, schemas, joins and examples in structured markdown, which agents parse well.
- **Links** let the agent walk from a table to its metric to its playbook.
- **Ontology/KG layer** supplies canonical entities and relationship types for planning.

### 7.3 Acting safely
- **Attested Computations** constrain agents to sanctioned calculations for high-stakes numbers.
- **`resource` URIs** tell the agent what real asset a concept corresponds to.
- **Playbooks** (as OKF concepts) encode procedures the agent should follow instead of improvising.

### 7.4 Knowing what to trust
- **Trust tier, `status`, `stale_after`** let the agent (or its harness) decide: use, use with a caveat, ask a human, or refuse.
- **Per-source credibility signals** (`author`, `usage_count`, `last_modified`) allow inference like "this source is actively used and recently modified."

### 7.5 Writing knowledge back
Because OKF is plain files, agents can **maintain the corpus**: generate concepts, update `log.md`, and record themselves in `generated.by`. Humans review via normal pull requests and add `verified: human:<id>`, so the trust tier rises only through real review.

---

## 8. Retrieval-Augmented Generation (RAG)

### 8.1 Where classic RAG struggles
Chunk-and-embed pipelines lose structure, lack provenance, can't tell fresh from stale, and handle multi-hop questions poorly.

### 8.2 How each layer improves RAG

**Ontology**
- Query understanding: normalize synonyms and map phrases to canonical concepts before retrieval.
- Query expansion with narrower/broader terms.

**Knowledge graph**
- **Graph-augmented retrieval**: start from entities in the question, expand to neighbors or paths, and include those facts as context.
- Better answers to relational questions (lineage, ownership, dependencies).
- Retrieval you can explain: "these 4 concepts were included because they're linked from X."

**OKF**
- **Concept-level chunking**: one concept = one coherent unit with a title, description and type. This avoids arbitrary mid-paragraph splits.
- **Hybrid retrieval**: embed `title + description + body` for semantic search; use frontmatter (`type`, `tags`, `status`) for exact-match filters.
- **Metadata-aware ranking and filtering**: drop `deprecated` concepts, down-rank or flag those past `stale_after`, prefer human-reviewed content.
- **Link-following**: after retrieving a hit, include its linked concepts (a bounded "neighborhood").
- **Citations**: footnotes keyed to `sources[].id` let the answer attribute specific claims to specific sources.
- **Progressive disclosure**: retrieve index entries first, then fetch full concepts only when needed.

### 8.3 Illustrative retrieval flow

```text
1. Parse the question → map terms to canonical concepts (ontology / tags).
2. Retrieve candidates:
     a. vector search over concept title+description+body
     b. metadata filter: type, tags, status != deprecated
3. Expand: follow links 1-2 hops from top hits (graph traversal).
4. Score and filter:
     - drop deprecated; flag or drop stale (now >= stale_after)
     - boost human-reviewed > machine-confirmed > unverified
     - boost sources with recent last_modified / healthy usage_count
5. Assemble a compact context pack: concept bodies + source ids.
6. Generate the answer with footnote-style attribution.
7. For numeric claims backed by an Attested Computation: run it, attest, then display.
```

### 8.4 Illustrative trust/staleness helper

A consumer-side sketch showing how little code is needed to derive trust tiers and staleness from OKF frontmatter (illustrative, not part of the spec):

```python
from datetime import datetime, timezone
import yaml

def load_concept(path):
    text = open(path, encoding="utf-8").read()
    _, fm, body = text.split("---", 2)
    return yaml.safe_load(fm), body

def _as_dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))

def trust_tier(meta):
    v = meta.get("verified")
    if not v:
        return "unverified"
    if isinstance(v, dict):        # spec: a bare mapping is a one-element list
        v = [v]
    if any(str(e.get("by", "")).startswith("human:") for e in v):
        return "human-reviewed"
    return "machine-confirmed"

def is_stale(meta, now=None):
    s = meta.get("stale_after")
    now = now or datetime.now(timezone.utc)
    return bool(s) and now >= _as_dt(s)

def usable(meta):
    return meta.get("status", "stable") != "deprecated"
```

---

## 9. Optimizing LLM responses

| Goal | How structured knowledge helps |
|---|---|
| **Fewer hallucinations** | The model answers from retrieved, attributed concepts rather than from parametric memory alone. Instructing it to say "not in the knowledge base" when retrieval is empty reinforces this. |
| **Higher accuracy on domain terms** | Ontology and concept definitions pin down meanings (e.g. what "recognized revenue" includes). |
| **Verifiable numbers** | Attested Computations ensure the number came from the sanctioned query, and the attester catches rewritten SQL or swapped files. |
| **Freshness** | `stale_after`, `status`, `generated.at` and `sources[].last_modified` let the system avoid or flag outdated facts. |
| **Calibrated confidence** | Trust tier can drive phrasing: "per the human-reviewed definition…" vs. "based on an unverified draft…". |
| **Lower token cost, better focus** | Progressive disclosure and concept-level retrieval send fewer, more relevant tokens. Structured markdown (headings, tables) is easy for models to parse. |
| **Consistency across agents/sessions** | A single shared bundle becomes a common source of truth instead of each agent improvising. |
| **Traceability and auditing** | Footnote citations, `generated`/`verified` history and git diffs show where an answer came from and who approved it. |
| **Better multi-step reasoning** | Link/graph neighborhoods supply the connected facts needed for multi-hop questions. |

### Prompting pattern (sketch)

```text
You answer using ONLY the provided knowledge concepts.
- Cite sources using the footnote labels given.
- If a concept is marked stale or deprecated, say so.
- If trust tier is "unverified", qualify the claim.
- For any figure, use the attested value; do not compute it yourself.
- If the concepts don't cover the question, say you don't know.
```

---

## 10. Reference architecture

```text
            ┌───────────────────────────────┐
 Sources →  │ Extraction / authoring agents │  (docs, schemas, dashboards, humans)
            └──────────────┬────────────────┘
                           ▼
            ┌───────────────────────────────┐
            │   OKF bundle in git           │  concepts, index.md, log.md
            │   (provenance, trust, status) │  reviewed via pull requests
            └───────┬───────────────┬───────┘
                    │               │
          index / embed        project to graph (optional)
                    ▼               ▼
            ┌─────────────┐   ┌─────────────┐
            │ Vector /    │   │ Knowledge   │ ← ontology-guided types & relations
            │ keyword idx │   │ graph       │
            └──────┬──────┘   └──────┬──────┘
                   └──────┬──────────┘
                          ▼
            ┌───────────────────────────────┐
            │ Retrieval layer               │ filter · expand · rank by trust/freshness
            └──────────────┬────────────────┘
                           ▼
            ┌───────────────────────────────┐
            │ LLM / Agent                   │ cited answers; attested computations
            └──────────────┬────────────────┘
                           ▼
              Feedback → new/updated concepts (agent writes, human verifies)
```

---

## 11. Adoption roadmap

1. **Start small**: pick one domain (e.g. your top 20 tables and 10 metrics). Write them as OKF concepts with `type`, `title`, `description`, and a schema or definition body.
2. **Add an `index.md`** per directory so agents can browse before reading.
3. **Link concepts** (table → metric → playbook) to build the graph implicitly.
4. **Add provenance and trust**: `sources`, `generated`, then `verified` once humans review.
5. **Set lifecycle fields**: `status` and `stale_after` where facts expire.
6. **Index for retrieval**: embeddings plus metadata filters; add link expansion.
7. **Introduce a light ontology** if vocabulary drift appears (standardize `type` values and relationship wording).
8. **Project to a graph store** only when you need multi-hop queries at scale.
9. **Add Attested Computations** for the few numbers where correctness is critical.
10. **Measure**: retrieval precision, answer groundedness, citation coverage, stale-content hits, human-correction rate.

---

## 12. Limitations and caveats

- **OKF is young.** The spec is v0.2, and the full attestation runtime protocol, attester ABI/sandboxing and caching are explicitly deferred. Expect change.
- **Untyped links.** OKF doesn't encode relationship kinds; if you need typed edges or inference, you'll add that on top (ontology, graph projection, or conventions in prose/frontmatter).
- **No built-in query engine.** OKF specifies a format, not storage, serving or search. You supply indexing and retrieval.
- **Trust signals are advisory.** Trust tiers and credibility signals are inputs to judgement, not access control. `usage_count` is explicitly a coarse liveness signal, not a ranking score.
- **Agent-written knowledge needs review.** Machine-generated concepts can be wrong; the trust model only helps if humans actually verify what matters.
- **Maintenance cost remains.** Any knowledge layer rots without ownership, freshness checks and a review process.
- **Evidence for gains is workload-specific.** Benefits like fewer hallucinations or lower token use depend on corpus quality and retrieval design; measure on your own tasks rather than assuming.

---

## 13. Conclusion

- **Ontologies** give agents a shared vocabulary and a model of how things relate.
- **Knowledge graphs** make those relationships traversable, enabling multi-hop, explainable retrieval.
- **OKF** makes the resulting knowledge practical to author, review, version and exchange. It's plain markdown in git, and it treats provenance, trust, freshness, lifecycle and attestation as first-class concerns.

Together they move an AI system from "generate something plausible from similar text" toward "answer from curated, attributable, current knowledge, and prove the numbers." The most pragmatic path is incremental: begin with a small OKF bundle, add links and trust metadata, layer in a light ontology and graph retrieval where multi-hop questions demand it, and reserve attestation for the figures that must be right.

---

## Source

- Open Knowledge Format (OKF) Specification, v0.2: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
