import { useState } from 'react'
import { Clock, Zap, Brain, Globe, RotateCcw, Trash2 } from 'lucide-react'
import { clsx } from 'clsx'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { useNavigate } from 'react-router-dom'

interface HistoryItem {
  id: string
  question: string
  route: string
  confidence: number
  cache_hit: boolean
  timestamp: string
  search_mode?: string
  features?: string[]
}

const ROUTE_COLORS: Record<string, string> = {
  rag: 'text-purple-400 bg-purple-500/10 border-purple-500/30',
  sql: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
  hybrid: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
}

const ROUTE_ICONS: Record<string, typeof Brain> = {
  rag: Brain,
  sql: Globe,
  hybrid: Zap,
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 80 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#ef4444'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-xs font-mono text-slate-400 w-8 text-right">{pct}%</span>
    </div>
  )
}

export function HistoryPage() {
  const navigate = useNavigate()
  const [history, setHistory] = useState<HistoryItem[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('query_history') || '[]')
    } catch {
      return []
    }
  })

  const clearHistory = () => {
    localStorage.removeItem('query_history')
    setHistory([])
  }

  const rerunQuestion = (q: string) => {
    sessionStorage.setItem('prefill_question', q)
    navigate('/')
  }

  const routeStats = history.reduce(
    (acc, h) => {
      acc[h.route] = (acc[h.route] || 0) + 1
      return acc
    },
    {} as Record<string, number>
  )

  const cacheHits = history.filter((h) => h.cache_hit).length
  const avgConf =
    history.length > 0
      ? history.reduce((s, h) => s + h.confidence, 0) / history.length
      : 0

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-12">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-4xl font-heading font-bold text-gradient mb-2 drop-shadow-lg">Query History</h1>
          <p className="text-slate-300 font-medium mt-1">
            Your last {history.length} queries this session
          </p>
        </div>
        {history.length > 0 && (
          <Button variant="ghost" onClick={clearHistory} className="!text-red-400 hover:!text-red-300">
            <Trash2 className="w-4 h-4 mr-2" /> Clear History
          </Button>
        )}
      </div>

      {/* Stats row */}
      {history.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Queries', value: history.length, icon: Clock },
            { label: 'Avg Confidence', value: `${Math.round(avgConf * 100)}%`, icon: Brain },
            { label: 'Cache Hits', value: cacheHits, icon: Zap },
            {
              label: 'Routes',
              value: Object.keys(routeStats).join(' · ') || '—',
              icon: Globe,
            },
          ].map((stat) => (
            <Card key={stat.label} className="p-4 border-white/[0.08] bg-surface-900/40 backdrop-blur-xl relative overflow-hidden">
              <div className="absolute inset-0 bg-glass-gradient opacity-20 pointer-events-none"></div>
              <div className="flex items-center gap-3 relative z-10">
                <div className="p-2.5 rounded-xl bg-brand-500/10 shadow-inner">
                  <stat.icon className="w-6 h-6 text-brand-400 drop-shadow-[0_0_8px_rgba(34,211,238,0.5)]" />
                </div>
                <div>
                  <p className="text-xs text-slate-400 uppercase tracking-wider font-semibold">{stat.label}</p>
                  <p className="text-2xl font-bold text-slate-100 mt-0.5">{stat.value}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* History list */}
      {history.length === 0 ? (
        <Card className="p-16 text-center">
          <Clock className="w-12 h-12 text-slate-600 mx-auto mb-4" />
          <p className="text-slate-400 text-lg">No query history yet</p>
          <p className="text-slate-500 text-sm mt-1">
            Your queries will appear here after you use the Chat page.
          </p>
          <Button className="mt-6" onClick={() => navigate('/')}>
            Start Chatting
          </Button>
        </Card>
      ) : (
        <div className="space-y-3">
          {[...history].reverse().map((item) => {
            const RouteIcon = ROUTE_ICONS[item.route] || Brain
            return (
              <Card
                key={item.id}
                className="p-5 border-white/[0.08] bg-surface-800/30 backdrop-blur-md relative overflow-hidden transition-all duration-300 hover:border-brand-500/40 hover:shadow-glow-brand hover:-translate-y-0.5 group"
              >
                <div className="absolute inset-0 bg-gradient-to-r from-white/[0.02] to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"></div>
                <div className="flex items-start gap-4 relative z-10">
                  {/* Route badge */}
                  <div
                    className={clsx(
                      'flex-shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-semibold uppercase tracking-wide mt-0.5',
                      ROUTE_COLORS[item.route] || ROUTE_COLORS.rag
                    )}
                  >
                    <RouteIcon className="w-3.5 h-3.5" />
                    {item.route}
                  </div>

                  {/* Question & details */}
                  <div className="flex-1 min-w-0">
                    <p className="text-slate-100 font-medium leading-snug mb-2 line-clamp-2">
                      {item.question}
                    </p>
                    <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                      {item.timestamp && (
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {new Date(item.timestamp).toLocaleTimeString()}
                        </span>
                      )}
                      {item.search_mode && (
                        <span className="capitalize">{item.search_mode} search</span>
                      )}
                      {item.cache_hit && (
                        <span className="text-emerald-400 flex items-center gap-1">
                          <Zap className="w-3 h-3" /> Cache hit
                        </span>
                      )}
                      {item.features && item.features.length > 0 && (
                        <span>{item.features.join(' · ')}</span>
                      )}
                    </div>
                    <div className="mt-3 w-48">
                      <p className="text-xs text-slate-500 mb-1">Confidence</p>
                      <ConfidenceBar value={item.confidence} />
                    </div>
                  </div>

                  {/* Re-run button */}
                  <button
                    onClick={() => rerunQuestion(item.question)}
                    className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-2 hover:bg-brand-500/10 rounded-lg text-brand-400"
                    title="Re-run this query"
                  >
                    <RotateCcw className="w-4 h-4" />
                  </button>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
