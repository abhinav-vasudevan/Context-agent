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
  createProject: (name, prompt = '') =>
    request('/api/project/create', {
      method: 'POST',
      body: JSON.stringify({ name, prompt }),
    }),
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
  projectFollowup: (text) => 
    request('/api/project/followup', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),

  // Plan
  generatePlan: (prompt) =>
    request('/api/plan/generate', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    }),
  approvePlan: () =>
    request('/api/plan/approve', { method: 'POST' }),

  // Execution
  executeAll: () =>
    request('/api/execute/all', { method: 'POST' }),
  executeStep: (stepNumber) =>
    request(`/api/execute/step/${stepNumber}`, { method: 'POST' }),
  retryExecution: () => request('/api/execute/retry', { method: 'POST' }),
  skipExecution: () => request('/api/execute/skip', { method: 'POST' }),

  // Process
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
};
