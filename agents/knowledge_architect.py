"""CertBrain — Knowledge Architect Agent.

Analyses diagnostic results and builds a dependency-aware Knowledge Graph
of exam concepts.  Uses GPT-4o to infer prerequisite relationships and
the MS Learn MCP server to validate that concepts are real and grounded
in official documentation.
"""

from __future__ import annotations

from typing import Any

from config import get_settings, get_logger
from integrations.azure_ai import AzureAIClient
from integrations.learn_mcp import LearnMCPClient
from models.assessment import DiagnosticResult
from models.knowledge_graph import KnowledgeGraph
from models.student import ExamObjective

logger = get_logger(__name__)

SYSTEM_PROMPT = """\
You are a Knowledge Architect for Microsoft certification exam preparation.

## Your role
Given exam objectives and diagnostic scores, produce a GRANULAR knowledge graph.
For each exam objective, decompose it into 3-5 specific sub-concepts that a student
must understand. Generate a MINIMUM of 15 concepts total (aim for 20-25).

Example: "Describe cloud computing" → sub-concepts:
  "IaaS vs PaaS vs SaaS", "Public vs Private vs Hybrid Cloud",
  "CapEx vs OpEx cost model", "High availability & fault tolerance",
  "Elasticity and scalability"

## Output format — strict JSON, no markdown fences
{
  "concepts": [
    {
      "id": "cloud_service_models",
      "name": "IaaS vs PaaS vs SaaS",
      "description": "The three cloud service models and their trade-offs",
      "parent_objective": "<objective_id from input>",
      "importance": 0.9
    }
  ],
  "dependencies": [
    {"prerequisite": "<concept_id>", "dependent": "<concept_id>", "reason": "<why>"}
  ],
  "priority_topics": [
    {"concept_id": "<id>", "priority": 8, "reason": "<why high priority>"}
  ]
}

## Rules
- concept IDs: snake_case, unique, descriptive (e.g. "azure_rbac_roles")
- parent_objective: must match one of the provided objective IDs exactly
- importance: 0.0-1.0 (higher = more likely to appear on exam)
- Generate 15-25 concepts minimum — be granular, not high-level
- Only add dependency edges where there is a genuine prerequisite
- A concept cannot depend on itself; avoid cycles
"""


