import { apiClient } from './client'

export type SearchMode = 'dense' | 'sparse' | 'hybrid'

export interface QueryRequest {
  question: string
  enable_rerank?: boolean
  top_k?: number
  enable_hyde?: boolean
  search_mode?: SearchMode
  enable_crag?: boolean
  enable_self_reflective?: boolean
}

export interface RetrievedChunk {
  text: string
  source: string
  score: number
}

export interface ResponseMetadata {
  route: string
  retrieved_chunks: RetrievedChunk[]
  cache_hit: boolean
  reflection_iterations: number
  reflection_score: number | null
  refined_question: string | null
}

export interface PendingSQLBlock {
  sql: string
  query_id: string
  explanation: string
}

export interface ChatResponse {
  answer: string
  sources: string[]
  confidence: number
  pending_sql: PendingSQLBlock | null
  cache_hit: boolean
  cost_saved: string
  metadata: ResponseMetadata
}

export interface SqlExecuteRequest {
  query_id: string
  approved: boolean
}

export const queryApi = {
  ask: async (body: QueryRequest): Promise<ChatResponse> => {
    const { data } = await apiClient.post<ChatResponse>('/query', body)
    return data
  },

  executeSQL: async (body: SqlExecuteRequest): Promise<ChatResponse> => {
    const { data } = await apiClient.post<ChatResponse>('/query/sql/execute', body)
    return data
  },
}
