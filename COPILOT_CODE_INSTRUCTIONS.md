# CertBrain — Master Build Instructions

## PROJECT CONTEXT
CertBrain is a multi-agent system for the Microsoft Agents League Hackathon (Reasoning Agents track). It helps students prepare for Microsoft certification exams using cognitive science (spaced repetition, Bloom's taxonomy, Vygotsky's ZPD) and a dynamic Knowledge Graph.

## TECH STACK
- Python 3.10+
- Azure AI Foundry SDK (azure-ai-projects, azure-ai-agents) with PROJECT_ENDPOINT auth via DefaultAzureCredential
- Microsoft Learn MCP Server (https://learn.microsoft.com/api/mcp) — remote MCP, streamable HTTP, no auth required
- Microsoft Learn Catalog API (https://learn.microsoft.com/api/catalog/) — REST, no auth, returns JSON with certifications, exams, learning paths, modules
- NetworkX for Knowledge Graph
- Streamlit for UI dashboard
- Plotly for visualizations

## ARCHITECTURE (6 agents orchestrated sequentially with conditional loops)
1. Diagnostic Agent — Adaptive pre-test (CAT algorithm). Generates questions from exam objectives, adjusts difficulty based on responses.
2. Knowledge Architect Agent — Builds a NetworkX knowledge graph from diagnostic results. Nodes=concepts, edges=dependencies, attributes=mastery_level(0-1).
3. Curriculum Optimizer Agent — Creates study plan with spaced repetition (SM-2 algorithm). Maps to Microsoft Learn modules via Catalog API.
4. Socratic Tutor Agent — Interactive teaching using Bloom's taxonomy levels. Never gives direct answers, asks escalating questions.
5. Critic/Verifier Agent — Reviews ALL agent outputs for accuracy against Microsoft Learn MCP docs. Self-reflection when confidence < 0.7.
6. Engagement Agent — Sends email reminders adapted to student patterns.

## ORCHESTRATION FLOW
Student selects certification → Diagnostic Agent (pre-test) → Knowledge Architect (build graph) → Critic verifies → Curriculum Optimizer (study plan) → Engagement Agent (reminders) → HUMAN CONFIRMS → Socratic Tutor (study sessions) → HUMAN READY → Diagnostic Agent (final assessment) → Pass ≥80%? → Yes: recommend exam / No: loop back

## .ENV VARIABLES AVAILABLE
- PROJECT_ENDPOINT=https://xxx.services.ai.azure.com/api/projects/xxx
- MODEL_DEPLOYMENT_NAME=gpt-4o

## CRITICAL IMPLEMENTATION RULES
1. Use `from azure.identity import DefaultAzureCredential` for auth (user already ran `az login`)
2. Use `azure.ai.projects.AIProjectClient` with endpoint param
3. For the MCP Learn Server: use httpx with streamable HTTP to https://learn.microsoft.com/api/mcp (or use the mcp Python package)
4. For Catalog API: simple GET requests to https://learn.microsoft.com/api/catalog/ with query params
5. All agent prompts must be detailed and include their specific role, reasoning patterns, and output format
6. Use Pydantic models for all data structures
7. Implement proper error handling with fallbacks
8. Add logging with Python's logging module for telemetry
9. Each agent must be independently testable
10. Include Responsible AI: input validation, output guardrails, content safety considerations

## FILE STRUCTURE (all files already created, need content)
certbrain/
├── main.py                        # Entry point
├── config.py                      # Centralized config
├── requirements.txt               # Already done
├── agents/                        # All 6 agents
│   ├── diagnostic_agent.py
│   ├── knowledge_architect.py
│   ├── curriculum_optimizer.py
│   ├── socratic_tutor.py
│   ├── critic_agent.py
│   └── engagement_agent.py
├── orchestrator/
│   ├── workflow.py                # Main orchestration
│   └── state.py                   # Shared state
├── integrations/
│   ├── learn_mcp.py               # MS Learn MCP client
│   ├── catalog_api.py             # Catalog API client
│   └── email_sender.py            # Email via SMTP
├── models/
│   ├── student.py                 # Student profile model
│   ├── knowledge_graph.py         # KG with NetworkX
│   └── assessment.py              # Assessment models
├── ui/
│   ├── app.py                     # Streamlit main
│   └── pages/                     # Multi-page app
├── evaluation/
│   ├── eval_runner.py
│   └── metrics.py
└── docs/
    ├── ARCHITECTURE.md
    └── REASONING_FLOW.md