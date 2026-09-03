import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/store/authStore'
import { Button } from '@/components/ui/Button'
import toast from 'react-hot-toast'
import { AxiosError } from 'axios'

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const loginStore = useAuthStore((s) => s.login)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await authApi.login({ username, password })
      loginStore(res.token, res.username, res.is_admin)
      toast.success('Logged in successfully')
      navigate('/')
    } catch (error) {
      if (error instanceof AxiosError) {
        toast.error(error.response?.data?.detail || 'Invalid credentials')
      } else {
        toast.error('Login failed')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-900 p-4">
      <div className="w-full max-w-md p-8 rounded-2xl bg-surface-800/80 backdrop-blur-xl border border-white/[0.08] shadow-2xl">
        <div className="mb-8 text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-brand-500/20 text-brand-400 mb-4 shadow-glow-brand">
            <span className="text-3xl">⚡</span>
          </div>
          <h1 className="text-2xl font-bold text-slate-100">Welcome Back</h1>
          <p className="text-slate-400 text-sm mt-2">Log in to your Enterprise RAG account</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Username</label>
            <input
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="input"
              placeholder="agent@demo.local"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input"
              placeholder="••••••••"
            />
          </div>
          <Button type="submit" loading={loading} className="w-full justify-center">
            Log In
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-400">
          Don't have an account?{' '}
          <Link to="/register" className="text-brand-400 hover:text-brand-300 font-medium">
            Register here
          </Link>
        </p>
      </div>
    </div>
  )
}
