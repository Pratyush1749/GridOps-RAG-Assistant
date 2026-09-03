import { useState, useEffect } from 'react'
import {
  Activity, Server, Database, Zap, CheckCircle2, XCircle,
  AlertCircle, RefreshCw, Cpu, Globe
} from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { api } from '@/api/client'
import { clsx } from 'clsx'

interface ServiceStatus {
  status: 'ok' | 'degraded' | 'error' | 'unknown'
  latency_ms?: number
  message?: string
}

interface HealthData {
  status: string
  postgres?: ServiceStatus
  qdrant?: ServiceStatus
  redis?: ServiceStatus
  openai?: ServiceStatus
}

interface PipelineFeature {
  id: string
  label: string
  description: string
  icon: string
  active: boolean
}

const PIPELINE_FEATURES: PipelineFeature[] = [
  { id: 'dense', label: 'Dense Search', description: 'Semantic vector similarity (OpenAI embeddings)', icon: '🧠', active: true },
  { id: 'sparse', label: 'Sparse Search', description: 'BM25 keyword retrieval for camelCase tokens', icon: '📝', active: true },
  { id: 'hybrid', label: 'Hybrid RRF', description: 'Reciprocal Rank Fusion combining dense + sparse', icon: '⚡', active: true },
  { id: 'rerank', label: 'Cross-Encoder Reranking', description: 'MS-MARCO MiniLM reranks top-K chunks 100×', icon: '🎯', active: true },
  { id: 'hyde', label: 'HyDE', description: 'Hypothetical Document Embeddings bridge vocab gaps', icon: '🔮', active: true },
  { id: 'crag', label: 'CRAG', description: 'Corrective RAG grades relevance + Tavily web fallback', icon: '🌐', active: true },
  { id: 'self_rag', label: 'Self-RAG', description: 'Reflection loop refines vague queries (max 2 retries)', icon: '🔄', active: true },
  { id: 'text2sql', label: 'Text2SQL', description: 'NL → SQL with Vanna + human approval gate', icon: '🗄️', active: true },
  { id: 'cache', label: 'Semantic Cache', description: 'Upstash Redis caches embeddings + RAG responses', icon: '💾', active: true },
  { id: 'security', label: 'LLM-Guard Security', description: 'Prompt injection & toxicity scan on every request', icon: '🛡️', active: true },
  { id: 'rate_limit', label: 'Rate Limiting', description: 'Per-user sliding window + daily token budget', icon: '⏱️', active: true },
  { id: 'spotlighting', label: 'Spotlighting', description: 'Marks retrieved context to resist prompt injection', icon: '🔦', active: true },
]

function StatusIcon({ status }: { status: string }) {
  if (status === 'ok') return <CheckCircle2 className="w-5 h-5 text-emerald-400" />
  if (status === 'degraded') return <AlertCircle className="w-5 h-5 text-amber-400" />
  return <XCircle className="w-5 h-5 text-red-400" />
}

function ServiceCard({
  name, icon: Icon, data,
}: {
  name: string
  icon: typeof Server
  data?: ServiceStatus
}) {
  const status = data?.status || 'unknown'
  const borderColor =
    status === 'ok'
      ? 'border-emerald-500/30'
      : status === 'degraded'
      ? 'border-amber-500/30'
      : 'border-red-500/30'

  return (
    <Card className={clsx('p-5 border relative overflow-hidden backdrop-blur-2xl transition-all duration-300 hover:-translate-y-1 hover:shadow-glow-brand bg-surface-800/20', borderColor)}>
      <div className="absolute inset-0 bg-glass-gradient opacity-30 pointer-events-none"></div>
      <div className="flex items-center gap-3 mb-3">
        <div className="w-9 h-9 rounded-lg bg-white/5 flex items-center justify-center">
          <Icon className="w-5 h-5 text-brand-400" />
        </div>
        <div className="flex-1">
          <p className="font-semibold text-slate-100 text-sm">{name}</p>
          <p className="text-xs text-slate-500 capitalize">{status}</p>
        </div>
        <StatusIcon status={status} />
      </div>
      {data?.latency_ms !== undefined && (
        <p className="text-xs text-slate-500">
          Latency: <span className="text-slate-300 font-mono">{data.latency_ms}ms</span>
        </p>
      )}
      {data?.message && (
        <p className="text-xs text-slate-500 mt-1 truncate">{data.message}</p>
      )}
    </Card>
  )
}

