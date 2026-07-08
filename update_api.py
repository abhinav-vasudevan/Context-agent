import re

with open('frontend/src/services/api.js', 'r') as f:
    content = f.read()

# We need to replace generatePlan and projectFollowup
def get_replacement(func_name, field_name):
    return f"""
  {func_name}: ({field_name}, files = []) => {{
    if (!files || files.length === 0) {{
      return request('/api/project/{'followup' if func_name == 'projectFollowup' else 'generate'}', {{
        method: 'POST',
        body: JSON.stringify({{ {field_name} }}),
      }});
    }} else {{
      const formData = new FormData();
      formData.append('{field_name}', {field_name});
      files.forEach(f => formData.append('files', f));
      
      return fetch(`${{API_BASE}}/api/project/{'followup' if func_name == 'projectFollowup' else 'generate'}`, {{
        method: 'POST',
        body: formData,
      }}).then(async (res) => {{
        if (!res.ok) {{
          const error = await res.json().catch(() => ({{ detail: res.statusText }}));
          throw new Error(error.detail || `Request failed: ${{res.status}}`);
        }}
        return res.json();
      }});
    }}
  }},
"""

content = re.sub(r'projectFollowup:\s*\(text\)\s*=>\s*request\(\'/api/project/followup\',\s*\{\s*method:\s*\'POST\',\s*body:\s*JSON\.stringify\(\{ text \}\),\s*\}\),', get_replacement('projectFollowup', 'text').strip(), content)
content = re.sub(r'generatePlan:\s*\(prompt\)\s*=>\s*request\(\'/api/plan/generate\',\s*\{\s*method:\s*\'POST\',\s*body:\s*JSON\.stringify\(\{ prompt \}\),\s*\}\),', get_replacement('generatePlan', 'prompt').strip(), content)

with open('frontend/src/services/api.js', 'w') as f:
    f.write(content)

print("Updated api.js")
