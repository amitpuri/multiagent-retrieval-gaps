# Decision Models: Trends, Evidence and Outlook


## Executive summary

Decision models are becoming the control layer of agent systems: the fast, cheap, auditable part that routes, gates, scores and escalates, while LLMs handle open-ended reasoning and language.

The phrase now covers two traditions that are converging:

- **Explicit decision models** (DMN tables, rules, scoring, optimization). Their 2026 story is governance. Gartner named decision governance a top data and analytics trend in June 2026, and vendors such as IBM now expose governed decision services to agents through MCP.
- **Learned "typed" decision models**, a new model category since September 2026. TypeSafe's Jev, OpenAI's Decisions API, Cloudflare's Clef, AWS's Strands Decider and Perplexity's decider return a choice, score or probability over options you define, instead of text.

The evidence is uneven. Speed and cost gains are real but smaller than launch headlines; accuracy is mid-tier on hard calls; calibration is the most contested claim. The practical pattern is a cascade: a typed decision model or rule acts when confident, and hands uncertain or consequential cases to an LLM or a person.

For an agent skills framework, three moves follow: treat skill routing as a typed classification decision, keep hard policy in versioned decision services rather than in SKILL.md prose, and set escalation thresholds on your own labelled data.

## What a decision model is

A decision model maps a situation to an action. Most share five parts: inputs (current state), options, criteria, a decision rule, and ideally a feedback loop. They differ mainly in how the rule is expressed.

| Family | How it decides | Strength | Weakness |
| --- | --- | --- | --- |
| Rule-based (rules, decision tables, DMN) | Explicit conditions | Deterministic, auditable | Brittle outside the rules |
| Scoring / optimization | Ranks options against weighted criteria and constraints | Handles trade-offs | Needs explicit objectives |
| Probabilistic / sequential (Bayesian, MDPs, bandits) | Updates beliefs, balances explore vs exploit | Handles uncertainty over time | Harder to build and explain |
| Learned / LLM-based | A classifier, policy or language model judges from context | Handles messy input | Less predictable, needs calibration |

In an agent, the roles separate cleanly: the **LLM** interprets intent and context, the **decision model** evaluates criteria and picks an outcome, the **skill** carries the procedure, and the **tool** executes. Separating decision from execution is what makes the system testable and auditable.

## Trend 1: Typed decision models became a product category

In under four weeks, "decision model" went from a modelling discipline to a model class you call over an API. You send state plus typed questions (choice, score, yes/no); the model returns probabilities over your options, never free text.

