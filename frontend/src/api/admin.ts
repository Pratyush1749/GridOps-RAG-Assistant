import { apiClient } from './client'

export interface ServiceStatus {
  postgres: boolean
  qdrant: boolean
  redis: boolean
  openai: boolean
  tavily: boolean
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  services: ServiceStatus
}

export interface CacheTierStats {
  hits: number
  misses: number
  sets: number
  hit_rate: number
}

export interface CacheStatsResponse {
  embedding: CacheTierStats
  rag: CacheTierStats
  sql_gen: CacheTierStats
  sql_result: CacheTierStats
  intent_router: CacheTierStats
}

export const adminApi = {
  health: async (): Promise<HealthResponse> => {
    const { data } = await apiClient.get<HealthResponse>('/admin/health')
    return data
  },

  cacheStats: async (): Promise<CacheStatsResponse> => {
    const { data } = await apiClient.get<CacheStatsResponse>('/admin/cache/stats')
    return data
  },

  cacheClear: async (): Promise<{ status: string; cleared: number }> => {
    const { data } = await apiClient.post('/admin/cache/clear')
    return data
  },
}
