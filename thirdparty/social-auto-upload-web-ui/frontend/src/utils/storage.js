const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5409'

/**
 * 统一文件 URL 构建
 * @param {string} storedPath - 相对路径，如 "materials/2026/05/31/uuid.jpg"
 */
export function getFileUrl(storedPath) {
  if (!storedPath) return ''
  if (storedPath.startsWith('http')) return storedPath
  // 历史草稿的 cover_path 存的是已带接口前缀的路径（/api/materials/file/materials/...），
  // 直接补 host 即可，否则会被再拼一次前缀导致 404
  if (storedPath.startsWith('/api/')) return `${BASE_URL}${storedPath}`
  return `${BASE_URL}/api/materials/file/${storedPath}`
}
