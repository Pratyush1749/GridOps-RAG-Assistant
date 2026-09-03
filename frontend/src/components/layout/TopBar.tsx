import { useAuthStore } from '@/store/authStore'
import { Badge } from '@/components/ui/Badge'
import { User, Shield } from 'lucide-react'

export function TopBar() {
  const { username, isAdmin } = useAuthStore()

  return (
    <header className="h-16 flex items-center justify-end px-6 mx-8 mt-6 rounded-2xl bg-surface-800/30 backdrop-blur-[40px] border border-white/[0.08] sticky top-6 z-50 shadow-glass">
      <div className="flex items-center gap-4">
        {isAdmin && (
          <Badge variant="brand" className="px-3 py-1">
            <Shield className="w-3 h-3 mr-1" />
            Admin
          </Badge>
        )}
        <div className="flex items-center gap-2 text-sm text-slate-300 bg-surface-700/40 backdrop-blur-md px-4 py-2 rounded-xl border border-white/[0.08] shadow-inner">
          <User className="w-4 h-4 text-slate-400" />
          {username}
        </div>
      </div>
    </header>
  )
}
