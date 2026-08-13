import axios from 'axios';

const api = axios.create({
  baseURL: '',
  headers: { 'Content-Type': 'application/json' },
});

// Providers
export const getHotProviders = () => api.get('/api/providers/hot-providers');
export const getProviders = () => api.get('/api/providers');
export const createProvider = (data: any) => api.post('/api/providers', data);
export const updateProvider = (id: number, data: any) => api.put('/api/providers/' + id, data);
export const deleteProvider = (id: number) => api.delete('/api/providers/' + id);

// API Keys
export const getKeys = (providerId: number) => api.get('/api/providers/' + providerId + '/keys');
export const createKey = (data: any) => api.post('/api/api-keys', data);
export const updateKey = (id: number, data: any) => api.put('/api/api-keys/' + id, data);
export const deleteKey = (id: number) => api.delete('/api/api-keys/' + id);
export const testKey = (id: number) => api.post('/api/api-keys/' + id + '/test');
export const testAllKeys = (providerId: number) => api.post('/api/providers/' + providerId + '/keys/test-all');
export const deleteInvalidKeys = (providerId: number) => api.delete('/api/providers/' + providerId + '/keys/invalid');

// Models
export const getModels = (providerId: number) => api.get('/api/providers/' + providerId + '/models');
export const createModel = (data: any) => api.post('/api/models', data);
export const updateModel = (id: number, data: any) => api.put('/api/models/' + id, data);
export const deleteModel = (id: number) => api.delete('/api/models/' + id);
export const fetchModels = (providerId: number) => api.post('/api/models/fetch/' + providerId);
export const syncModels = (providerId: number) => api.post('/api/models/sync/' + providerId);
export const testAllModels = (providerId: number) => api.post('/api/providers/' + providerId + '/models/test-all');
export const deleteInvalidModels = (providerId: number) => api.delete('/api/providers/' + providerId + '/models/invalid');
export const clearModels = (providerId: number) => api.delete('/api/providers/' + providerId + '/models');

// Strategies
export const getStrategies = () => api.get('/api/strategies');
export const createStrategy = (data: any) => api.post('/api/strategies', data);
export const updateStrategy = (id: number, data: any) => api.put('/api/strategies/' + id, data);
export const deleteStrategy = (id: number) => api.delete('/api/strategies/' + id);
export const addRule = (strategyId: number, data: any) => api.post('/api/strategies/' + strategyId + '/rules', data);
export const updateRule = (ruleId: number, data: any) => api.put('/api/strategies/rules/' + ruleId, data);
export const deleteRule = (ruleId: number) => api.delete('/api/strategies/rules/' + ruleId);
export const testStrategy = (id: number) => api.post('/api/strategies/' + id + '/test');

// Logs
export const getLogs = (params: any) => api.get('/api/logs', { params });

// Dashboard
export const getDashboardStats = () => api.get('/api/dashboard/stats');
export const clearTodayStats = () => api.post('/api/dashboard/clear-today');

// Health
export const getHealth = () => api.get('/api/health');

// Icons
export const searchIcons = (keyword: string, page?: number, engine?: string) => api.post('/api/icons/search', { keyword, page: page || 0, count: 9, engine: engine || 'baidu' });
export const saveIcon = (url: string, providerId: number) => api.post('/api/icons/save', { url, provider_id: providerId });

// Backup/Restore
export const getBackupConfig = () => api.get('/api/backup/config');
export const updateBackupConfig = (data: any) => api.put('/api/backup/config', data);
export const createBackup = () => api.post('/api/backup/create');
export const listBackups = () => api.get('/api/backup/list');
export const restoreLocalBackup = (filename: string) => api.post('/api/backup/restore-local?filename=' + encodeURIComponent(filename));
export const deleteBackup = (filename: string) => api.delete('/api/backup/' + encodeURIComponent(filename));
export const downloadBackupUrl = (filename: string) => '/api/backup/download/' + encodeURIComponent(filename);

// App Settings
export const getSettings = () => api.get("/api/settings");
export const updateSettings = (data: any) => api.put("/api/settings", data);
export const getLanIp = () => api.get("/api/settings/lan-ip");

// Conversations
export const getConversations = () => api.get('/api/conversations');
export const createConversation = (data: any) => api.post('/api/conversations', data);
export const updateConversation = (id: number, data: any) => api.put('/api/conversations/' + id, data);
export const deleteConversation = (id: number) => api.delete('/api/conversations/' + id);


// Image Generation
export const generateImage = (data: any) => api.post('/v1/images/generations', data);

// TTS (Text-to-Speech)
export const generateSpeech = async (data: any): Promise<Blob> => {
  const resp = await fetch('/v1/audio/speech', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: { message: resp.statusText } }));
    throw new Error(err.error?.detail || err.error?.message || 'TTS request failed');
  }
  return resp.blob();
};

// Video Generation
export const createVideo = (data: any) => api.post('/v1/videos', data);
export const getVideoTask = (taskId: string, providerId: number) =>
  api.get('/v1/videos/' + taskId + '?_provider_id=' + providerId);
export default api;
