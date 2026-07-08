/**
 * API service for communicating with the Context Agent backend.
 */

const API_BASE = 'http://127.0.0.1:8088';

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Request failed: ${response.status}`);
  }

  return response.json();
}

export const api = {
  // Health & Settings
  health: () => request('/api/health'),
  updateModel: (modelName) =>
    request('/api/settings/model', {
      method: 'POST',
      body: JSON.stringify({ model_name: modelName }),
    }),

  // Projects
  listProjects: () => request('/api/projects'),
  createProject: (name, prompt = '', mode = 'build', file = null) => {
    const formData = new FormData();
    formData.append('name', name);
    formData.append('prompt', prompt);
    formData.append('mode', mode);
    if (file) {
      formData.append('file', file);
    }
    return fetch(`${API_BASE}/api/project/create`, {
      method: 'POST',
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail || `Request failed: ${res.status}`);
      }
      return res.json();
    });
  },
  loadProject: (workspacePath) =>
    request('/api/project/load', {
      method: 'POST',
      body: JSON.stringify({ workspace_path: workspacePath }),
    }),
  ingestCodebase: (name, path) =>
    request('/api/project/ingest', {
      method: 'POST',
      body: JSON.stringify({ name, path }),
    }),
  getProjectState: () => request('/api/project/state'),
  projectFollowup: (text, files = []) => {
    const formData = new FormData();
    formData.append('text', text);
    if (files) {
      files.forEach(f => formData.append('files', f));
    }
    
    return fetch(`${API_BASE}/api/project/followup`, {
      method: 'POST',
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail || `Request failed: ${res.status}`);
      }
      return res.json();
    });
  },

  // Plan
  generatePlan: (prompt, files = []) => {
    const formData = new FormData();
    formData.append('prompt', prompt);
    if (files) {
      files.forEach(f => formData.append('files', f));
    }
    
    return fetch(`${API_BASE}/api/plan/generate`, {
      method: 'POST',
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail || `Request failed: ${res.status}`);
      }
      return res.json();
    });
  },
  approvePlan: () =>
    request('/api/plan/approve', { method: 'POST' }),

  // Execution
  executeAll: () =>
    request('/api/execute/all', { method: 'POST' }),
  executeStep: (stepNumber) =>
    request(`/api/execute/step/${stepNumber}`, { method: 'POST' }),
  retryExecution: (stepNumber = null) => 
    request('/api/execute/retry', { 
      method: 'POST',
      body: stepNumber !== null ? JSON.stringify({ step_number: stepNumber }) : undefined
    }),
  skipExecution: () => request('/api/execute/skip', { method: 'POST' }),

  // Process
  pauseExecution: () => request('/api/pause', { method: 'POST' }),
  resumeExecution: () => request('/api/resume', { method: 'POST' }),
  sendInput: (text) =>
    request('/api/process/input', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  killProcess: () =>
    request('/api/process/kill', { method: 'POST' }),

  // Permission
  respondPermission: (granted) =>
    request('/api/permission/respond', {
      method: 'POST',
      body: JSON.stringify({ granted }),
    }),

  // Files
  getFile: (filePath) => request(`/api/file/${filePath}`),
  listFiles: () => request('/api/files'),

  // Documents
  ingestDocument: (file, docId) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('doc_id', docId);

    return fetch(`${API_BASE}/api/documents/ingest`, {
      method: 'POST',
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(error.detail || `Request failed: ${res.status}`);
      }
      return res.json();
    });
  },

  consolidateDocuments: () => request('/api/documents/consolidate', { method: 'POST' }),
};
