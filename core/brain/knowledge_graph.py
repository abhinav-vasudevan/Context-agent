"""
Knowledge Graph — Neo4j-backed graph of project architecture.

Stores:
  - Nodes: Project, Subsystem, Service, File, Symbol
  - Edges: OWNS, USES, IMPLEMENTS, DEPENDS_ON, IMPORTS, CONTAINS

This is the primary mechanism for "file 78 knowing about file 2"
without both ever appearing in the same LLM context window.

The graph is persisted in Neo4j and queried at context assembly time
to retrieve only the relevant subgraph for the current task.

Project isolation
-----------------
All projects share one Neo4j database, so every node carries a ``project``
property (the KnowledgeGraph's ``project`` key — the workspace path) and is
MERGEd on ``(project, key)``. Every read and write is filtered by it, so a
"Frontend" subsystem or a ``src/main.py`` in one project is a different node
from the same name in another project. Raw queries passed to
``execute_query`` automatically receive a ``$project`` parameter and MUST
filter on it.
"""

from __future__ import annotations
import logging
from typing import List, Dict, Optional, Any

log = logging.getLogger(__name__)

# ── Neo4j availability check ─────────────────────────────────────────
try:
    from neo4j import GraphDatabase
    HAS_NEO4J = True
except ImportError as e:
    HAS_NEO4J = False
    log.warning(f"neo4j driver not installed. Run: pip install neo4j. Error: {e}")


def _key_field(label: str) -> str:
    """The property that uniquely identifies a node of this label within a project."""
    if label == "File":
        return "path"
    if label == "Symbol":
        return "id"
    return "name"