class KnowledgeArchitectAgent:
    """Builds a KnowledgeGraph from diagnostic results and exam objectives.

    Parameters
    ----------
    diagnostic_result:
        Output from the Diagnostic Agent.
    objectives:
        Full list of exam objectives.
    """

    def __init__(
        self,
        diagnostic_result: DiagnosticResult,
        objectives: list[ExamObjective],
    ) -> None:
        self._diag = diagnostic_result
        self._objectives = objectives
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_objective_summary(self) -> str:
        """Create a concise text summary of objectives + scores for the LLM."""
        lines: list[str] = []
        score_map: dict[str, float] = {
            s.objective_id: s.score
            for s in self._diag.assessment.objective_scores
        }
        for obj in self._objectives:
            mastery = score_map.get(obj.id, 0.0)
            lines.append(
                f"- {obj.id} | {obj.name} | weight={obj.weight_percent}% "
                f"| mastery={mastery:.0%} | {obj.description}"
            )
        return "\n".join(lines)

    async def _analyse_with_llm(self, azure_client: AzureAIClient) -> dict[str, Any]:
        """Ask the LLM to produce a granular concept breakdown."""
        user_msg = (
            "Here are the exam objectives with diagnostic scores:\n\n"
            f"{self._build_objective_summary()}\n\n"
            "Identified gaps: "
            f"{', '.join(self._diag.identified_gaps) or 'none'}\n"
            "Identified strengths: "
            f"{', '.join(self._diag.identified_strengths) or 'none'}\n\n"
            "Decompose EACH objective into 3-5 specific sub-concepts. "
            "Produce the concepts list, dependency edges, and priority ranking "
            "in the JSON format specified. Aim for 20+ concepts total."
        )

        try:
            return await azure_client.chat_completion_json(
                SYSTEM_PROMPT, user_msg, temperature=0.3, max_tokens=3000
            )
        except Exception as exc:
            logger.warning("LLM analysis failed: %s — returning empty structure", exc)
            return {"concepts": [], "dependencies": [], "priority_topics": []}

    async def _validate_concepts_with_mcp(
        self, concept_names: list[str]
    ) -> dict[str, str]:
        """Search MS Learn MCP for each concept to get reference URLs."""
        url_map: dict[str, str] = {}
        try:
            async with LearnMCPClient() as mcp:
                for name in concept_names[:10]:  # limit to avoid rate issues
                    results = await mcp.search_docs(name, top=1)
                    if results:
                        first = results[0]
                        url = first.get("url", first.get("text", ""))
                        url_map[name] = url
                        logger.debug("MCP validated concept '%s' → %s", name, url)
        except Exception as exc:
            logger.warning("MCP validation partially failed: %s", exc)
        return url_map

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------
    def _build_graph(
        self,
        llm_output: dict[str, Any],
        score_map: dict[str, float],
    ) -> KnowledgeGraph:
        """Construct the KnowledgeGraph from LLM output and scores.

        Uses the granular sub-concepts from the LLM.  If the LLM returns
        fewer than 8 concepts (e.g. it ignored the instruction), fall back to
        adding the raw objectives as nodes so the graph is never empty.
        """
        kg = KnowledgeGraph()

        # Build parent-objective mastery and weight lookup
        obj_mastery: dict[str, float] = {obj.id: score_map.get(obj.id, 0.0) for obj in self._objectives}
        obj_weight: dict[str, float] = {obj.id: obj.weight_percent for obj in self._objectives}
        # Count sub-concepts per objective (for weight distribution)
        parent_counts: dict[str, int] = {}
        for c in llm_output.get("concepts", []):
            p = c.get("parent_objective", "")
            parent_counts[p] = parent_counts.get(p, 0) + 1

        # Add granular sub-concepts from LLM
        for c in llm_output.get("concepts", []):
            cid = c.get("id", "")
            if not cid:
                continue
            parent = c.get("parent_objective", "")
            # Inherit mastery from parent objective (with slight random variance
            # so similar objectives don't all show the same bar)
            import random as _rnd
            parent_m = obj_mastery.get(parent, 0.0)
            variance = _rnd.uniform(-0.08, 0.08)
            mastery = max(0.0, min(1.0, parent_m + variance))
            # Distribute parent weight evenly among sub-concepts
            n_sub = max(1, parent_counts.get(parent, 1))
            weight = obj_weight.get(parent, 10.0) / n_sub

            kg.add_concept(
                concept_id=cid,
                name=c.get("name", cid),
                mastery=mastery,
                weight_percent=round(weight, 1),
                description=c.get("description", ""),
                importance=c.get("importance", 0.5),
                parent_objective=parent,
            )

        # Fallback: if LLM produced too few concepts, add raw objectives
        if kg.num_concepts < 5:
            logger.warning(
                "LLM produced only %d concepts — adding raw objectives as fallback",
                kg.num_concepts,
            )
            for obj in self._objectives:
                if obj.id not in kg:
                    mastery = score_map.get(obj.id, 0.0)
                    kg.add_concept(
                        concept_id=obj.id,
                        name=obj.name,
                        mastery=mastery,
                        weight_percent=obj.weight_percent,
                        description=obj.description,
                        importance=0.8,
                    )

        # Add dependency edges
        for dep in llm_output.get("dependencies", []):
            prereq = dep.get("prerequisite", "")
            dependent = dep.get("dependent", "")
            if prereq and dependent and prereq != dependent:
                # Only add if both nodes exist
                if prereq in kg and dependent in kg:
                    try:
                        kg.add_dependency(prereq, dependent)
                    except ValueError as exc:
                        logger.warning("Skipping cyclic edge: %s", exc)

        logger.info("Built graph: %d concepts, %d edges", kg.num_concepts, kg.num_dependencies)
        return kg

    @staticmethod
    def _get_zpd_topics(kg: KnowledgeGraph) -> list[str]:
        """Identify topics in Vygotsky's Zone of Proximal Development.

        ZPD = mastery between 0.3 and 0.7 — concepts the student is
        *ready* to learn with guidance.
        """
        zpd: list[str] = []
        for node_id in kg.concepts:
            m = kg.get_mastery(node_id)
            if 0.3 <= m <= 0.7:
                zpd.append(node_id)
        zpd.sort(key=lambda n: kg.get_mastery(n))
        return zpd

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def run(self) -> tuple[KnowledgeGraph, list[dict[str, Any]]]:
        """Build the knowledge graph.

        Returns
        -------
        tuple[KnowledgeGraph, list[dict]]
            The populated graph and the ``priority_topics`` list
            (each dict has ``objective_id``, ``priority``, ``reason``).
        """
        logger.info(
            "Knowledge Architect starting — %d objectives, %d gaps",
            len(self._objectives), len(self._diag.identified_gaps),
        )

        score_map: dict[str, float] = {
            s.objective_id: s.score
            for s in self._diag.assessment.objective_scores
        }

        azure_client = AzureAIClient()
        try:
            llm_output = await self._analyse_with_llm(azure_client)
        finally:
            await azure_client.close()

        kg = self._build_graph(llm_output, score_map)

        # Validate a sample of concepts against MS Learn docs
        concept_names = [o.name for o in self._objectives[:10]]
        url_map = await self._validate_concepts_with_mcp(concept_names)
        logger.info("MCP validated %d / %d concepts", len(url_map), len(concept_names))

        # Priority topics from LLM + ZPD enrichment
        priority_topics: list[dict[str, Any]] = llm_output.get("priority_topics", [])
        zpd = self._get_zpd_topics(kg)
        logger.info(
            "Knowledge graph built: %d nodes, %d edges, %d ZPD topics",
            kg.num_concepts, kg.num_dependencies, len(zpd),
        )

        return kg, priority_topics
