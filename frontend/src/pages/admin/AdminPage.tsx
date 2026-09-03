import { useState, useEffect } from 'react'
import type { HealthResponse, CacheStatsResponse } from '@/api/admin'
import { adminApi } from '@/api/admin'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { Activity, Database, Server, RefreshCw, Trash2, Cpu } from 'lucide-react'
import toast from 'react-hot-toast'

export function AdminPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [stats, setStats] = useState<CacheStatsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [clearing, setClearing] = useState(false)

  const fetchData = async () => {
    try {
      const [h, s] = await Promise.all([adminApi.health(), adminApi.cacheStats()])
      setHealth(h)
      setStats(s)
    } catch (error) {
      toast.error('Failed to load admin dashboard data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const handleClearCache = async () => {
    if (!confirm('Are you sure you want to clear all system caches?')) return
    setClearing(true)
    try {
      const res = await adminApi.cacheClear()
      toast.success(`Cleared ${res.cleared} items from cache`)
      fetchData() // Refresh stats
    } catch (error) {
      toast.error('Failed to clear cache')
    } finally {
      setClearing(false)
    }
  }

  if (loading || !health || !stats) {
    return (
      <div className="h-full flex items-center justify-center">
        <Spinner size="lg" />
      </div>
    )
  }

  const services = [
    { name: 'PostgreSQL', ok: health.services.postgres, icon: Database },
    { name: 'Qdrant', ok: health.services.qdrant, icon: Server },
    { name: 'Redis (Upstash)', ok: health.services.redis, icon: Activity },
    { name: 'OpenAI', ok: health.services.openai, icon: Cpu },
    { name: 'Tavily Search', ok: health.services.tavily, icon: Activity },
  ]

  return (
    <div className="max-w-6xl mx-auto space-y-8 pb-12 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-100 mb-2">System Dashboard</h1>
          <p className="text-slate-400">Monitor health, services, and cache performance.</p>
        </div>
        <Button variant="ghost" onClick={fetchData}>
          <RefreshCw className="w-4 h-4" />
          Refresh
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <Activity className="text-brand-400" /> System Health
            </h2>
            <Badge variant={health.status === 'ok' ? 'green' : 'red'}>
              {health.status.toUpperCase()}
            </Badge>
          </div>
          <div className="grid grid-cols-2 gap-4">
            {services.map((s) => (
              <div key={s.name} className="flex items-center gap-3 p-3 bg-surface-800 rounded-xl border border-white/[0.05]">
                <s.icon className="w-5 h-5 text-slate-400" />
                <span className="flex-1 text-sm font-medium">{s.name}</span>
                <Badge variant={s.ok ? 'green' : 'red'}>{s.ok ? 'UP' : 'DOWN'}</Badge>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <Database className="text-brand-400" /> Cache Performance
            </h2>
            <Button variant="danger" onClick={handleClearCache} loading={clearing}>
              <Trash2 className="w-4 h-4" />
              Flush Caches
            </Button>
          </div>
          
          <div className="space-y-4">
            {Object.entries(stats).map(([tier, stat]) => (
              <div key={tier} className="p-4 bg-surface-800 rounded-xl border border-white/[0.05]">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-slate-300 capitalize">{tier.replace('_', ' ')}</span>
                  <Badge variant="brand">{(stat.hit_rate * 100).toFixed(1)}% hit rate</Badge>
                </div>
                <div className="flex gap-6 text-xs text-slate-400">
                  <span>Hits: <span className="text-emerald-400 font-mono ml-1">{stat.hits}</span></span>
                  <span>Misses: <span className="text-red-400 font-mono ml-1">{stat.misses}</span></span>
                  <span>Sets: <span className="text-brand-400 font-mono ml-1">{stat.sets}</span></span>
                </div>
                {/* Progress bar */}
                <div className="mt-3 h-1.5 w-full bg-surface-900 rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-gradient-to-r from-emerald-500 to-brand-500"
                    style={{ width: `${stat.hit_rate * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