| Date (2026) | Release | What it is |
| --- | --- | --- |
| Oct 6 | [OpenAI Decisions API](https://aiweekly.co/alerts/openai-launches-decisions-api-public-beta-on-gpt-6-luna) | Public beta on gpt-6-luna; predicate, choice and score outputs; text and image input; $0.10 per 1M input tokens, no output charge; claims up to 10x faster than its own Responses API |
| Oct 1 | [Cloudflare Clef and Clef-flash](https://letsdatascience.com/news/cloudflare-releases-open-weight-clef-decision-models-c52886d6) | Open weight (Apache 2.0), 27B with 64K context, vision; Jev-compatible API; Clef-flash median 38.8 ms (Cloudflare's numbers) |
| Oct 1 | AWS Strands Decider 2B | Qwen3.5-2B with the LM head replaced by an option-scoring pointer head; runs on a consumer GPU; weaker on hard tasks ([comparison](https://www.beri.net/article/cloudflare-clef-amazon-strands-decider-open-weight-decision-models-vs-jev-benchmarks-pricing)) |
| Sep 29 – Oct 1 | Liquid AI, Perplexity (pplx-decider, 27B, Apache 2.0) | Further hosted and open-weight entrants ([list](https://github.com/AnotiaWang/awesome-decision-models/wiki)) |
| Sep 15 | [TypeSafe Jev](https://www.vktr.com/ai-platforms/chatgpt-cocreator-launches-typesafe-ai-with-jev/) | First "System One" model; $40M seed led by DCVC; trained with RL for calibrated decisions (RLCD); $0.042 per 1M input tokens, output free |

**How they work.** Most reuse an LLM backbone, read the input once, then score every valid option in parallel instead of generating tokens. Output is schema-valid by construction, so malformed tool calls and invented fields disappear. A valid answer can still be wrong.

**Why it matters.** The bet is volume: when one AI judgment costs fractions of a cent and tens of milliseconds, software can afford to ask far more of them. TypeSafe's demo ran a Doom bot at about ten decisions a second for roughly $7 an hour.

**Adoption signals.** Vercel reported Jev was the fastest-adopted model in its AI Gateway's history in its first 24 hours ([The New Stack](https://thenewstack.io/typesafe-jev-system-one/)). LangChain shipped a classifier integration and middleware that screens tool calls before they run ([InfoQ](https://infoq.com/news/2026/10/typesafe-ai-jev-released)).

## Trend 2: Classic decision modelling repositions as governance for agents

The rules-and-DMN world is reframing itself as the accountability layer around AI agents. As agents take real actions, the question shifts from "was the response good?" to "who authorised this decision, under which policy version?"

- **Analyst signal.** At its June 16, 2026 Sydney summit, [Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-06-16-gartner-identifies-the-top-trends-for-data-and-analytics) listed "reducing AI agent risk with decision governance" as trend 2 of its 2026 data and analytics trends: applying governance to decision intelligence so automated decisions are explainable and auditable. Gartner also predicts explicitly modelled decisions will be five times more trusted and 80% faster than ungoverned ones by 2029 ([summary](https://letsdatascience.com/news/gartner-identifies-top-data-and-analytics-trends-a1d2914a)). That is a forecast, not a measured result.
- **Division of labour.** The common position: ML and LLMs supply scores, extractions and predictions as inputs; an explicit model (rules, DMN tables) makes the binding decision. Some vendors go further and say the LLM should never decide. Treat that as a vendor stance, but it names the live tension.
- **The standard itself is moving slowly.** OMG's site still lists [DMN 1.6 as beta](https://omg.org/spec/DMN) (September 2024), with a 1.7 beta in progress. One of the pasted drafts said 1.6 became formal in September 2026; I could not confirm that. The related Shared Data Model and Notation (SDMN 1.0) did reach formal status in June 2026 ([OMG](https://www.omg.org/spec/company/trisotech/About-trisotech/)).
- **LLMs as authors.** Vendors now pitch LLMs that draft candidate decision tables and test cases from policy text. The sound framing: AI can draft a candidate model; only review, testing and approval make it authoritative.

## Trend 3: Decisions and skills become distributable services over MCP

Both decision logic and skill instructions are moving out of individual agents and into shared, versioned services that many agents call.

- **Decision services as tools.** IBM's open-source [Decision Intelligence MCP server](https://github.com/DecisionsDev/ibm-decision-intelligence-mcp-server) exposes each operation of a deployed decision service as an MCP tool, so assistants such as watsonx Orchestrate, Claude or Cursor can discover and run governed decisions ([IBM docs](https://www.ibm.com/docs/en/SSZGQX/com.ibm.ads.execute/topics/con_integrate_ai_app.html)). One refund or eligibility model can then serve every agent that needs it.
- **Skills as remote assets.** Microsoft Agent Framework added experimental support (July 28, 2026) for agents to [discover and load Agent Skills from an MCP server](https://devblogs.microsoft.com/agent-framework/discover-agent-skills-from-mcp-servers-in-net/), keeping progressive disclosure and adding controls on script execution. Its framing: one expense policy everyone uses, not a copy per team. (A pasted draft dated this to September.)
- **Why it matters.** Skills and decision services can be versioned, owned and released independently. Change a policy without touching prompts; change a prompt without silently changing approval rules.

## Trend 4: Hybrid architectures — the LLM frames, a specialist decides

The dominant design pattern is no longer "let the LLM decide everything." It splits work by what each component does best.

- **Structured macro-flow.** Agent loops are increasingly explicit graphs or state machines (LangGraph-style), with the LLM making targeted choices inside nodes and schema-validated outputs between them.
- **LLM as interpreter, specialist as engine.** The LLM extracts facts and frames the problem; a rule engine, optimiser, forecaster or typed decision model computes the answer. Reported work on optimisation found LLMs writing a correct optimisation model only about a quarter to two-fifths of the time, which is why solvers stay in the loop.
- **Evidence then decision.** An independent benchmark found the best setup was hybrid: use a decision model to extract structured evidence cheaply, then let a small trained classifier or application logic make the final call ([MindStudio](https://www.mindstudio.ai/blog/jev-vs-classic-classifiers-benchmark/)).
- **Distillation path.** Start a workflow on a frontier LLM, log the traces, then distil the repetitive judgments into a small decision model, rules or a statistical model. Cloudflare already offers RL fine-tuning of Clef on a customer's own labelled decisions ([InfoQ summary](https://letsdatascience.com/news/cloudflare-releases-open-weight-clef-decision-models-c52886d6)).

## Trend 5: Calibration, abstention and cascades become the real battleground

The value of a decision model lies in knowing when *not* to act, so calibration is the claim that matters most and the one that holds up least consistently.

| Claim | What independent work found |
| --- | --- |
| Speed and cost | Real but smaller than headlines: an analysis of 12,759 launch posts put user-reported median speedup at 7x and cost saving at 30x, against a 193.6x headline ([InfoQ](https://infoq.com/news/2026/10/typesafe-ai-jev-released)) |
| Accuracy | Strong on easy, few-option tasks; four evaluators measured Jev on Banking77 at 76.3% to 87.0% ([Creative AI News](https://www.creativeainews.com/articles/open-jev-clones-benchmark-disagreement-2026/)); trained small classifiers often win |
| Mechanism | A review of 28 early papers found the typed readout shows no independent accuracy edge over label-probability baselines; gains are latency and cost ([arXiv](https://arxiv.org/pdf/2609.32160)) |
| Calibration | Mixed: well calibrated when pooled (ECE 0.047) but off within individual benchmarks (median 0.168), a base-rate mismatch ([arXiv](https://arxiv.org/pdf/2609.29429)); another benchmark measured ECE 0.246, worst in its field |
| Confidence as a filter | Useful: keeping the most confident half of decisions raised median accuracy from 0.793 to 0.933 in the same study |

The last row is the practical lesson. Confidence ranks decisions well even when its absolute values drift, so the dominant pattern is a **cascade**: act on confident decisions, escalate the rest to an LLM judge or a person, and set the cut-off on your own labels rather than the default 0.5. A second pattern follows: define a typed check once and use it both as an offline eval and as a runtime gate.

## What this means for an agent skills framework

Every skill framework already contains decision points: routing (which skill fires), depth (how much of a skill to load), branching inside a skill, control (proceed, ask, retry, escalate) and composition (which skills, in what order). The trends above suggest making each one explicit.

&#91;embedded content: decision flow for a skills framework · gate, policy, escalation, feedback\]

A cheap typed gate picks the skill; hard policy lives in a shared service, not in SKILL.md prose; anything uncertain or policy-flagged goes to an LLM or a person, and logged outcomes tune the threshold.

1. **Treat routing as classification.** Write skill descriptions with explicit triggers and exclusions ("use for X, not Y"). Overlapping descriptions are the usual cause of misfires. Note that routing research found metadata alone loses 31 to 44 points of accuracy versus using the full skill text ([SkillRouter](https://arxiv.org/abs/2603.22455)), so a router may need more than names and descriptions.
2. **Put a typed gate in front of skills.** A decision model or small classifier answers "does any skill apply, which one, how confident." Fit the threshold on 50 to a few hundred labelled requests.
3. **Split crisp rules from judgment.** Thresholds, format choices, eligibility and approvals go in decision tables, scripts or a shared decision service. Leave only fuzzy interpretation to the model.
4. **Make escalation explicit.** Ask or escalate when an action is irreversible or the ambiguity changes the outcome; otherwise proceed and state the assumption.
5. **Use progressive disclosure as a cost decision.** Rules like "read the edge-cases reference only if the input has nested records" make value-of-information choices visible.
6. **Close the loop.** Log the chosen skill, confidence, policy version and outcome. A confusion matrix of mistaken skills tells you which descriptions to sharpen or merge.
7. **Reuse checks as gates.** A typed question that tests a skill offline can guard it in production.

## Limits, risks and open questions

- **Valid is not correct.** Typed models cannot emit an invalid option but can pick the wrong valid one. Known weak spots include counting, arithmetic, date comparison, long noisy inputs and adversarial content.
- **Closed option sets only.** These models work only when the decision space is already defined; open-ended planning stays with LLMs.
- **Little explanation.** A probability is not a rationale. Regulated decisions still need reason codes, which explicit rules provide and typed models do not.
- **Specialists can win.** Small classifiers trained on a few hundred of your own labels often beat zero-shot decision models.
- **Security exposure.** A decision model used for moderation or prompt-injection screening reads untrusted input; uncertain cases should go to stronger review.
- **Thin, mostly vendor evidence.** Most numbers are self-reported or from days-old preprints. Even independent evaluations disagree by more than 10 points on the same benchmark.
- **Absorption risk.** Frontier labs can ship decision endpoints as a cheap tier, as OpenAI just did. Whether independent vendors keep an edge is open.
- **Governance cost.** Decision catalogs, owners, versions and audit trails take real effort; over-specifying rules makes agents brittle. Encode the decisions that matter and leave the rest to judgment.

## Outlook and signals to watch

My projection, not established fact: over the next 12 to 24 months the two traditions merge. Explicit models (DMN-style requirement graphs) supply structure, authority and audit; learned decision models fill individual judgment nodes; LLMs frame problems and handle the long tail. The competitive edge shifts from raw accuracy to trustworthy calibration on a customer's own data.

Signals that would confirm or break this view:

- Peer-reviewed, non-vendor benchmarks with per-domain calibration results
- OpenAI's Decisions API pricing and terms at general availability
- Uptake of customer fine-tuning on own decisions (Cloudflare's offering is the first test)
- DMN 1.6 reaching formal status, or DMN tooling adding learned-judgment nodes
- MCP skill distribution moving from experimental to stable in major frameworks
- Whether frontier labs fold decision endpoints into their standard model tiers

## Sources

- [Gartner: Top trends for data and analytics, June 2026](https://www.gartner.com/en/newsroom/press-releases/2026-06-16-gartner-identifies-the-top-trends-for-data-and-analytics)
- [VKTR: TypeSafe launches Jev](https://www.vktr.com/ai-platforms/chatgpt-cocreator-launches-typesafe-ai-with-jev/)
- [InfoQ: TypeSafe AI releases Jev](https://infoq.com/news/2026/10/typesafe-ai-jev-released)
- [The New Stack: Why TypeSafe launched Jev](https://thenewstack.io/typesafe-jev-system-one/)
- [AI Weekly: OpenAI Decisions API public beta](https://aiweekly.co/alerts/openai-launches-decisions-api-public-beta-on-gpt-6-luna)
- [Dealroom: OpenAI Decisions API vs Jev](https://app.dealroom.co/news/note/openai-opens-decisions-api-to-all-developers-adding-image-input-in-challenge-to-typesafe-s-jev)
- [The Register: Cloudflare Clef](https://www.theregister.com/a/5300649)
- [Let's Data Science: Clef decision models](https://letsdatascience.com/news/cloudflare-releases-open-weight-clef-decision-models-c52886d6)
- [BERI: Clef and Strands Decider vs Jev](https://www.beri.net/article/cloudflare-clef-amazon-strands-decider-open-weight-decision-models-vs-jev-benchmarks-pricing)
- [Awesome decision models list](https://github.com/AnotiaWang/awesome-decision-models/wiki)
- [arXiv: Just Ask Jev (calibration study)](https://arxiv.org/pdf/2609.29429)
- [arXiv: Typed decision models evidence audit](https://arxiv.org/pdf/2609.32160)
- [Creative AI News: benchmark disagreement](https://www.creativeainews.com/articles/open-jev-clones-benchmark-disagreement-2026/)
- [MindStudio: Jev vs classic classifiers](https://www.mindstudio.ai/blog/jev-vs-classic-classifiers-benchmark/)
- [OMG: DMN specification](https://omg.org/spec/DMN)
- [IBM Decision Intelligence MCP server](https://github.com/DecisionsDev/ibm-decision-intelligence-mcp-server)
- [Microsoft: Agent Skills from MCP servers](https://devblogs.microsoft.com/agent-framework/discover-agent-skills-from-mcp-servers-in-net/)
- [arXiv: SkillRouter](https://arxiv.org/abs/2603.22455)
