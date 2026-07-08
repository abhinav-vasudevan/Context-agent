import re

with open('backend/orchestrator.py', 'r') as f:
    content = f.read()

# There are two places where RepositoryIngester is initialized
# One in `__init__` (around line 171) and one in `load_project` (around line 218)

wrong_init = "self.ingester = RepositoryIngester(self.llm, self.brain.graph, self.brain.semantic, self.state)"
right_init = "self.ingester = RepositoryIngester(self.workspace_dir, self.brain, self.summarizer, self.understanding_agent, state=self.state)"

content = content.replace(wrong_init, right_init)

with open('backend/orchestrator.py', 'w') as f:
    f.write(content)

print("Fixed RepositoryIngester init in orchestrator.py")