class KnowledgeGraph:
    """
    Neo4j-backed Knowledge Graph for the Project Brain, scoped to one project.

    Node types:
      - Project, Subsystem, Service, File, Symbol

    Edge types:
      - OWNS (parent -> child in the hierarchy)
      - USES (runtime dependency between services/modules)
      - IMPLEMENTS (a File implements a Service contract)
      - DEPENDS_ON (import-level dependency between files)
      - IMPORTS (specific import statement)
      - CONTAINS (File -> Symbol)
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
        database: str = "neo4j",
        project: str = "",
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.project = project
        self._driver = None

        if not project:
            log.warning("KnowledgeGraph created without a project key; data will not be isolated.")

        if HAS_NEO4J:
            try:
                self._driver = GraphDatabase.driver(uri, auth=(user, password))
                # Verify connectivity
                self._driver.verify_connectivity()
                log.info("Connected to Neo4j at %s (project=%s)", uri, project)
                self._ensure_indexes()
            except Exception as e:
                log.warning("Neo4j connection failed: %s. Graph features disabled.", e)
                self._driver = None
        else:
            log.warning("Neo4j driver not available. Graph features disabled.")

    @property
    def is_available(self) -> bool:
        """Check if Neo4j is connected and operational."""
        return self._driver is not None

    def close(self):
        """Close the Neo4j driver connection."""
        if self._driver:
            self._driver.close()
            self._driver = None

    def _run(self, query: str, **params) -> List[Dict[str, Any]]:
        """Run a query with ``$project`` bound to this graph's project."""
        with self._driver.session(database=self.database) as session:
            result = session.run(query, project=self.project, **params)
            return [dict(record) for record in result]

    def execute_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Execute a raw Cypher query and return the results as a list of dicts.

        ``$project`` is always bound to this graph's project key; queries must
        use it (e.g. ``MATCH (f:File {project: $project})``) to stay isolated.
        """
        if not self._driver:
            return []
        params = {k: v for k, v in (parameters or {}).items() if k != "project"}
        try:
            return self._run(query, **params)
        except Exception as e:
            log.error("Failed to execute Cypher query: %s", e)
            return []

    # ── Schema Setup ──────────────────────────────────────────────────

    def _ensure_indexes(self):
        """Create (project, key) indexes for fast scoped lookups."""
        if not self._driver:
            return
        queries = [
            f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.project, n.{_key_field(label)})"
            for label in ("Project", "Subsystem", "Service", "Module", "File", "Symbol")
        ]
        with self._driver.session(database=self.database) as session:
            for q in queries:
                try:
                    session.run(q)
                except Exception as e:
                    log.debug("Index creation note: %s", e)

    def clear_project(self, project_name: str = None):
        """Remove all nodes and edges belonging to this graph's project.

        ``project_name`` is accepted for backward compatibility and ignored —
        isolation is by the project key, not the display name.
        """
        if not self._driver:
            return
        self._run("MATCH (n {project: $project}) DETACH DELETE n")
        log.info("Cleared graph for project: %s", self.project)

    # ── Node Operations ───────────────────────────────────────────────

    def add_node(self, label: str, properties: Dict[str, Any]) -> Optional[str]:
        """
        Create or merge a node (within this project) with the given label and properties.

        Args:
            label: Node type (Project, Subsystem, Service, File, Symbol)
            properties: Dict of node properties (must include the label's key:
                        'path' for File, 'id' for Symbol, 'name' otherwise)

        Returns:
            The node's identifier, or None on failure.
        """
        if not self._driver:
            return None

        key_field = _key_field(label)
        key_value = properties.get(key_field, "")
        if not key_value:
            log.warning("Cannot add %s node without '%s' property", label, key_field)
            return None

        props = {k: v for k, v in properties.items() if k != "project"}
        set_clause = ", ".join(f"n.{k} = $p_{k}" for k in props.keys())
        query = (
            f"MERGE (n:{label} {{project: $project, {key_field}: $key}}) "
            f"SET {set_clause} RETURN n.{key_field} AS id"
        )
        rows = self._run(query, key=key_value, **{f"p_{k}": v for k, v in props.items()})
        return rows[0]["id"] if rows else None

    def add_edge(
        self,
        from_label: str,
        from_key: str,
        to_label: str,
        to_key: str,
        edge_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Create a directed edge between two nodes of this project.

        Args:
            from_label: Source node type
            from_key: Source node key (name/path/id)
            to_label: Target node type
            to_key: Target node key (name/path/id)
            edge_type: Relationship type (OWNS, USES, DEPENDS_ON, etc.)
            properties: Optional edge properties

        Returns:
            True if edge was created successfully.
        """
        if not self._driver:
            return False

        from_field = _key_field(from_label)
        to_field = _key_field(to_label)

        props_str = ""
        params = {"from_key": from_key, "to_key": to_key}
        if properties:
            props_str = " {" + ", ".join(f"{k}: $e_{k}" for k in properties.keys()) + "}"
            params.update({f"e_{k}": v for k, v in properties.items()})

        query = (
            f"MATCH (a:{from_label} {{project: $project, {from_field}: $from_key}}) "
            f"MATCH (b:{to_label} {{project: $project, {to_field}: $to_key}}) "
            f"MERGE (a)-[r:{edge_type}{props_str}]->(b) "
            f"RETURN type(r) AS rel"
        )
        return bool(self._run(query, **params))

    # ── Query Operations ──────────────────────────────────────────────

    def get_related_files(self, file_path: str, depth: int = 2) -> List[Dict[str, Any]]:
        """
        Find all files related to the given file within N hops.

        This is the core query for context retrieval — it answers
        "What other files does file X depend on or is depended on by?"

        Args:
            file_path: The relative path of the file
            depth: Maximum number of hops to traverse

        Returns:
            List of dicts with file info and relationship paths
        """
        if not self._driver:
            return []

        query = (
            "MATCH (f:File {project: $project, path: $path})-[r*1.." + str(int(depth)) + "]-"
            "(related:File {project: $project}) "
            "RETURN DISTINCT related.path AS path, related.purpose AS purpose, "
            "[rel IN r | type(rel)] AS relationships"
        )
        return self._run(query, path=file_path)

    def get_subsystem_for_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Find the subsystem that owns a given file (via Service → File chain)."""
        if not self._driver:
            return None

        rows = self._run(
            "MATCH (sub:Subsystem {project: $project})-[:OWNS*]->(f:File {project: $project, path: $path}) "
            "RETURN sub.name AS name, sub.purpose AS purpose, sub.description AS description "
            "LIMIT 1",
            path=file_path,
        )
        return rows[0] if rows else None

    def get_files_in_subsystem(self, subsystem_name: str) -> List[str]:
        """Get all file paths owned by a subsystem."""
        if not self._driver:
            return []

        rows = self._run(
            "MATCH (sub:Subsystem {project: $project, name: $name})-[:OWNS*]->(f:File {project: $project}) "
            "RETURN DISTINCT f.path AS path ORDER BY path",
            name=subsystem_name,
        )
        return [r["path"] for r in rows]

    def get_dependency_chain(self, file_path: str) -> List[str]:
        """Get the ordered list of files that must exist before this file can be built."""
        if not self._driver:
            return []

        rows = self._run(
            "MATCH (f:File {project: $project, path: $path})-[:DEPENDS_ON*]->(dep:File {project: $project}) "
            "RETURN DISTINCT dep.path AS path",
            path=file_path,
        )
        return [r["path"] for r in rows]

    def get_impact_analysis(self, file_path: str) -> Dict[str, List[str]]:
        """
        Change Impact Analysis: determine what is affected if this file changes.

        Returns:
            Dict with keys: affected_files, affected_services, affected_subsystems, affected_tests
        """
        result = {
            "affected_files": [],
            "affected_services": [],
            "affected_subsystems": [],
            "affected_tests": [],
        }
        if not self._driver:
            return result

        # Files that depend on this file
        rows = self._run(
            "MATCH (dep:File {project: $project})-[:DEPENDS_ON|IMPORTS*]->(f:File {project: $project, path: $path}) "
            "RETURN DISTINCT dep.path AS path",
            path=file_path,
        )
        result["affected_files"] = [r["path"] for r in rows]

        # Services that own this file
        rows = self._run(
            "MATCH (svc:Service {project: $project})-[:OWNS*]->(f:File {project: $project, path: $path}) "
            "RETURN DISTINCT svc.name AS name",
            path=file_path,
        )
        result["affected_services"] = [r["name"] for r in rows]

        # Subsystems
        rows = self._run(
            "MATCH (sub:Subsystem {project: $project})-[:OWNS*]->(f:File {project: $project, path: $path}) "
            "RETURN DISTINCT sub.name AS name",
            path=file_path,
        )
        result["affected_subsystems"] = [r["name"] for r in rows]

        return result

    def get_architecture_overview(self) -> List[Dict[str, Any]]:
        """
        Get a high-level overview of this project's architecture.

        Returns a list of subsystems with their services and file counts.
        Used to build the architecture context for the LLM prompt.
        """
        if not self._driver:
            return []

        return self._run(
            "MATCH (sub:Subsystem {project: $project}) "
            "OPTIONAL MATCH (sub)-[:OWNS]->(svc:Service {project: $project}) "
            "OPTIONAL MATCH (svc)-[:OWNS*]->(f:File {project: $project}) "
            "RETURN sub.name AS subsystem, sub.purpose AS purpose, "
            "collect(DISTINCT svc.name) AS services, "
            "count(DISTINCT f) AS file_count "
            "ORDER BY subsystem"
        )

    def get_graph_data(self, project_name: str = None) -> Dict[str, Any]:
        """Get this project's raw nodes and links for visualization.

        ``project_name`` is accepted for backward compatibility and ignored —
        results are always scoped to this graph's project key.
        """
        if not self._driver:
            return {"nodes": [], "links": []}

        def node_id(props: Dict[str, Any], fallback: str) -> str:
            return props.get("name", props.get("path", props.get("id", fallback)))

        nodes = [
            {
                "id": node_id(r["props"], str(r["node_id"])),
                "labels": r["labels"],
                "properties": r["props"],
            }
            for r in self._run(
                "MATCH (n {project: $project}) "
                "RETURN elementId(n) AS node_id, labels(n) AS labels, properties(n) AS props"
            )
        ]
        links = [
            {
                "source": node_id(r["a_props"], str(r["aid"])),
                "target": node_id(r["b_props"], str(r["bid"])),
                "type": r["type"],
            }
            for r in self._run(
                "MATCH (a {project: $project})-[r]->(b {project: $project}) "
                "RETURN properties(a) AS a_props, type(r) AS type, properties(b) AS b_props, "
                "elementId(a) AS aid, elementId(b) AS bid"
            )
        ]
        return {"nodes": nodes, "links": links}
