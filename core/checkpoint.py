import json
import logging
from pathlib import Path
from typing import Optional, Dict

log = logging.getLogger(__name__)

class CheckpointManager:
    """
    Manages persistent checkpoints for multi-day builds.
    
    If the system crashes (OOM, network drop, machine reboot), 
    the checkpoint file allows it to resume from the exact file
    it left off at within the current Epic/Sprint.
    """
    
    CHECKPOINT_FILE = "checkpoint.json"
    
    @staticmethod
    def get_checkpoint_path(workspace_dir: Path) -> Path:
        """Get the path to the checkpoint file within the project's brain directory."""
        # Using the standard agent_brain folder name
        return workspace_dir / ".agent_brain" / CheckpointManager.CHECKPOINT_FILE
        
    @staticmethod
    def save(workspace_dir: Path, epic_id: Optional[str], step_number: int, status: str) -> None:
        """
        Save the current progress as a checkpoint.
        Called after every successfully completed file.
        """
        try:
            path = CheckpointManager.get_checkpoint_path(workspace_dir)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "current_epic_id": epic_id,
                "current_step_number": step_number,
                "status": status,
            }
            
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("Failed to save checkpoint: %s", e)
            
    @staticmethod
    def load(workspace_dir: Path) -> Optional[Dict]:
        """
        Load an existing checkpoint if one exists.
        Returns None if no checkpoint is found.
        """
        path = CheckpointManager.get_checkpoint_path(workspace_dir)
        if not path.exists():
            return None
            
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Failed to read checkpoint file: %s", e)
            return None
            
    @staticmethod
    def clear(workspace_dir: Path) -> None:
        """
        Remove the checkpoint file.
        Called when the project (or epic) successfully completes.
        """
        try:
            path = CheckpointManager.get_checkpoint_path(workspace_dir)
            if path.exists():
                path.unlink()
        except Exception as e:
            log.warning("Failed to clear checkpoint file: %s", e)
