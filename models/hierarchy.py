"""
Hierarchy Models — data structures for Hierarchical Spec-Driven Planning.

These models represent the v2 architecture hierarchy:
  Project → Subsystems → Services → Modules → Files → Functions

Every node can be tracked through the planning pipeline (PENDING → IN_PROGRESS → COMPLETED).
All models are JSON-serializable for checkpoint/resume support.
"""

from __future__ import annotations
import uuid
import json
from typing import List, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from datetime import datetime


class NodeStatus(str, Enum):
    """Status of any hierarchical planning node."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ── Architectural Decision Record ─────────────────────────────────────

@dataclass
class ArchitectureDecisionRecord:
    """
    An Architectural Decision Record (ADR).
    
    Stores the *why* behind design choices so that future LLM generations
    can understand decisions made weeks or months ago without re-deriving them.
    
    Example:
        ADR #3: Use JWT for authentication
        Context: Need stateless auth for microservices
        Decision: JWT with RS256 signing
        Consequences: Token revocation is harder; need refresh token rotation
    """
    id: str = field(default_factory=lambda: f"adr_{uuid.uuid4().hex[:8]}")
    title: str = ""
    context: str = ""           # The problem or situation being addressed
    decision: str = ""          # What was decided
    alternatives: str = ""      # What other options were considered
    consequences: str = ""      # Tradeoffs and downstream effects
    risks: str = ""             # Known risks of this decision
    related_subsystems: List[str] = field(default_factory=list)
    related_files: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "context": self.context,
            "decision": self.decision,
            "alternatives": self.alternatives,
            "consequences": self.consequences,
            "risks": self.risks,
            "related_subsystems": self.related_subsystems,
            "related_files": self.related_files,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArchitectureDecisionRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Semantic Summary ──────────────────────────────────────────────────

@dataclass
class SemanticSummary:
    """
    Semantic summary of a code file, class, or function.
    
    Stored in ChromaDB for vector similarity retrieval.
    Unlike the AST registry (which stores *structure*), this stores *meaning*.
    
    Example:
        file: "src/dns_resolver.py"
        purpose: "Resolves hostnames to IP addresses using iterative DNS queries"
        constraints: ["Must support both IPv4 and IPv6", "Timeout after 5 seconds"]
        dependencies: ["src/network_socket.py", "src/cache.py"]
        risks: ["DNS poisoning if DNSSEC is not validated"]
    """
    id: str = field(default_factory=lambda: f"sem_{uuid.uuid4().hex[:8]}")
    entity_type: str = ""       # "file", "class", "function", "subsystem", "service"
    entity_path: str = ""       # e.g. "src/dns_resolver.py" or "Networking/DNS"
    purpose: str = ""
    responsibilities: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_path": self.entity_path,
            "purpose": self.purpose,
            "responsibilities": self.responsibilities,
            "constraints": self.constraints,
            "dependencies": self.dependencies,
            "exports": self.exports,
            "risks": self.risks,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SemanticSummary":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_embedding_text(self) -> str:
        """Create a natural-language string suitable for embedding."""
        parts = [f"{self.entity_type}: {self.entity_path}"]
        if self.purpose:
            parts.append(f"Purpose: {self.purpose}")
        if self.responsibilities:
            parts.append(f"Responsibilities: {', '.join(self.responsibilities)}")
        if self.constraints:
            parts.append(f"Constraints: {', '.join(self.constraints)}")
        if self.exports:
            parts.append(f"Exports: {', '.join(self.exports)}")
        return "\n".join(parts)


# ── Hierarchical Planning Nodes ───────────────────────────────────────

@dataclass
class ModuleSpec:
    """
    Level 4: A specific module/file to be generated.
    
    Example: "src/packet_filter.py" within the Firewall service.
    """
    id: str = field(default_factory=lambda: f"mod_{uuid.uuid4().hex[:8]}")
    name: str = ""
    file_path: str = ""
    description: str = ""
    status: NodeStatus = NodeStatus.PENDING
    dependencies: List[str] = field(default_factory=list)  # IDs of other ModuleSpecs
    exports: List[str] = field(default_factory=list)       # Expected public API

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "file_path": self.file_path,
            "description": self.description, "status": self.status.value,
            "dependencies": self.dependencies, "exports": self.exports,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModuleSpec":
        d = dict(data)
        if "status" in d:
            d["status"] = NodeStatus(d["status"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ServiceSpec:
    """
    Level 3: A logical service that owns multiple modules.
    
    Example: "Firewall" service containing rule_engine.py, packet_filter.py, policy_manager.py.
    """
    id: str = field(default_factory=lambda: f"svc_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    status: NodeStatus = NodeStatus.PENDING
    responsibilities: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)    # Public API contracts
    dependencies: List[str] = field(default_factory=list)   # IDs of other ServiceSpecs
    modules: List[ModuleSpec] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "status": self.status.value, "responsibilities": self.responsibilities,
            "interfaces": self.interfaces, "dependencies": self.dependencies,
            "modules": [m.to_dict() for m in self.modules],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceSpec":
        d = dict(data)
        if "status" in d:
            d["status"] = NodeStatus(d["status"])
        if "modules" in d:
            d["modules"] = [ModuleSpec.from_dict(m) for m in d["modules"]]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SubsystemSpec:
    """
    Level 2: A major subsystem within the architecture.
    
    Example: "Networking" subsystem containing TCP, UDP, DNS, Routing, Firewall services.
    """
    id: str = field(default_factory=lambda: f"sub_{uuid.uuid4().hex[:8]}")
    name: str = ""
    purpose: str = ""
    description: str = ""
    status: NodeStatus = NodeStatus.PENDING
    responsibilities: List[str] = field(default_factory=list)
    boundaries: List[str] = field(default_factory=list)    # What this subsystem does NOT do
    dependencies: List[str] = field(default_factory=list)   # IDs of other SubsystemSpecs
    services: List[ServiceSpec] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "purpose": self.purpose,
            "description": self.description, "status": self.status.value,
            "responsibilities": self.responsibilities, "boundaries": self.boundaries,
            "dependencies": self.dependencies,
            "services": [s.to_dict() for s in self.services],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SubsystemSpec":
        d = dict(data)
        if "status" in d:
            d["status"] = NodeStatus(d["status"])
        if "services" in d:
            d["services"] = [ServiceSpec.from_dict(s) for s in d["services"]]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ProjectScale(str, Enum):
    """Complexity classification for dynamic project sizing."""
    SIMPLE = "simple"       # 1-5 files (calculator, single script)
    MEDIUM = "medium"       # 5-30 files (web app, CLI tool)
    LARGE = "large"         # 30-100 files (coding agent, full-stack app)
    MASSIVE = "massive"     # 100+ files (OpenStack, OS, ERP system)


@dataclass
class EpicSpec:
    """
    V3 Epic — a Bounded Domain that is planned and built as a self-contained unit.
    
    Epics are the core unit of JIT (Just-In-Time) planning. The Master Planner
    generates Epics first (high-level bounded domains with public API contracts),
    then the Orchestrator plans and executes them one at a time.
    """
    id: str = field(default_factory=lambda: f"epic_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    purpose: str = ""
    status: NodeStatus = NodeStatus.PENDING
    scale_estimate: ProjectScale = ProjectScale.MEDIUM
    public_api_contract: List[str] = field(default_factory=list)
    depends_on_epics: List[str] = field(default_factory=list)
    subsystem: Optional[SubsystemSpec] = None
    completed_files: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "purpose": self.purpose, "status": self.status.value,
            "scale_estimate": self.scale_estimate.value,
            "public_api_contract": self.public_api_contract,
            "depends_on_epics": self.depends_on_epics,
            "subsystem": self.subsystem.to_dict() if self.subsystem else None,
            "completed_files": self.completed_files,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EpicSpec":
        d = dict(data)
        if "status" in d:
            d["status"] = NodeStatus(d["status"])
        if "scale_estimate" in d:
            d["scale_estimate"] = ProjectScale(d["scale_estimate"])
        if "subsystem" in d and d["subsystem"] is not None:
            d["subsystem"] = SubsystemSpec.from_dict(d["subsystem"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ArchitectureSpec:
    """
    Level 1: The overall system architecture.
    
    This is the root of the hierarchical plan. It owns all subsystems and ADRs.
    """
    id: str = field(default_factory=lambda: f"arch_{uuid.uuid4().hex[:8]}")
    name: str = ""
    vision: str = ""            # High-level system vision statement
    description: str = ""
    status: NodeStatus = NodeStatus.PENDING
    subsystems: List[SubsystemSpec] = field(default_factory=list)
    adrs: List[ArchitectureDecisionRecord] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "vision": self.vision,
            "description": self.description, "status": self.status.value,
            "subsystems": [s.to_dict() for s in self.subsystems],
            "adrs": [a.to_dict() for a in self.adrs],
            "constraints": self.constraints,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArchitectureSpec":
        d = dict(data)
        if "status" in d:
            d["status"] = NodeStatus(d["status"])
        if "subsystems" in d:
            d["subsystems"] = [SubsystemSpec.from_dict(s) for s in d["subsystems"]]
        if "adrs" in d:
            d["adrs"] = [ArchitectureDecisionRecord.from_dict(a) for a in d["adrs"]]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path):
        """Save architecture spec to JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Optional["ArchitectureSpec"]:
        """Load architecture spec from JSON."""
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except Exception:
            return None

    def get_all_modules(self) -> List[ModuleSpec]:
        """Flatten the hierarchy to get all modules in dependency order."""
        modules = []
        for subsystem in self.subsystems:
            for service in subsystem.services:
                modules.extend(service.modules)
        return modules

    def progress_percent(self) -> float:
        """Calculate overall completion percentage."""
        modules = self.get_all_modules()
        if not modules:
            return 0.0
        completed = sum(1 for m in modules if m.status == NodeStatus.COMPLETED)
        return round((completed / len(modules)) * 100, 1)
