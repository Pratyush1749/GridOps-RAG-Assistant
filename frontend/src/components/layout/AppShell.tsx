import { Outlet, Navigate } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { useAuthStore } from '@/store/authStore'

export function AppShell() {
  const { isAuthenticated } = useAuthStore()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return (
    <div className="flex h-screen bg-transparent text-slate-100 overflow-hidden font-sans relative z-0">
      <Sidebar />
      <div className="flex-1 flex flex-col relative h-screen">
        <main className="flex-1 overflow-y-auto p-8 relative">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
