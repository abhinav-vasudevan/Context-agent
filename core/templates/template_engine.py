import logging
from pathlib import Path
from typing import Dict, Any, Optional
import jinja2

log = logging.getLogger(__name__)

class TemplateEngine:
    """
    Renders boilerplate code using Jinja2 templates.
    Used in Phase 3 of execution to generate standard patterns (MVC, CRUD, API)
    without wasting LLM tokens.
    """
    def __init__(self, templates_dir: Optional[Path] = None):
        if templates_dir is None:
            # Default to core/templates/files relative to this file
            self.templates_dir = Path(__file__).parent / "files"
        else:
            self.templates_dir = templates_dir
            
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.templates_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True
        )

    def get_template_for_file(self, file_path: str) -> Optional[str]:
        """
        Determine the template name based on file path conventions.
        Returns the template filename (e.g. 'api_endpoint.py.j2') or None.
        """
        path = Path(file_path)
        name = path.name.lower()
        
        if name.endswith("_model.py") or name == "models.py":
            return "model.py.j2"
        elif name.endswith("_service.py") or name == "service.py":
            return "service.py.j2"
        elif name.endswith("_controller.py") or name.endswith("_api.py") or name.endswith("_router.py"):
            return "api_endpoint.py.j2"
            
        return None

    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render a Jinja2 template with the given context."""
        try:
            template = self.env.get_template(template_name)
            return template.render(**context)
        except jinja2.TemplateNotFound:
            log.warning(f"Template not found: {template_name}")
            return ""
        except Exception as e:
            log.error(f"Template rendering failed: {e}")
            return ""
