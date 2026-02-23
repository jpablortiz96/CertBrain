<div align="center">

# 🧬 CertBrain

### Neuro-Adaptive Microsoft Certification Coach

**A multi-agent AI system that applies cognitive science to personalize Microsoft certification exam preparation**

Built with Microsoft Foundry · Azure AI · Microsoft Learn MCP · Learn Catalog API

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Microsoft Foundry](https://img.shields.io/badge/Microsoft-Foundry-purple.svg)](https://ai.azure.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[🎬 Demo Video](#demo-video) · [🏗️ Architecture](#architecture) · [🚀 Quick Start](#quick-start) · [📖 Documentation](#documentation)

</div>

---

## 🎯 What is CertBrain?

CertBrain is a **multi-agent AI system** that transforms Microsoft certification exam preparation from a passive, one-size-fits-all experience into an **adaptive, scientifically-grounded learning journey**.

Unlike traditional study tools that just quiz you, CertBrain:

- **Diagnoses** your knowledge state using Computerized Adaptive Testing (CAT/IRT)
- **Maps** your cognitive landscape as a dynamic Knowledge Graph
- **Optimizes** your study plan using SM-2 spaced repetition algorithms
- **Teaches** through Socratic dialogue scaled to Bloom's Taxonomy levels
- **Verifies** every piece of content against official Microsoft documentation
- **Adapts** continuously based on your evolving performance

### 🧪 The Science Behind CertBrain

| Cognitive Principle | How CertBrain Uses It |
|---|---|
| **Item Response Theory (IRT)** | Adaptive diagnostic that estimates ability (θ) by adjusting question difficulty based on response patterns |
| **Vygotsky's Zone of Proximal Development** | Identifies your "learning frontier" — concepts you're *almost* ready to master — and prioritizes them |
| **Bloom's Taxonomy** | The Socratic Tutor scales questions from Remember → Understand → Apply → Analyze → Evaluate → Create based on mastery |
| **SM-2 Spaced Repetition** | Study plan calculates optimal review intervals using the SuperMemo 2 algorithm to maximize long-term retention |
| **Knowledge Graphs** | Dynamic concept maps with dependency tracking enable targeted, prerequisite-aware learning paths |

---

## 🎬 Demo Video

> **[▶️ Watch the full demo on YouTube](https://youtu.be/tlnmA0QKU08)**

---

## 🏗️ Architecture

### System Overview

CertBrain orchestrates **6 specialized AI agents** through a state-machine workflow with 5 explicit reasoning patterns:

```
┌──────────────────────────────────────────────────────────────┐
│                      🔧 ORCHESTRATOR                          │
│               (State Machine + Workflow Engine)                │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│   👤 Student selects certification (e.g., AZ-900)             │
│          │                                                    │
│          ▼                                                    │
│   ┌──────────────┐          ┌─────────────────┐              │
│   │ 🔍 DIAGNOSTIC │─────────▶│ 🧠 KNOWLEDGE    │              │
│   │    AGENT      │          │   ARCHITECT     │              │
│   │  (CAT / IRT)  │          │ (Build Graph)   │              │
│   └──────────────┘          └────────┬────────┘              │
│                                      │                        │
│                     ┌────────────────┘                        │
│                     ▼                                         │
│          ┌──────────────────┐                                 │
│          │ 🔎 CRITIC AGENT   │  ◀── Verifies ALL outputs      │
│          │ (Self-Reflection) │      against MS Learn MCP       │
│          └────────┬─────────┘                                 │
│                   │                                            │
│          ┌────────▼─────────┐     ┌──────────────┐           │
│          │ 📋 CURRICULUM     │────▶│ 📧 ENGAGEMENT │           │
│          │   OPTIMIZER       │     │    AGENT     │           │
│          │ (SM-2 Algorithm)  │     │ (Reminders)  │           │
│          └────────┬─────────┘     └──────────────┘           │
│                   │                                            │
│          🖐️ HUMAN-IN-THE-LOOP: Confirm study plan             │
│                   │                                            │
│          ┌────────▼─────────┐                                 │
│          │ 🎓 SOCRATIC       │   Interactive teaching          │
│          │    TUTOR          │   (Bloom's Taxonomy)           │
│          └────────┬─────────┘                                 │
│                   │                                            │
│          🖐️ HUMAN-IN-THE-LOOP: Ready for assessment?          │
│                   │                                            │
│          ┌────────▼─────────┐                                 │
│          │ 🔍 ASSESSMENT     │   Adaptive final test           │
│          └────────┬─────────┘                                 │
│                   │                                            │
│            Score ≥ 80%?                                        │
│           ╱           ╲                                        │
│     ✅ PASS        ❌ FAIL ──▶ Loop back to Curriculum         │
│     Recommend       (max 3 iterations)                         │
│     exam date                                                  │
│                                                               │
├──────────────────────────────────────────────────────────────┤
│   📡 INTEGRATIONS                                              │
│   ├── Microsoft Learn MCP Server (doc verification)            │
│   ├── Microsoft Learn Catalog API (certs, paths, modules)      │
│   ├── Azure AI Foundry / GPT-4o (reasoning engine)             │
│   └── SMTP Email (engagement reminders)                        │
└──────────────────────────────────────────────────────────────┘
```

### 🧩 Reasoning Patterns Implemented

| Pattern | Implementation | Purpose |
|---------|---------------|---------|
| **Planner–Executor** | Curriculum Optimizer plans → Socratic Tutor executes | Separates strategic planning from tactical execution |
| **Critic / Verifier** | Critic Agent reviews every agent output, retries up to 2x on failure | Prevents hallucinations, ensures accuracy |
| **Self-Reflection** | Critic uses devil's advocate re-analysis when confidence < 0.7 | Catches subtle errors through adversarial self-review |
| **Human-in-the-Loop** | 2 checkpoints: post-plan confirmation + pre-assessment readiness | Keeps student in control of their learning journey |
| **Conditional Loop** | Assessment < 80% → revised curriculum (max 3 iterations) | Ensures mastery before recommending certification exam |

---

### 🤖 Agent Details

#### 🔍 Diagnostic Agent (CAT/IRT)

- Generates exam-style questions via GPT-4o based on real exam objectives
- Implements simplified Item Response Theory with ability estimation (θ)
- Adapts difficulty dynamically: θ += 0.5 on hard correct, θ -= 0.3 on easy incorrect
- Converges in 10-20 questions when θ delta < 0.1
- Post-processes answers with random shuffle to prevent position bias

#### 🧠 Knowledge Architect Agent

- Decomposes exam objectives into 15-25 granular sub-concepts
- Builds NetworkX directed graph with prerequisite dependencies
- Assigns mastery levels from diagnostic results
- Identifies Vygotsky's ZPD: concepts with mastery between 0.3-0.7
- Validates concepts against Microsoft Learn MCP documentation

#### 📋 Curriculum Optimizer Agent (SM-2)

- Implements SuperMemo 2 spaced repetition algorithm
- Maps concepts to real Microsoft Learn modules via Catalog API
- Generates weekly milestones with time allocations
- Calculates optimal review intervals: `interval = prev_interval × easiness_factor`
- Includes real Microsoft Learn URLs and module titles

#### 🎓 Socratic Tutor Agent (Bloom's Taxonomy)

- Never gives direct answers — uses Socratic questioning method
- Scales cognitive demand based on mastery level:
  - `< 0.3` → Remember/Understand (define, describe, explain)
  - `0.3-0.5` → Apply (demonstrate, implement, use)
  - `0.5-0.7` → Analyze (compare, differentiate, examine)
  - `0.7-0.9` → Evaluate (justify, critique, recommend)
  - `> 0.9` → Create (design, propose, architect)
- Enriches responses with official Microsoft Learn documentation

#### 🔎 Critic / Verifier Agent

- Cross-references all agent outputs against Microsoft Learn MCP Server
- Confidence scoring (0-1) for each verification
- Self-reflection loop: if confidence < 0.7, re-analyzes with contrarian prompt
- Returns structured feedback with issues, corrections, and source URLs

#### 📧 Engagement Agent

- Generates personalized reminder messages via GPT-4o
- Adapts tone: motivational / empathetic / urgent / celebratory
- Schedules reminders aligned with study plan milestones
- Sends via SMTP or logs (configurable)

---

## 🔌 Integrations

### Microsoft Learn MCP Server

- **Endpoint**: `https://learn.microsoft.com/api/mcp`
- **Protocol**: Streamable HTTP (JSON-RPC 2.0)
- **Usage**: Real-time documentation search and verification
- **No authentication required**

### Microsoft Learn Catalog API

- **Endpoint**: `https://learn.microsoft.com/api/catalog/`
- **Usage**: Fetches certifications, exams, learning paths, and modules with real URLs and metadata
- **No authentication required**

### Azure AI Foundry (GPT-4o)

- **Auth**: DefaultAzureCredential (Entra ID via `az login`)
- **Usage**: Powers all 6 agents' reasoning capabilities
- **Retry logic**: Exponential backoff (3 attempts) for rate limit handling

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Azure subscription with AI Foundry project and GPT-4o deployed
- Azure CLI (`az login` completed)

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR-USERNAME/agentsleague.git
cd agentsleague/certbrain

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Azure AI Foundry project endpoint
```

### Configuration

Edit `.env` with your Azure credentials:

```env
PROJECT_ENDPOINT=https://your-resource.services.ai.azure.com/api/projects/your-project
MODEL_DEPLOYMENT_NAME=gpt-4o
```

**Find your Project Endpoint:**

1. Go to [ai.azure.com](https://ai.azure.com)
2. Open your project → Overview
3. Under **Libraries > Foundry**, copy the endpoint URL

### Run

```bash
# Launch the Streamlit dashboard
streamlit run ui/app.py --server.port 8501

# Or run the CLI pipeline
python main.py
```

---

## 📁 Project Structure

```
certbrain/
├── main.py                        # CLI entry point
├── config.py                      # Centralized configuration & logging
├── requirements.txt               # Python dependencies
│
├── agents/                        # 6 specialized AI agents
│   ├── diagnostic_agent.py        # CAT/IRT adaptive pre-test
│   ├── knowledge_architect.py     # Knowledge Graph builder
│   ├── curriculum_optimizer.py    # SM-2 spaced repetition planner
│   ├── socratic_tutor.py          # Bloom's Taxonomy tutor
│   ├── critic_agent.py            # Output verifier + self-reflection
│   └── engagement_agent.py        # Email reminder scheduler
│
├── orchestrator/                  # Multi-agent orchestration
│   ├── workflow.py                # State machine + 5 reasoning patterns
│   └── state.py                   # Shared session state (9 phases)
│
├── integrations/                  # External service clients
│   ├── azure_ai.py                # Azure AI Foundry GPT-4o client
│   ├── catalog_api.py             # Microsoft Learn Catalog API
│   ├── learn_mcp.py               # Microsoft Learn MCP Server
│   └── email_sender.py            # SMTP email sender
│
├── models/                        # Pydantic data models
│   ├── student.py                 # StudentProfile, ExamObjective, StudySession
│   ├── knowledge_graph.py         # NetworkX-based Knowledge Graph
│   └── assessment.py              # Question, Answer, AssessmentResult
│
├── ui/                            # Streamlit dashboard
│   ├── app.py                     # Main app + landing page
│   ├── pages/                     # Multi-page navigation
│   │   ├── 01_diagnostic.py       # Adaptive pre-test UI
│   │   ├── 02_knowledge_map.py    # Interactive Knowledge Graph
│   │   ├── 03_study_plan.py       # Study plan + MS Learn links
│   │   ├── 04_tutor.py            # Socratic chat interface
│   │   └── 05_assessment.py       # Final assessment
│   └── components/                # Reusable UI components
│       ├── brain_viz.py           # Plotly Knowledge Graph renderer
│       └── progress_bar.py        # Pipeline progress sidebar
│
├── evaluation/                    # Testing & metrics
│   ├── eval_runner.py             # Automated test cases
│   └── metrics.py                 # Performance metrics
│
└── docs/                          # Additional documentation
    ├── ARCHITECTURE.md            # Detailed architecture docs
    └── REASONING_FLOW.md          # Reasoning patterns deep-dive
```

---

## 🛡️ Responsible AI

CertBrain implements responsible AI practices:

- **Input Validation**: All student inputs are sanitized before processing
- **Output Guardrails**: Critic Agent verifies accuracy of all generated content against official documentation
- **Hallucination Prevention**: Cross-referencing with Microsoft Learn MCP Server ensures factual correctness
- **Content Safety**: Questions and responses are validated for appropriateness
- **Human Oversight**: Two human-in-the-loop checkpoints ensure student maintains control
- **Transparency**: All agent decisions are logged with reasoning traces
- **Fallback Handling**: Graceful error handling with clear user messaging when services are unavailable
- **Data Privacy**: No student data is stored permanently; all processing is session-based

---

## 📊 Evaluation

CertBrain includes automated evaluation capabilities:

- **Question Quality**: Validates generated questions cover exam objectives accurately
- **Knowledge Graph Coherence**: Checks dependency graph is acyclic and well-connected
- **Study Plan Coverage**: Ensures all exam objectives are mapped to learning modules
- **Tutor Effectiveness**: Measures mastery improvement across tutoring sessions
- **Agent Latency**: Tracks response times and token usage per agent

---

## 🏆 Hackathon Submission

**Track**: 🧠 Reasoning Agents — Microsoft Agents League 2026

**Challenge**: Build a multi-agent system for Microsoft certification exam preparation

**What makes CertBrain unique:**

1. **Cognitive Science Foundation** — Not just another quiz app; applies real learning science (IRT, ZPD, SM-2, Bloom's)
2. **Dynamic Knowledge Graph** — Visual representation of the student's cognitive state that evolves in real-time
3. **5 Explicit Reasoning Patterns** — Planner-Executor, Critic/Verifier, Self-Reflection, Human-in-the-Loop, Conditional Loops
4. **Real Integrations** — Live connections to Microsoft Learn MCP, Catalog API, and Azure AI Foundry
5. **Production-Ready** — Complete Streamlit dashboard, proper error handling, logging, and evaluation

---

## 📝 License

This project is licensed under the MIT License — see the [LICENSE](../LICENSE) file for details.

## 🙏 Acknowledgments

- [Microsoft Agents League](https://github.com/microsoft/agentsleague) — Hackathon organizers
- [Microsoft Learn MCP Server](https://learn.microsoft.com/training/support/mcp) — Documentation integration
- [Microsoft Learn Catalog API](https://learn.microsoft.com/training/support/catalog-api) — Training content metadata
- [Azure AI Foundry](https://ai.azure.com) — AI model hosting and agent services
