import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/store/authStore'
import { Button } from '@/components/ui/Button'
import toast from 'react-hot-toast'
import { AxiosError } from 'axios'

export function RegisterPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const loginStore = useAuthStore((s) => s.login)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await authApi.register({ username, password })
      loginStore(res.token, res.username, res.is_admin)
      toast.success('Account created successfully')
      navigate('/')
    } catch (error) {
      if (error instanceof AxiosError) {
        toast.error(error.response?.data?.detail || 'Registration failed')
      } else {
        toast.error('Registration failed')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-900 p-4">
      <div className="w-full max-w-md p-8 rounded-2xl bg-surface-800/80 backdrop-blur-xl border border-white/[0.08] shadow-2xl">
        <div className="mb-8 text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-accent-500/20 text-accent-400 mb-4 shadow-glow-accent">
            <span className="text-3xl">🚀</span>
          </div>
          <h1 className="text-2xl font-bold text-slate-100">Create Account</h1>
          <p className="text-slate-400 text-sm mt-2">Join the Enterprise RAG platform</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Username</label>
            <input
              type="text"
              required
              minLength={3}
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
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input"
              placeholder="••••••••"
            />
          </div>
          <Button type="submit" loading={loading} className="w-full justify-center">
            Sign Up
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-400">
          Already have an account?{' '}
          <Link to="/login" className="text-accent-400 hover:text-accent-300 font-medium">
            Log in here
          </Link>
        </p>
      </div>
    </div>
  )
}
