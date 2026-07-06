"""
Knowledge Graph — Neo4j-backed graph of project architecture.

Stores:
  - Nodes: Subsystem, Service, Module, File, Class, Function
  - Edges: OWNS, USES, IMPLEMENTS, DEPENDS_ON, IMPORTS

This is the primary mechanism for "file 78 knowing about file 2"
without both ever appearing in the same LLM context window.

The graph is persisted in Neo4j and queried at context assembly time
to retrieve only the relevant subgraph for the current task.
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


class KnowledgeGraph:
    """
    Neo4j-backed Knowledge Graph for the Project Brain.

    Node types:
      - Project, Subsystem, Service, Module, File, Class, Function

    Edge types:
      - OWNS (parent -> child in the hierarchy)
      - USES (runtime dependency between services/modules)
      - IMPLEMENTS (a File implements a Service contract)
      - DEPENDS_ON (import-level dependency between files)
      - IMPORTS (specific import statement)
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
        database: str = "neo4j",
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self._driver = None

        if HAS_NEO4J:
            try:
                self._driver = GraphDatabase.driver(uri, auth=(user, password))
                # Verify connectivity
                self._driver.verify_connectivity()
                log.info("Connected to Neo4j at %s", uri)
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

    def execute_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Execute a raw Cypher query and return the results as a list of dicts."""
        if not self._driver:
            return []
        try:
            with self._driver.session(database=self.database) as session:
                result = session.run(query, parameters or {})
                return [dict(record) for record in result]
        except Exception as e:
            log.error("Failed to execute Cypher query: %s", e)
            return []

    # ── Schema Setup ──────────────────────────────────────────────────

    def _ensure_indexes(self):
        """Create indexes for fast lookups."""
        if not self._driver:
            return
        queries = [
            "CREATE INDEX IF NOT EXISTS FOR (n:Project) ON (n.name)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Subsystem) ON (n.name)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Service) ON (n.name)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Module) ON (n.name)",
            "CREATE INDEX IF NOT EXISTS FOR (n:File) ON (n.path)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Class) ON (n.name)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Function) ON (n.name)",
        ]
        with self._driver.session(database=self.database) as session:
            for q in queries:
                try:
                    session.run(q)
                except Exception as e:
                    log.debug("Index creation note: %s", e)

    def clear_project(self, project_name: str):
        """Remove all nodes and edges for a given project."""
        if not self._driver:
            return
        with self._driver.session(database=self.database) as session:
            # Use directed hierarchical traversal to avoid OOM path explosion
            session.run(
                "MATCH (p:Project {name: $name})-[:OWNS|CONTAINS*0..]->(n) DETACH DELETE p, n",
                name=project_name,
            )
            log.info("Cleared graph for project: %s", project_name)

    # ── Node Operations ───────────────────────────────────────────────

    def add_node(self, label: str, properties: Dict[str, Any]) -> Optional[str]:
        """
        Create or merge a node with the given label and properties.
        
        Args:
            label: Node type (Project, Subsystem, Service, Module, File, Class, Function)
            properties: Dict of node properties (must include 'name' or 'path')
            
        Returns:
            The node's identifier (name or path), or None on failure.
        """
        if not self._driver:
            return None

        key_field = "path" if label == "File" else "name"
        key_value = properties.get(key_field, "")
        if not key_value:
            log.warning("Cannot add %s node without '%s' property", label, key_field)
            return None

        # Build MERGE query dynamically
        set_clause = ", ".join(f"n.{k} = ${k}" for k in properties.keys())
        query = f"MERGE (n:{label} {{{key_field}: ${key_field}}}) SET {set_clause} RETURN n.{key_field} AS id"

        with self._driver.session(database=self.database) as session:
            result = session.run(query, **properties)
            record = result.single()
            return record["id"] if record else None

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
        Create a directed edge between two nodes.
        
        Args:
            from_label: Source node type
            from_key: Source node name/path
            to_label: Target node type
            to_key: Target node name/path
            edge_type: Relationship type (OWNS, USES, DEPENDS_ON, etc.)
            properties: Optional edge properties
            
        Returns:
            True if edge was created successfully.
        """
        if not self._driver:
            return False

        from_field = "path" if from_label == "File" else "name"
        to_field = "path" if to_label == "File" else "name"

        props_str = ""
        params = {"from_key": from_key, "to_key": to_key}
        if properties:
            props_str = " {" + ", ".join(f"{k}: ${k}" for k in properties.keys()) + "}"
            params.update(properties)

        query = (
            f"MATCH (a:{from_label} {{{from_field}: $from_key}}) "
            f"MATCH (b:{to_label} {{{to_field}: $to_key}}) "
            f"MERGE (a)-[r:{edge_type}{props_str}]->(b) "
            f"RETURN type(r) AS rel"
        )

        with self._driver.session(database=self.database) as session:
            result = session.run(query, **params)
            return result.single() is not None

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
            "MATCH (f:File {path: $path})-[r*1.." + str(depth) + "]-(related:File) "
            "RETURN DISTINCT related.path AS path, related.purpose AS purpose, "
            "[rel IN r | type(rel)] AS relationships"
        )

        with self._driver.session(database=self.database) as session:
            result = session.run(query, path=file_path)
            return [dict(record) for record in result]

    def get_subsystem_for_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Find the subsystem that owns a given file (via Service → Module → File chain)."""
        if not self._driver:
            return None

        query = (
            "MATCH (sub:Subsystem)-[:OWNS*]->(f:File {path: $path}) "
            "RETURN sub.name AS name, sub.purpose AS purpose, sub.description AS description "
            "LIMIT 1"
        )

        with self._driver.session(database=self.database) as session:
            result = session.run(query, path=file_path)
            record = result.single()
            return dict(record) if record else None

    def get_files_in_subsystem(self, subsystem_name: str) -> List[str]:
        """Get all file paths owned by a subsystem."""
        if not self._driver:
            return []

        query = (
            "MATCH (sub:Subsystem {name: $name})-[:OWNS*]->(f:File) "
            "RETURN f.path AS path ORDER BY f.path"
        )

        with self._driver.session(database=self.database) as session:
            result = session.run(query, name=subsystem_name)
            return [record["path"] for record in result]

    def get_dependency_chain(self, file_path: str) -> List[str]:
        """Get the ordered list of files that must exist before this file can be built."""
        if not self._driver:
            return []

        query = (
            "MATCH (f:File {path: $path})-[:DEPENDS_ON*]->(dep:File) "
            "RETURN DISTINCT dep.path AS path"
        )

        with self._driver.session(database=self.database) as session:
            result = session.run(query, path=file_path)
            return [record["path"] for record in result]

    def get_impact_analysis(self, file_path: str) -> Dict[str, List[str]]:
        """
        Change Impact Analysis: determine what is affected if this file changes.
        
        Returns:
            Dict with keys: affected_files, affected_services, affected_subsystems, affected_tests
        """
        if not self._driver:
            return {"affected_files": [], "affected_services": [], "affected_subsystems": [], "affected_tests": []}

        result = {
            "affected_files": [],
            "affected_services": [],
            "affected_subsystems": [],
            "affected_tests": [],
        }

        with self._driver.session(database=self.database) as session:
            # Files that depend on this file
            r = session.run(
                "MATCH (dep:File)-[:DEPENDS_ON|IMPORTS*]->(f:File {path: $path}) "
                "RETURN DISTINCT dep.path AS path",
                path=file_path,
            )
            result["affected_files"] = [rec["path"] for rec in r]

            # Services that own this file
            r = session.run(
                "MATCH (svc:Service)-[:OWNS*]->(f:File {path: $path}) "
                "RETURN DISTINCT svc.name AS name",
                path=file_path,
            )
            result["affected_services"] = [rec["name"] for rec in r]

            # Subsystems
            r = session.run(
                "MATCH (sub:Subsystem)-[:OWNS*]->(f:File {path: $path}) "
                "RETURN DISTINCT sub.name AS name",
                path=file_path,
            )
            result["affected_subsystems"] = [rec["name"] for rec in r]

        return result

    def get_architecture_overview(self) -> List[Dict[str, Any]]:
        """
        Get a high-level overview of the entire project architecture.
        
        Returns a list of subsystems with their services and file counts.
        Used to build the architecture context for the LLM prompt.
        """
        if not self._driver:
            return []

        query = (
            "MATCH (sub:Subsystem) "
            "OPTIONAL MATCH (sub)-[:OWNS]->(svc:Service) "
            "OPTIONAL MATCH (svc)-[:OWNS*]->(f:File) "
            "RETURN sub.name AS subsystem, sub.purpose AS purpose, "
            "collect(DISTINCT svc.name) AS services, "
            "count(DISTINCT f) AS file_count "
            "ORDER BY sub.name"
        )

        with self._driver.session(database=self.database) as session:
            result = session.run(query)
            return [dict(record) for record in result]

    def get_graph_data(self, project_name: str = None) -> Dict[str, Any]:
        """Get raw nodes and links for visualization. If project_name is provided, filters to that project."""
        if not self._driver:
            return {"nodes": [], "links": []}
            
        nodes = []
        links = []
        with self._driver.session(database=self.database) as session:
            # Get nodes
            if project_name:
                n_query = "MATCH (p:Project {name: $name})-[:OWNS|CONTAINS*0..]->(n) RETURN DISTINCT elementId(n) as node_id, labels(n) as labels, properties(n) as props"
                n_result = session.run(n_query, name=project_name)
            else:
                n_result = session.run("MATCH (n) RETURN elementId(n) as node_id, labels(n) as labels, properties(n) as props")
                
            for record in n_result:
                props = record["props"]
                node_name = props.get("name", props.get("path", str(record["node_id"])))
                nodes.append({
                    "id": node_name,
                    "labels": record["labels"],
                    "properties": props
                })
                
            # Get edges
            if project_name:
                e_query = """
                MATCH (p:Project {name: $name})-[:OWNS|CONTAINS*0..]->(a)
                MATCH (p)-[:OWNS|CONTAINS*0..]->(b)
                MATCH (a)-[r]->(b)
                RETURN properties(a) as a_props, type(r) as type, properties(b) as b_props, elementId(a) as aid, elementId(b) as bid
                """
                e_result = session.run(e_query, name=project_name)
            else:
                e_result = session.run("MATCH (a)-[r]->(b) RETURN properties(a) as a_props, type(r) as type, properties(b) as b_props, elementId(a) as aid, elementId(b) as bid")
                
            for record in e_result:
                a_props = record["a_props"]
                b_props = record["b_props"]
                source_id = a_props.get("name", a_props.get("path", str(record["aid"])))
                target_id = b_props.get("name", b_props.get("path", str(record["bid"])))
                links.append({
                    "source": source_id,
                    "target": target_id,
                    "type": record["type"]
                })
                
        return {"nodes": nodes, "links": links}
