import re

with open('frontend/src/pages/Workspace.jsx', 'r') as f:
    content = f.read()

replacement = """
    if (hasExistingPlan || attachedFiles.length > 0) {
      api.projectFollowup(prompt.trim() || 'Please process the attached documents.', attachedFiles)
        .then(() => loadFiles())
        .catch(console.error);
    } else {
      api.generatePlan(prompt.trim(), attachedFiles).then((res) => {
        if (res.success) {
          if (res.project) {
            setProject(res.project);
          } else if (res.plan_steps) {
            setProject(prev => ({ ...prev, plan_steps: res.plan_steps }));
          }
        }
        loadFiles();
      }).catch(console.error);
    }
"""

content = re.sub(r'if \(hasExistingPlan \|\| attachedFiles\.length > 0\) \{[\s\S]*?\}\s*\}\s*\}\)\.catch\(console\.error\);\s*\}', replacement.strip(), content)

with open('frontend/src/pages/Workspace.jsx', 'w') as f:
    f.write(content)

print("Fixed loadFiles in Workspace.jsx")
