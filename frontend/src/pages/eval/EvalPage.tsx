import { useState, useEffect } from 'react'
import {
  BarChart3, TrendingUp, TrendingDown, Minus,
  ChevronDown, ChevronUp, RefreshCw
} from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { api } from '@/api/client'
import { clsx } from 'clsx'

/* ── Types ────────────────────────────────────────────────────────────── */

interface RagasMetrics {
  faithfulness?: number | null
  context_precision?: number | null
  context_recall?: number | null
  answer_relevancy?: number | null
}

interface EvalRow {
  id: string
  question: string
  answer: string
  demonstrates_feature?: string
  intent?: string
  ragas_metrics?: RagasMetrics
  forbidden_check?: { passed: boolean }
  contexts?: string[]
  golden_sources?: string[]
  actual_sources?: string[]
  source_overlap?: Record<string, number>
}

interface EvalFile {
  name: string
  profile?: string
  timestamp_utc?: string
  aggregate?: {
    faithfulness: number
    context_precision: number
    context_recall: number
    answer_relevancy: number
    evaluated: number
  }
  rows?: EvalRow[]
  skipped?: unknown[]
}

/* ── Helpers ──────────────────────────────────────────────────────────── */

function fmt(v: number | null | undefined) {
  return v != null ? v.toFixed(2) : '—'
}

function rowStatus(row: EvalRow): 'pass' | 'partial' | 'fail' | 'forbidden' {
  if (!(row.forbidden_check?.passed ?? true)) return 'forbidden'
  const f = row.ragas_metrics?.faithfulness ?? 0
  const a = row.ragas_metrics?.answer_relevancy ?? 0
  const score = Math.max(f, a)
  if (score >= 0.7) return 'pass'
  if (score >= 0.4) return 'partial'
  return 'fail'
}