export function SystemPage() {
  const [health, setHealth] = useState<HealthData | null>(null)
  const [loading, setLoading] = useState(false)
  const [lastPing, setLastPing] = useState<Date | null>(null)

  const fetchHealth = async () => {
    setLoading(true)
    try {
      const res = await api.get('/admin/health')
      setHealth(res.data)
      setLastPing(new Date())
    } catch {
      setHealth({ status: 'error' })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchHealth()
  }, [])

  const overallOk = health?.status === 'ok'

  return (
    <div className="max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-4xl font-heading font-bold text-gradient mb-2 drop-shadow-lg">System Status</h1>
          <p className="text-slate-400 mt-1">
            Live health of all backend services and the RAG pipeline
          </p>
        </div>
        <Button onClick={fetchHealth} disabled={loading} variant="ghost">
          {loading ? <Spinner size="sm" /> : <RefreshCw className="w-4 h-4" />}
          <span className="ml-2">Refresh</span>
        </Button>
      </div>

      {/* Overall status banner */}
      {health && (
        <Card className={clsx(
          'p-6 border flex items-center gap-5 relative overflow-hidden backdrop-blur-3xl shadow-glass',
          overallOk ? 'border-emerald-500/40 bg-emerald-900/20 shadow-[0_0_30px_rgba(16,185,129,0.15)]' : 'border-red-500/40 bg-red-900/20 shadow-[0_0_30px_rgba(239,68,68,0.15)]'
        )}>
          <div className="absolute inset-0 bg-glass-gradient opacity-30 pointer-events-none"></div>
          <div className={clsx(
            'w-14 h-14 rounded-2xl flex items-center justify-center relative z-10 shadow-glass-inset',
            overallOk ? 'bg-emerald-500/20 shadow-glow-brand/50' : 'bg-red-500/20'
          )}>
            <Activity className={clsx('w-7 h-7', overallOk ? 'text-emerald-400 drop-shadow-[0_0_10px_rgba(52,211,153,0.8)]' : 'text-red-400 drop-shadow-[0_0_10px_rgba(248,113,113,0.8)]')} />
          </div>
          <div className="relative z-10">
            <p className={clsx('text-lg font-bold', overallOk ? 'text-emerald-400' : 'text-red-400')}>
              {overallOk ? '✓ All Systems Operational' : '⚠ System Degraded'}
            </p>
            {lastPing && (
              <p className="text-xs text-slate-500 mt-0.5">
                Last checked: {lastPing.toLocaleTimeString()}
              </p>
            )}
          </div>
        </Card>
      )}

      {/* Service status grid */}
      <div>
        <h2 className="text-lg font-semibold text-slate-200 mb-4">Infrastructure Services</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <ServiceCard name="PostgreSQL" icon={Database} data={health?.postgres} />
          <ServiceCard name="Qdrant Vector DB" icon={Server} data={health?.qdrant} />
          <ServiceCard name="Redis Cache" icon={Zap} data={health?.redis} />
          <ServiceCard name="OpenAI API" icon={Cpu} data={health?.openai} />
        </div>
      </div>

      {/* Pipeline features */}
      <div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">RAG Pipeline Features</h2>
        <p className="text-sm text-slate-400 mb-4">
          Every feature implemented in this enterprise-grade pipeline:
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {PIPELINE_FEATURES.map((feat) => (
            <Card key={feat.id} className="p-4 border-white/[0.08] bg-surface-900/40 backdrop-blur-xl relative overflow-hidden hover:border-brand-500/40 hover:shadow-glow-brand transition-all duration-300 hover:-translate-y-1">
              <div className="absolute inset-0 bg-gradient-to-br from-brand-500/5 to-accent-500/5 opacity-0 hover:opacity-100 transition-opacity duration-300 pointer-events-none"></div>
              <div className="flex items-start gap-3 relative z-10">
                <span className="text-2xl mt-0.5">{feat.icon}</span>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <p className="text-sm font-semibold text-slate-100">{feat.label}</p>
                    <span className="flex-shrink-0 w-2 h-2 rounded-full bg-emerald-400" />
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed">{feat.description}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </div>

      {/* Architecture summary */}
      <Card className="p-6">
        <h2 className="text-lg font-semibold text-slate-200 mb-4 flex items-center gap-2">
          <Globe className="w-5 h-5 text-brand-400" />
          Architecture Overview
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm">
          <div>
            <p className="text-xs font-semibold text-brand-400 uppercase tracking-wider mb-2">Frontend</p>
            <ul className="space-y-1 text-slate-400">
              <li>React 19 + TypeScript + Vite</li>
              <li>TailwindCSS + Zustand</li>
              <li>TanStack Query for data fetching</li>
              <li>react-dropzone for doc upload</li>
              <li>react-markdown for answer rendering</li>
            </ul>
          </div>
          <div>
            <p className="text-xs font-semibold text-brand-400 uppercase tracking-wider mb-2">Backend</p>
            <ul className="space-y-1 text-slate-400">
              <li>FastAPI + Python 3.12</li>
              <li>LangGraph stateful pipeline</li>
              <li>psycopg3 async pool</li>
              <li>PostgreSQL 16 (checkpoint store)</li>
              <li>Qdrant v1.17 vector DB</li>
            </ul>
          </div>
          <div>
            <p className="text-xs font-semibold text-brand-400 uppercase tracking-wider mb-2">AI / Models</p>
            <ul className="space-y-1 text-slate-400">
              <li>OpenAI GPT-4o (answers + routing)</li>
              <li>text-embedding-3-small</li>
              <li>MS-MARCO MiniLM cross-encoder</li>
              <li>LLM-Guard (security scanning)</li>
              <li>Vanna (Text2SQL)</li>
            </ul>
          </div>
        </div>
      </Card>
    </div>
  )
}
