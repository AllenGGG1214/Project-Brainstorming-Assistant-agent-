# Project Brainstorming Agent

An evidence-first agent that turns a rough student or personal project idea into a buildable, resume-ready project plan.

Unlike a generic idea generator, the agent starts by searching for comparable projects, products, repositories, and articles. It then helps the user decide whether to continue, narrow the scope, differentiate the idea, or stop. Only after that decision does it generate a lightweight design pack.

## Why this project exists

Students often jump from an idea directly into coding. They may discover too late that the project already exists, the scope is too large, or the architecture cannot be explained in an interview. This agent adds a lightweight validation and design workflow for individual builders.

## Workflow

```text
Rough idea
   |
   v
1. Idea intake and clarification
   |
   v
2. Internet landscape search
   |-- similar work found --> compare and differentiate
   `-- weak/no match ------> report search coverage and uncertainty
   |
   v
3. Human decision gate: Go / Pivot / Stop
   |
   v
4. Lightweight design pack
   |-- Project brief / lightweight SDD
   |-- Functional list with person-days and cost
   `-- Architecture diagram and rationale
   |
   v
5. Resume evidence pack and implementation roadmap
```

## Outputs

- `idea_brief.md`: problem, target users, constraints, success criteria, and differentiation.
- `landscape_scan.md`: search queries, comparable projects/articles, source links, comparison, and evidence confidence.
- `lightweight_sdd.md`: scope, user flow, data, APIs, non-functional requirements, risks, testing, and milestones.
- `functional_list.xlsx` or `.csv`: Basic/MVP, Standard, and Stretch capabilities with dependencies, person-days, cost assumptions, and totals.
- `architecture.md` plus a Mermaid/Draw.io diagram: system context, components, data flow, integrations, deployment, and trade-offs.
- `resume_pack.md`: concise resume bullets, interview talking points, measurable evidence, and an honest status label.

## Design principles

1. Evidence before generation.
2. Never claim that no similar project exists; state what was searched and the confidence of the result.
3. Preserve source links and clearly separate facts, inference, and assumptions.
4. Keep the user as the decision maker at Go/Pivot/Stop gates.
5. Estimate effort as ranges, not false precision.
6. Do not fabricate users, test results, performance metrics, GitHub activity, or adoption.
7. Prefer a small buildable MVP over an enterprise-scale specification.
8. Generate resume claims only from artifacts or results that actually exist.

## MVP scope

The first version is a single orchestrating agent with modular stages and saved Markdown/CSV artifacts. A multi-agent implementation is optional later; it is not required to demonstrate the product idea.

## Suggested implementation

- Orchestrator: Python or TypeScript state machine
- Model interface: provider-agnostic adapter
- Search: web search API plus GitHub and academic/project sources when relevant
- Storage: local project workspace with JSON state and versioned artifacts
- Diagrams: Mermaid for reproducibility; Draw.io export as an optional enhancement
- Validation: schema checks, citation checks, cost formula checks, and golden test ideas

See [AGENT_INSTRUCTION.md](AGENT_INSTRUCTION.md) for the operating contract and [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) for the design and resume framing.

## Codex skills

The repository includes one orchestrator and five independently invokable node skills under the repository-level `.agents/skills/` directory:

| Skill | Node | Output |
|---|---:|---|
| `$project-brainstorming` | All | Runs the complete gated workflow |
| `$organize-project-idea` | 1 | `01-idea-brief.md` |
| `$research-project-ideas` | 2 | `02-research-and-brainstorm.md` |
| `$plan-project-functions` | 3 | `03-functional-list.md` |
| `$prototype-project-html` | 4 | Runnable prototype and `prototype-map.md` |
| `$design-project-architecture` | 5 | `05-architecture.md` with Mermaid diagrams |

Start the full workflow in Codex with:

```text
$project-brainstorming I have an idea for ...
```

Invoke a node directly when you already have its required upstream artifacts. Codex detects repository skill changes automatically; restart Codex only if the new skills do not appear.

## Current implementation status

The Codex-native MVP includes deterministic workflow support in `.agents/skills/project-brainstorming/scripts/`:

- `workflow_state.py` initializes a project, enforces stage order and the research decision gate, records accepted artifacts, and maintains `project-state.json`.
- `validate_project.py` checks stage order, source URLs, `FL-NNN` traceability, prototype files, Mermaid architecture coverage, and organization-specific sensitive terms.
- `test_workflow.py` runs an isolated five-stage end-to-end smoke test using only the Python standard library.

No third-party packages or API key are required for this Codex-native version. Codex provides reasoning and web search; the scripts provide deterministic state and validation.
