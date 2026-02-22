"""CertBrain — Knowledge Graph built on NetworkX.

Models concepts (exam objectives) as nodes and prerequisite relationships
as directed edges.  Tracks per-concept mastery so that agents can identify
the *learning frontier* (concepts the student is ready to tackle next)
and *weak areas* (low-mastery concepts that block progress).
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from config import get_logger

logger = get_logger(__name__)


class KnowledgeGraph:
    """Directed acyclic graph of certification concepts and their dependencies.

    Each node stores:
        - ``mastery`` (float 0-1): current student mastery estimate
        - ``name`` (str): human-readable concept name
        - any extra metadata passed to :meth:`add_concept`

    Edges represent *prerequisite* relationships:
        ``add_dependency(prereq, dependent)`` means *prereq* must be learned
        before *dependent*.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------
    def add_concept(
        self,
        concept_id: str,
        name: str = "",
        mastery: float = 0.0,
        **metadata: Any,
    ) -> None:
        """Add or update a concept node.

        Parameters
        ----------
        concept_id:
            Unique identifier (typically ``ExamObjective.id``).
        name:
            Human-readable label.
        mastery:
            Initial mastery estimate (0-1).
        **metadata:
            Arbitrary extra attributes stored on the node.
        """
        self._graph.add_node(
            concept_id,
            name=name,
            mastery=max(0.0, min(1.0, mastery)),
            **metadata,
        )
        logger.debug("add_concept  id=%s mastery=%.2f", concept_id, mastery)

    def add_dependency(self, prerequisite_id: str, dependent_id: str) -> None:
        """Declare that *prerequisite_id* must be mastered before *dependent_id*.

        Both nodes are auto-created with default mastery 0 if they don't exist.
        Raises ``ValueError`` if the edge would create a cycle.
        """
        for nid in (prerequisite_id, dependent_id):
            if nid not in self._graph:
                self.add_concept(nid)

        # Prevent cycles
        if nx.has_path(self._graph, dependent_id, prerequisite_id):
            raise ValueError(
                f"Adding edge {prerequisite_id} → {dependent_id} would create a cycle"
            )

        self._graph.add_edge(prerequisite_id, dependent_id)
        logger.debug("add_dependency %s → %s", prerequisite_id, dependent_id)

    def update_mastery(self, concept_id: str, mastery: float) -> None:
        """Set the mastery value for an existing concept.

        Raises ``KeyError`` if the concept does not exist.
        """
        if concept_id not in self._graph:
            raise KeyError(f"Concept '{concept_id}' not in graph")
        self._graph.nodes[concept_id]["mastery"] = max(0.0, min(1.0, mastery))
        logger.debug("update_mastery %s → %.2f", concept_id, mastery)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_mastery(self, concept_id: str) -> float:
        """Return current mastery for *concept_id*."""
        return self._graph.nodes[concept_id]["mastery"]

    def get_learning_frontier(self, mastery_threshold: float = 0.8) -> list[str]:
        """Return concept IDs the student is *ready* to learn next.

        A concept is on the frontier when:
        1. Its own mastery is below *mastery_threshold*.
        2. **All** its prerequisites have mastery >= *mastery_threshold*.

        Returns a list sorted by current mastery (lowest first) so the
        most impactful concepts come first.
        """
        frontier: list[str] = []
        for node in self._graph.nodes:
            node_mastery: float = self._graph.nodes[node]["mastery"]
            if node_mastery >= mastery_threshold:
                continue
            predecessors = list(self._graph.predecessors(node))
            if all(
                self._graph.nodes[p]["mastery"] >= mastery_threshold
                for p in predecessors
            ):
                frontier.append(node)
        frontier.sort(key=lambda n: self._graph.nodes[n]["mastery"])
        return frontier

    def get_weak_areas(self, threshold: float = 0.5) -> list[str]:
        """Return concept IDs with mastery strictly below *threshold*.

        Sorted by mastery ascending (weakest first).
        """
        weak = [
            n
            for n in self._graph.nodes
            if self._graph.nodes[n]["mastery"] < threshold
        ]
        weak.sort(key=lambda n: self._graph.nodes[n]["mastery"])
        return weak

    def get_topological_order(self) -> list[str]:
        """Return concept IDs in topological (prerequisite-first) order."""
        return list(nx.topological_sort(self._graph))

    @property
    def concepts(self) -> list[str]:
        """All concept IDs currently in the graph."""
        return list(self._graph.nodes)

    @property
    def num_concepts(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def num_dependencies(self) -> int:
        return self._graph.number_of_edges()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Serialize the graph to a plain dict (JSON-safe).

        Format::

            {
                "nodes": [{"id": "...", "name": "...", "mastery": 0.5, ...}, …],
                "edges": [{"source": "A", "target": "B"}, …]
            }
        """
        nodes = []
        for nid, attrs in self._graph.nodes(data=True):
            nodes.append({"id": nid, **attrs})
        edges = [
            {"source": u, "target": v} for u, v in self._graph.edges
        ]
        return {"nodes": nodes, "edges": edges}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeGraph:
        """Reconstruct a KnowledgeGraph from a dict produced by :meth:`to_dict`."""
        kg = cls()
        for node in data.get("nodes", []):
            nid = node.pop("id")
            kg.add_concept(nid, **node)
        for edge in data.get("edges", []):
            kg.add_dependency(edge["source"], edge["target"])
        return kg

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------
    def __contains__(self, concept_id: str) -> bool:
        return concept_id in self._graph

    def __len__(self) -> int:
        return self.num_concepts

    def __repr__(self) -> str:
        return (
            f"KnowledgeGraph(concepts={self.num_concepts}, "
            f"dependencies={self.num_dependencies})"
        )
