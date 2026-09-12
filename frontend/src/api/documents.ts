import { apiClient } from './client'

export interface DocumentListItem {
  doc_id: string
  source: string
  chunk_count: number
}

export interface DocumentListResponse {
  documents: DocumentListItem[]
  total: number
}

export interface UploadResponse {
  doc_id: string
  filename: string
  chunks_indexed: number
  page_count: number | null
  message: string
}

export const documentsApi = {
  list: async (): Promise<DocumentListResponse> => {
    const { data } = await apiClient.get<DocumentListResponse>('/documents/')
    return data
  },

  upload: async (file: File, onProgress?: (pct: number) => void): Promise<UploadResponse> => {
    const form = new FormData()
    form.append('file', file)
    const { data } = await apiClient.post<UploadResponse>('/documents/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600_000, // 10 min for Docling first-run
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          onProgress(Math.round((e.loaded / e.total) * 100))
        }
      },
    })
    return data
  },

  delete: async (docId: string): Promise<{ status: string; deleted_chunks: number }> => {
    const { data } = await apiClient.delete(`/documents/${docId}`)
    return data
  },
}
