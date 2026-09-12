import { apiClient } from './client'

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  password: string
}

export interface TokenResponse {
  token: string
  token_type: string
  username: string
  is_admin: boolean
}

export const authApi = {
  login: async (body: LoginRequest): Promise<TokenResponse> => {
    const { data } = await apiClient.post<TokenResponse>('/auth/login', body)
    return data
  },

  register: async (body: RegisterRequest): Promise<TokenResponse> => {
    const { data } = await apiClient.post<TokenResponse>('/auth/register', body)
    return data
  },
}
