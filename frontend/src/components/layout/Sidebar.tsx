import { FileText, MessageSquare, ShieldAlert, LogOut, Clock, BarChart3, Activity } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { clsx } from 'clsx'

export function Sidebar() {
  const { isAdmin, logout, username } = useAuthStore()

  const navLinks = [
    { name: 'Chat', to: '/', icon: MessageSquare, exact: true },
    { name: 'Documents', to: '/documents', icon: FileText },
    { name: 'History', to: '/history', icon: Clock },
    { name: 'Eval Dashboard', to: '/eval', icon: BarChart3 },
    { name: 'System Status', to: '/system', icon: Activity },
  ]

  if (isAdmin) {
    navLinks.push({ name: 'Admin', to: '/admin', icon: ShieldAlert })
  }

  return (
    <aside className="w-72 bg-surface-900/40 border-r border-white/[0.08] shadow-[5px_0_30px_rgba(0,0,0,0.5)] h-screen flex flex-col backdrop-blur-[40px] relative z-10">
      <div className="p-8">
        <h1 className="text-2xl font-heading font-bold text-gradient flex items-center gap-3 drop-shadow-lg mb-1">
          <span className="text-3xl drop-shadow-[0_0_10px_rgba(0,180,216,0.8)] animate-pulse-slow">⚡</span> Enterprise RAG
        </h1>
        <p className="text-[10px] uppercase tracking-[0.2em] font-mono text-slate-500 font-semibold ml-10">
          GridOps Edition
        </p>
      </div>

      <nav className="flex-1 px-4 space-y-2 mt-4">
        {navLinks.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.exact}
            className={({ isActive }) =>
              clsx('nav-item', isActive && 'active')
            }
          >
            <link.icon className="w-5 h-5" />
            {link.name}
          </NavLink>
        ))}
      </nav>

      <div className="p-4 border-t border-white/[0.05]">
        {username && (
          <p className="text-xs text-slate-500 mb-3 px-2 truncate">
            Signed in as <span className="text-slate-300">{username}</span>
          </p>
        )}
        <button
          onClick={logout}
          className="nav-item w-full !text-red-400 hover:!text-red-300 hover:!bg-red-500/10"
        >
          <LogOut className="w-5 h-5" />
          Logout
        </button>
      </div>
    </aside>
  )
}
