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
| Oct 9 | **Microsoft-Decision-1** | Post-trained Qwen3.5-9B returning calibrated probabilities; available on Azure Foundry and OpenRouter; $0.042 per 1M input tokens, output free. Microsoft claims top accuracy on 36 benchmarks (~150 K questions), 2.5× faster than runner-up H2O-Lightning-4B and 35× faster than GPT-6 Sol, and average decision-flip rate of 1.3% on perturbations (0% on option-reorder or paraphrase). Plans to rebase on MAI and OpenAI models. Use cases listed include **skill-based decisions** — applying an agent skill's rules to choose the next action without reprocessing a long instruction list. Results are self-reported. |
| Oct 6 | [OpenAI Decisions API](https://aiweekly.co/alerts/openai-launches-decisions-api-public-beta-on-gpt-6-luna) | Public beta on gpt-6-luna; predicate, choice and score outputs; text and image input; $0.10 per 1M input tokens, no output charge; claims up to 10x faster than its own Responses API |
| Oct 1 | [Cloudflare Clef and Clef-flash](https://letsdatascience.com/news/cloudflare-releases-open-weight-clef-decision-models-c52886d6) | Open weight (Apache 2.0), 27B with 64K context, vision; Jev-compatible API; Clef-flash median 38.8 ms (Cloudflare's numbers) |
| Oct 1 | **AWS Strands Decider 2B** | Qwen3.5-2B with LM head replaced by a ~1 M-parameter pointer head; open weights, code, training data and scripts published; framework kit rather than a managed service — no hosted endpoint or Bedrock listing as of early October. JevBench: current 0.762, launch 0.723 vs 0.996 for GPT-6 Luna. AWS-reported median latency ~115 ms (RTX 3090), ~153 ms (M3 Mac), ~1.6 s on 8-thread Xeon CPU. Retraining ~11 h on one RTX 3090. Early users report first-option bias matching the wider order-sensitivity problem. ([comparison](https://www.beri.net/article/cloudflare-clef-amazon-strands-decider-open-weight-decision-models-vs-jev-benchmarks-pricing); [deeper look below](#aws-strands-decider-2b)) |
| Sep 29 – Oct 1 | Liquid AI, Perplexity (pplx-decider, 27B, Apache 2.0) | Further hosted and open-weight entrants ([list](https://github.com/AnotiaWang/awesome-decision-models/wiki)) |
| Sep 15 | [TypeSafe Jev](https://www.vktr.com/ai-platforms/chatgpt-cocreator-launches-typesafe-ai-with-jev/) | First "System One" model; $40M seed led by DCVC; trained with RL for calibrated decisions (RLCD); $0.042 per 1M input tokens, output free |

**How they work.** Most reuse an LLM backbone, read the input once, then score every valid option in parallel instead of generating tokens. Output is schema-valid by construction, so malformed tool calls and invented fields disappear. A valid answer can still be wrong.

### Lab landscape as of October 11, 2026

| Lab | Status | Notable detail |
| --- | --- | --- |
| **Microsoft** | Shipping (Oct 9) | Microsoft-Decision-1 on Foundry and OpenRouter; self-reports top accuracy on 36 benchmarks; Xbox labelling case: 10 K+ items, comparable quality, 14× faster and 200× cheaper than GPT-6 Sol |
| **OpenAI** | Public beta (Oct 6) | Decisions API on gpt-6-luna; a third-party test found it order-sensitive — answers changed for 30% of items across five reorderings of a 77-option task, vs 4% for Jev |
| **Google DeepMind** | No first-party model | Ecosystem footprint: OpenJev is built on DiffusionGemma (accepts up to 8 images per request); a Google codelab walks developers through Jev or DiffusionGemma as the decision model inside a parallel Google ADK workflow |
| **Nvidia** | Framework support, no model | A NeMo agents pull request adds decision-model support, including agents that run without a chat model, with a fallback to the chat LLM when none is configured |
| **Anthropic** | No product or announcement | A third-party emulation project wraps Haiku 5.5; in its tests a single Haiku call matched Jev and OpenAI on four of five datasets; Jev led on BoolQ (91.0% vs 87.2%); Haiku changed answers on 22% of reordered items vs 4% for Jev. A creative hybrid: one developer had Jev play Pokémon Red while Claude Opus 5 watched the log and adjusted the option wording as a coach |
| **Meta / Meta Superintelligence Labs** | No decision model or API found | Nearest small-model release is Muse Spark (succeeds Llama 4, next generation in development), but it is not positioned for typed decisions. Open weights could be used via Nokia AnyJev (turns any causal LLM into a decision model without training). If Meta enters, expect an open-weight model release rather than a hosted API. |
| **AWS, Cloudflare, Perplexity, Liquid AI** | Generally available | Covered above |

The JevBench leaderboard now lists over 60 community Jev-style models.

**Backbone landscape.** The documented open decision models in the published audit run on Qwen, ModernBERT and DeBERTa. Microsoft, Cloudflare and AWS have all built on Qwen. Google DeepMind's ecosystem entry uses DiffusionGemma. Llama is barely visible in the open decision-model ecosystem — the leaderboard may contain community Llama-based models, but none of the major releases use it. Nokia's AnyJev turns any open causal LLM (Hugging Face, vLLM, SGLang, llama.cpp) into a decision model without training, so any open-weight family including Llama or Muse could be used that way without a dedicated model release.

### AWS Strands Decider 2B — deeper look {#aws-strands-decider-2b}

Released October 1 by Strands Labs, the experimental arm of AWS's open-source Strands Agents project. The release is closer to a recipe than a service: weights, code, training data and scripts are all public, and retraining takes about 11 hours on one RTX 3090.

**Architecture.** Starts from Qwen3.5-2B, drops the text-generating head, and adds a pointer head of just over a million parameters that scores the supplied options. Supports the same three question types as Jev: yes/no, choice and score.

**Agent integration pattern.** Plugs into Strands through an intervention system that can let an action proceed, deny it, ask for confirmation, or request feedback. Generative calls still go through Amazon Bedrock. The repo's example gates a weather-tool call on two yes/no decisions — the agent asks which city rather than guessing — which is exactly the typed-gate-before-action pattern. Co-author Marc Brooker has said he's most interested in hybrid workflows that fill the gap between deterministic ones (like Step Functions) and fully agentic ones.

**Performance.** AWS-reported median latency: ~115 ms on an RTX 3090, ~153 ms on an M3 MacBook for small tasks, ~1.6 s per question on an 8-thread Xeon CPU, and 16–18 s at ~3,000 tokens on plain CPU. JevBench scores: current model 0.762, launch model 0.723, versus 0.996 for GPT-6 Luna. AWS says both versions average the same accuracy across six training runs each, and claims rank 2 among public ~2B models and rank 1 among those with a full public training recipe; a third-party source puts it third in its class — treat the exact rank loosely.

**Limits (AWS's own statement and early-user reports).** Significantly worse than reasoning models on complex problems; unsuited to coding, chatbots or summarisation. Confidence bands were set on short classification tasks only. Early users report sensitivity to option order and a bias toward the first option, consistent with the wider order-sensitivity problem.

**Bedrock status.** No hosted endpoint and no Bedrock listing as of early October 2026. The local server has no authentication. AWS says it is working on decision-model integration libraries. A community builder has deployed it unofficially on Bedrock AgentCore Runtime (2 vCPU, 8 GB microVM).

**Comparison framing.** Microsoft and OpenAI ship hosted APIs with pricing and SLAs. AWS ships a framework-level kit you host, tune and threshold yourself. For your skills framework, Strands Decider is a cheap way to experiment with gating and routing on your own labels, but you need to add hosting, authentication, option-order testing and threshold calibration yourself before putting it on a routing path.

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
| Accuracy | Strong on easy, few-option tasks; four evaluators measured Jev on Banking77 at 76.3% to 87.0% ([Creative AI News](https://www.creativeainews.com/articles/open-jev-clones-benchmark-disagreement-2026/)); an off-the-shelf Qwen3.5-4B matches community Jev-style models on the same backbone |
| Mechanism | A review of 28 early papers found the typed readout shows no independent accuracy edge over label-probability baselines; gains are latency and cost ([arXiv](https://arxiv.org/pdf/2609.32160)) |
| Calibration | Mixed: well calibrated when pooled (ECE 0.047) but off within individual benchmarks (median 0.168), a base-rate mismatch ([arXiv](https://arxiv.org/pdf/2609.29429)); another benchmark measured ECE 0.246, worst in its field |
| Confidence as a filter | Useful: keeping the most confident half of decisions raised median accuracy from 0.793 to 0.933 in the same study |
| **Robustness** | Swapping yes/no option names across rubrics cut a decision model's AUC from .815 to .581 in one study; score-guided prompt injection roughly doubled attack success from 1.8% to 3.5% |
| **Order-sensitivity** | OpenAI's API flipped answers on 30% of items across option reorderings (third-party, 77-option task); Anthropic Haiku 5.5 emulation flipped 22%; Jev and Microsoft-Decision-1 report ≤4% and ≤1.3% respectively (vendor numbers) |
| **Correlated errors / escalation** | LLM judges repeated Jev's wrong answer in 96% of verdicts on its most confident errors in one rubric-judging study — escalation only helps if errors are uncorrelated |

The practical lessons that hold across sources: (1) Confidence *ranks* decisions well even when absolute values drift — use it as a filter, not a threshold; (2) test order and wording invariance on your own routing examples before relying on robustness claims from vendor benchmarks; (3) when you escalate, the judge must be genuinely independent or you compound rather than catch errors. So the dominant pattern is still a **cascade** — act on confident decisions, escalate the rest to an LLM judge or a person — but pick the judge carefully and set the cut-off on your own labels rather than the default 0.5. A second pattern follows: define a typed check once and use it both as an offline eval and as a runtime gate.

## What this means for an agent skills framework

Every skill framework already contains decision points: routing (which skill fires), depth (how much of a skill to load), branching inside a skill, control (proceed, ask, retry, escalate) and composition (which skills, in what order). The trends above suggest making each one explicit.

&#91;embedded content: decision flow for a skills framework · gate, policy, escalation, feedback\]

A cheap typed gate picks the skill; hard policy lives in a shared service, not in SKILL.md prose; anything uncertain or policy-flagged goes to an LLM or a person, and logged outcomes tune the threshold.

Microsoft's skill-based decisions use case — applying an agent skill's rules to choose the next action without reprocessing a long instruction list — maps directly onto this pattern. The implication is concrete: turn each skill's decision table into typed questions, let a cheap decision model pick the branch, and reserve the LLM for ambiguous cases that need contextual reasoning. Before shipping, test order and wording invariance on your own routing examples; none of the published benchmarks cover skill routing specifically, and Microsoft-Decision-1 has no independent evaluation yet (as of October 11, 2026).

1. **Treat routing as classification.** Write skill descriptions with explicit triggers and exclusions ("use for X, not Y"). Overlapping descriptions are the usual cause of misfires. Note that routing research found metadata alone loses 31 to 44 points of accuracy versus using the full skill text ([SkillRouter](https://arxiv.org/abs/2603.22455)), so a router may need more than names and descriptions.
2. **Put a typed gate in front of skills.** A decision model or small classifier answers "does any skill apply, which one, how confident." Fit the threshold on 50 to a few hundred labelled requests.
3. **Split crisp rules from judgment.** Thresholds, format choices, eligibility and approvals go in decision tables, scripts or a shared decision service. Leave only fuzzy interpretation to the model.
4. **Make escalation explicit.** Ask or escalate when an action is irreversible or the ambiguity changes the outcome; otherwise proceed and state the assumption. Choose an escalation judge that is genuinely independent — correlated errors mean a judge that mirrors the model's reasoning will repeat its mistakes 96% of the time on the hardest cases.
5. **Use progressive disclosure as a cost decision.** Rules like "read the edge-cases reference only if the input has nested records" make value-of-information choices visible.
6. **Close the loop.** Log the chosen skill, confidence, policy version and outcome. A confusion matrix of mistaken skills tells you which descriptions to sharpen or merge.
7. **Reuse checks as gates.** A typed question that tests a skill offline can guard it in production.
8. **Test robustness before trusting.** Measure how often the chosen skill changes when you reorder options, paraphrase the question, or rename yes/no labels. A result that flips >5% of the time on benign perturbations is not ready for production routing.

## Limits, risks and open questions

- **Valid is not correct.** Typed models cannot emit an invalid option but can pick the wrong valid one. Known weak spots include counting, arithmetic, date comparison, long noisy inputs and adversarial content.
- **Closed option sets only.** These models work only when the decision space is already defined; open-ended planning stays with LLMs.
- **Little explanation.** A probability is not a rationale. Regulated decisions still need reason codes, which explicit rules provide and typed models do not.
- **Specialists can win.** Small classifiers trained on a few hundred of your own labels often beat zero-shot decision models. An off-the-shelf Qwen3.5-4B already matches community Jev-style models on the same backbone, which is probably why price points are converging and why Microsoft leads with robustness rather than accuracy.
- **Security exposure.** A decision model used for moderation or prompt-injection screening reads untrusted input; score-guided prompt injection roughly doubled attack success from 1.8% to 3.5% in one study. Uncertain cases should go to stronger review.
- **Order and wording sensitivity.** Swapping option names or reordering items can flip decisions dramatically (AUC from .815 to .581 in one adversarial rubric study; 30% flip rate on a third-party OpenAI API test). Treat published robustness claims as vendor self-reports until independently replicated.
- **Correlated escalation errors.** LLM judges repeated Jev's wrong answer on 96% of its most confident errors in one study. Escalation to an LLM only helps if the judge reasons independently. Design for divergent escalation paths.
- **Thin, mostly vendor evidence.** Most numbers are self-reported or from days-old preprints. Microsoft-Decision-1 has no independent evaluation as of October 11, 2026. Even independent evaluations disagree by more than 10 points on the same benchmark.
- **Absorption risk.** Frontier labs can ship decision endpoints as a cheap tier, as OpenAI and now Microsoft have. Whether independent vendors keep an edge is open. The interface is easy to copy.
- **Governance cost.** Decision catalogs, owners, versions and audit trails take real effort; over-specifying rules makes agents brittle. Encode the decisions that matter and leave the rest to judgment.

## Outlook and signals to watch

My projection, not established fact: over the next 12 to 24 months the two traditions merge. Explicit models (DMN-style requirement graphs) supply structure, authority and audit; learned decision models fill individual judgment nodes; LLMs frame problems and handle the long tail. The competitive edge shifts from raw accuracy to trustworthy calibration on a customer's own data. With Microsoft now in the market and the interface easy to copy, **robustness and calibration on customer data** are becoming the primary differentiators — accuracy on shared benchmarks is already converging.

Signals that would confirm or break this view:

- Independent (non-vendor) evaluation of Microsoft-Decision-1 on standard and skill-routing benchmarks
- Peer-reviewed, non-vendor benchmarks with per-domain calibration and robustness (order/wording invariance) results
- OpenAI's Decisions API pricing and terms at general availability
- Uptake of customer fine-tuning on own decisions (Cloudflare's offering is the first test)
- Whether Google DeepMind ships a first-party decision model or deepens the DiffusionGemma/ADK ecosystem play
- Nvidia NeMo decision-model support reaching a stable release
- Anthropic product announcement or continued silence — the emulation-only gap is a meaningful signal either way
- Meta: whether Muse Spark or a Llama variant ships with calibrated option-probability readout, or whether Meta remains absent from this tier
- AWS Strands Decider gaining a hosted Bedrock endpoint, or remaining a framework-only kit
- Nokia AnyJev adoption as a proxy for how many teams want to convert existing open-weight models rather than adopt dedicated ones
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
- Microsoft-Decision-1 launch post, October 9, 2026 (self-reported; post edited after publication to add Jev accuracy and calibration comparisons)
- Third-party OpenAI Decisions API order-sensitivity test (77-option task, five reorderings; 30% answer-change rate vs 4% for Jev)
- Google ADK codelab: using Jev or DiffusionGemma as the decision model inside a parallel ADK workflow
- Nvidia NeMo agents pull request: decision-model support with LLM fallback
- Third-party Anthropic emulation project (Haiku 5.5): four of five datasets matched Jev and OpenAI; Jev led BoolQ 91.0% vs 87.2%; 22% answer-change rate on reorderings
- AWS Strands Decider 2B repo (Strands Labs, October 1, 2026): architecture, training recipe, latency and JevBench figures; limits stated by AWS
- Third-party Strands Decider review (vendor in adjacent space, traces back to AWS repo): rank claims, order-sensitivity and first-option bias
- Community deployment of Strands Decider on Bedrock AgentCore Runtime (unofficial)
- Meta Superintelligence Labs: Muse Spark announcement (no decision-model positioning found)
- Nokia AnyJev: converts any open causal LLM to a decision model without training; backends for Hugging Face, vLLM, SGLang, llama.cpp
- Open decision model backbone audit: documented open models use Qwen, ModernBERT and DeBERTa; Llama absent from major releases