const STATUS_CONFIG = {
  pass: { label: '✅ Pass', cls: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' },
  partial: { label: '🟡 Partial', cls: 'text-amber-400 bg-amber-500/10 border-amber-500/30' },
  fail: { label: '❌ Fail', cls: 'text-red-400 bg-red-500/10 border-red-500/30' },
  forbidden: { label: '🚫 Forbidden', cls: 'text-orange-400 bg-orange-500/10 border-orange-500/30' },
}

function DeltaBadge({ curr, prev }: { curr?: number | null; prev?: number | null }) {
  if (curr == null || prev == null) return null
  const delta = curr - prev
  if (Math.abs(delta) < 0.005) return <Minus className="w-3.5 h-3.5 text-slate-500" />
  return delta > 0 ? (
    <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
  ) : (
    <TrendingDown className="w-3.5 h-3.5 text-red-400" />
  )
}

function MetricCell({
  label, value, prevValue,
}: {
  label: string
  value?: number | null
  prevValue?: number | null
}) {
  const delta = value != null && prevValue != null ? value - prevValue : null
  return (
    <div className="text-center">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className="text-sm font-mono font-bold text-slate-100">{fmt(value)}</p>
      {delta != null && (
        <p className={clsx('text-xs font-mono', delta >= 0 ? 'text-emerald-400' : 'text-red-400')}>
          {delta >= 0 ? '+' : ''}{delta.toFixed(2)}
        </p>
      )}
    </div>
  )
}

/* ── Drilldown ────────────────────────────────────────────────────────── */

function RowDrilldown({ row }: { row: EvalRow }) {
  const [tab, setTab] = useState<'answer' | 'contexts' | 'sources'>('answer')
  const tabs = ['answer', 'contexts', 'sources'] as const

  return (
    <div className="mt-4 pt-4 border-t border-white/[0.05] animate-fade-in">
      <div className="flex gap-2 mb-4">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              'px-3 py-1 rounded-lg text-xs font-medium capitalize transition-colors',
              tab === t
                ? 'bg-brand-500 text-white'
                : 'bg-white/5 text-slate-400 hover:bg-white/10'
            )}
          >
            {t === 'answer' ? '📝 Answer' : t === 'contexts' ? '📚 Contexts' : '🎯 Sources'}
          </button>
        ))}
      </div>

      {tab === 'answer' && (
        <div className="text-sm text-slate-300 leading-relaxed bg-white/[0.02] rounded-xl p-4 max-h-48 overflow-y-auto">
          {row.answer || <span className="text-slate-500 italic">No answer captured</span>}
        </div>
      )}

      {tab === 'contexts' && (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {(row.contexts || []).length === 0 ? (
            <p className="text-sm text-slate-500 italic">No contexts captured</p>
          ) : (
            row.contexts!.map((ctx, i) => (
              <div key={i} className="text-xs text-slate-400 bg-white/[0.02] rounded-lg p-3 leading-relaxed">
                <span className="text-brand-400 font-mono mr-2">#{i + 1}</span>
                {ctx}
              </div>
            ))
          )}
        </div>
      )}

      {tab === 'sources' && (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-slate-500 mb-2 font-semibold">Expected Sources</p>
            <ul className="space-y-1">
              {(row.golden_sources || []).map((s) => (
                <li key={s} className="text-xs text-slate-300 font-mono bg-white/[0.02] px-2 py-1 rounded">{s}</li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-xs text-slate-500 mb-2 font-semibold">Retrieved Sources</p>
            <ul className="space-y-1">
              {(row.actual_sources || []).map((s) => (
                <li key={s} className="text-xs text-slate-300 font-mono bg-white/[0.02] px-2 py-1 rounded">{s}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Main page ────────────────────────────────────────────────────────── */

export function EvalPage() {
  const [files, setFiles] = useState<string[]>([])
  const [selectedFile, setSelectedFile] = useState<string>('')
  const [compareFile, setCompareFile] = useState<string>('')
  const [data, setData] = useState<EvalFile | null>(null)
  const [compareData, setCompareData] = useState<EvalFile | null>(null)
  const [loading, setLoading] = useState(false)
  const [expandedRow, setExpandedRow] = useState<string | null>(null)
  const [filterStatus, setFilterStatus] = useState<string[]>(['pass', 'partial', 'fail', 'forbidden'])
  const [filterFeature, setFilterFeature] = useState<string>('all')

  /* Load file list */
  useEffect(() => {
    api.get('/admin/eval-files').then((res) => {
      setFiles(res.data.files || [])
      if (res.data.files?.length > 0) setSelectedFile(res.data.files[0])
    }).catch(() => {
      /* endpoint not available — show empty state */
    })
  }, [])

  /* Load selected file data */
  useEffect(() => {
    if (!selectedFile) return
    setLoading(true)
    api.get(`/admin/eval-file?name=${encodeURIComponent(selectedFile)}`).then((res) => {
      setData(res.data)
    }).catch(() => setData(null)).finally(() => setLoading(false))
  }, [selectedFile])

  /* Load compare file */
  useEffect(() => {
    if (!compareFile) { setCompareData(null); return }
    api.get(`/admin/eval-file?name=${encodeURIComponent(compareFile)}`).then((res) => {
      setCompareData(res.data)
    }).catch(() => setCompareData(null))
  }, [compareFile])

  const rows = data?.rows || []
  const agg = data?.aggregate
  const compareAgg = compareData?.aggregate

  const features = ['all', ...Array.from(new Set(rows.map((r) => r.demonstrates_feature || 'unknown')))]

  const filtered = rows.filter((r) => {
    const st = rowStatus(r)
    if (!filterStatus.includes(st)) return false
    if (filterFeature !== 'all' && (r.demonstrates_feature || 'unknown') !== filterFeature) return false
    return true
  })

  /* Compare row map */
  const compareRowsById = Object.fromEntries(
    (compareData?.rows || []).map((r) => [r.id, r])
  )

  const toggleStatus = (s: string) =>
    setFilterStatus((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s])

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-4xl font-heading font-bold text-gradient mb-2 drop-shadow-lg">Eval Dashboard</h1>
          <p className="text-slate-300 font-medium mt-1">RAGAS evaluation results — faithfulness, precision, recall, relevancy</p>
        </div>
        <Button onClick={() => setSelectedFile(selectedFile)} variant="ghost" disabled={loading}>
          {loading ? <Spinner size="sm" /> : <RefreshCw className="w-4 h-4" />}
          <span className="ml-2">Reload</span>
        </Button>
      </div>

      {/* No files */}
      {files.length === 0 && (
        <Card className="p-16 text-center">
          <BarChart3 className="w-12 h-12 text-slate-600 mx-auto mb-4" />
          <p className="text-slate-400 text-lg mb-2">No evaluation results yet</p>
          <p className="text-slate-500 text-sm mb-4">
            Run <code className="bg-white/10 px-2 py-0.5 rounded text-brand-300">make eval-baseline</code> to generate your first RAGAS report.
          </p>
          <p className="text-xs text-slate-600">Results appear in <code className="font-mono">eval/results/*.json</code></p>
        </Card>
      )}

      {files.length > 0 && (
        <>
          {/* File selectors */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-slate-400 mb-1 font-medium">📄 Latest Result File</label>
              <select
                className="input"
                value={selectedFile}
                onChange={(e) => setSelectedFile(e.target.value)}
              >
                {files.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1 font-medium">📄 Compare With (optional)</label>
              <select
                className="input"
                value={compareFile}
                onChange={(e) => setCompareFile(e.target.value)}
              >
                <option value="">— none —</option>
                {files.filter((f) => f !== selectedFile).map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Aggregate metrics */}
          {agg && (
            <Card className="p-6 border-white/[0.08] bg-surface-900/40 backdrop-blur-xl relative overflow-hidden shadow-glass">
              <div className="absolute inset-0 bg-glass-gradient opacity-20 pointer-events-none"></div>
              <div className="relative z-10">
                <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-6">Aggregate Scores</p>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-6">
                {([
                  ['Faithfulness', 'faithfulness'],
                  ['Ctx Precision', 'context_precision'],
                  ['Ctx Recall', 'context_recall'],
                  ['Ans Relevancy', 'answer_relevancy'],
                ] as [string, keyof typeof agg][]).map(([label, key]) => (
                  <div key={key} className="text-center">
                    <p className="text-xs text-slate-500 mb-1">{label}</p>
                    <p className="text-3xl font-bold font-mono text-slate-100">{fmt(agg[key] as number)}</p>
                    {compareAgg && (
                      <div className="flex items-center justify-center gap-1 mt-1">
                        <DeltaBadge curr={agg[key] as number} prev={compareAgg[key] as number} />
                        <span className={clsx(
                          'text-xs font-mono',
                          ((agg[key] as number) - (compareAgg[key] as number)) >= 0 ? 'text-emerald-400' : 'text-red-400'
                        )}>
                          {((agg[key] as number) - (compareAgg[key] as number) >= 0) ? '+' : ''}
                          {((agg[key] as number) - (compareAgg[key] as number)).toFixed(2)}
                        </span>
                      </div>
                    )}
                  </div>
                ))}
                  <div className="text-center">
                    <p className="text-xs text-slate-400 mb-1">Evaluated</p>
                    <p className="text-3xl font-bold font-mono text-slate-100">{agg.evaluated}</p>
                    <p className="text-xs text-slate-500 mt-1">{(data?.skipped || []).length} skipped</p>
                  </div>
                </div>
              </div>
            </Card>
          )}

          {/* Filters */}
          <div className="flex flex-wrap gap-3 items-center">
            <span className="text-xs text-slate-500 font-medium">Filter:</span>
            {(['pass', 'partial', 'fail', 'forbidden'] as const).map((s) => {
              const cfg = STATUS_CONFIG[s]
              return (
                <button
                  key={s}
                  onClick={() => toggleStatus(s)}
                  className={clsx(
                    'px-3 py-1 rounded-full text-xs font-medium border transition-all',
                    filterStatus.includes(s) ? cfg.cls : 'text-slate-600 bg-transparent border-white/10'
                  )}
                >
                  {cfg.label}
                </button>
              )
            })}
            <select
              className="input !py-1 !px-2 !text-xs ml-auto w-auto"
              value={filterFeature}
              onChange={(e) => setFilterFeature(e.target.value)}
            >
              {features.map((f) => (
                <option key={f} value={f}>{f === 'all' ? 'All features' : f}</option>
              ))}
            </select>
          </div>

          {/* Rows table */}
          {loading ? (
            <div className="flex justify-center py-12"><Spinner /></div>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">{filtered.length} golden questions</p>
              {filtered.map((row) => {
                const st = rowStatus(row)
                const cfg = STATUS_CONFIG[st]
                const compareRow = compareRowsById[row.id]
                const expanded = expandedRow === row.id
                return (
                  <Card
                    key={row.id}
                    className="p-5 border-white/[0.08] bg-surface-800/30 backdrop-blur-md relative overflow-hidden transition-all duration-300 hover:border-brand-500/40 hover:shadow-glow-brand cursor-pointer group"
                    onClick={() => setExpandedRow(expanded ? null : row.id)}
                  >
                    <div className="absolute inset-0 bg-gradient-to-r from-white/[0.02] to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"></div>
                    <div className="flex items-start gap-4 relative z-10">
                      {/* Status */}
                      <span className={clsx('flex-shrink-0 px-2.5 py-1 rounded-full border text-xs font-semibold', cfg.cls)}>
                        {cfg.label}
                      </span>

                      {/* Question */}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-100 line-clamp-1 mb-1">
                          {row.question}
                        </p>
                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                          {row.demonstrates_feature && (
                            <span className="text-brand-400">{row.demonstrates_feature}</span>
                          )}
                          {row.intent && <span className="capitalize">{row.intent}</span>}
                          <span className="font-mono text-slate-600">{row.id}</span>
                        </div>
                      </div>

                      {/* Metric cells */}
                      <div className="hidden md:flex gap-6 flex-shrink-0">
                        <MetricCell
                          label="Faith"
                          value={row.ragas_metrics?.faithfulness}
                          prevValue={compareRow?.ragas_metrics?.faithfulness}
                        />
                        <MetricCell
                          label="Prec"
                          value={row.ragas_metrics?.context_precision}
                          prevValue={compareRow?.ragas_metrics?.context_precision}
                        />
                        <MetricCell
                          label="Recall"
                          value={row.ragas_metrics?.context_recall}
                          prevValue={compareRow?.ragas_metrics?.context_recall}
                        />
                        <MetricCell
                          label="Rel"
                          value={row.ragas_metrics?.answer_relevancy}
                          prevValue={compareRow?.ragas_metrics?.answer_relevancy}
                        />
                      </div>

                      {/* Expand toggle */}
                      <button className="flex-shrink-0 text-slate-500 hover:text-slate-300 p-1">
                        {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </button>
                    </div>

                    {/* Expanded drilldown */}
                    {expanded && <RowDrilldown row={row} />}
                  </Card>
                )
              })}
            </div>
          )}
        </>
      )}
    </div>
  )
}
