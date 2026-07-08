import re

with open('frontend/src/services/api.js', 'r') as f:
    content = f.read()

def get_replacement_always_form(func_name, field_name):
    return f"""
  {func_name}: ({field_name}, files = []) => {{
    const formData = new FormData();
    formData.append('{field_name}', {field_name});
    if (files) {{
      files.forEach(f => formData.append('files', f));
    }}
    
    return fetch(`${{API_BASE}}/api/{'project/followup' if func_name == 'projectFollowup' else 'plan/generate'}`, {{
      method: 'POST',
      body: formData,
    }}).then(async (res) => {{
      if (!res.ok) {{
        const error = await res.json().catch(() => ({{ detail: res.statusText }}));
        throw new Error(error.detail || `Request failed: ${{res.status}}`);
      }}
      return res.json();
    }});
  }},
"""

# Replace the complex if/else ones with the always-form ones
content = re.sub(r'projectFollowup:\s*\(text,\s*files\s*=\s*\[\]\)\s*=>\s*\{[\s\S]*?\}\s*\},', get_replacement_always_form('projectFollowup', 'text').strip(), content)
content = re.sub(r'generatePlan:\s*\(prompt,\s*files\s*=\s*\[\]\)\s*=>\s*\{[\s\S]*?\}\s*\},', get_replacement_always_form('generatePlan', 'prompt').strip(), content)

with open('frontend/src/services/api.js', 'w') as f:
    f.write(content)

print("Fixed api.js to always use FormData")
