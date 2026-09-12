import { clsx } from 'clsx'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import type { ChatResponse } from '@/api/query'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Database, Zap, ArrowRight, Search, Check, X } from 'lucide-react'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  metadata?: ChatResponse
}

interface MessageBubbleProps {
  message: Message
  onApproveSql?: (queryId: string, approved: boolean) => void
}

export function MessageBubble({ message, onApproveSql }: MessageBubbleProps) {
  const isUser = message.role === 'user'

  return (
    <div className={clsx('flex w-full mb-6', isUser ? 'justify-end' : 'justify-start')}>
      <div 
        className={clsx(
          'max-w-[85%] rounded-2xl p-5 shadow-sm',
          isUser 
            ? 'bg-brand-500/20 backdrop-blur-md border border-brand-400/40 text-brand-50 rounded-tr-sm shadow-glow-brand/50 relative overflow-hidden' 
            : 'bg-surface-800/40 backdrop-blur-xl border border-white/[0.1] text-slate-200 rounded-tl-sm shadow-glass relative'
        )}
      >
        <div className="prose prose-invert prose-sm max-w-none prose-pre:bg-surface-900 prose-pre:border prose-pre:border-white/[0.05]">
          <ReactMarkdown
            components={{
              code({ node, inline, className, children, ...props }: any) {
                const match = /language-(\w+)/.exec(className || '')
                return !inline && match ? (
                  <SyntaxHighlighter
                    style={vscDarkPlus as any}
                    language={match[1]}
                    PreTag="div"
                    {...props}
                  >
                    {String(children).replace(/\n$/, '')}
                  </SyntaxHighlighter>
                ) : (
                  <code className={className} {...props}>
                    {children}
                  </code>
                )
              }
            }}
          >
            {message.content}
          </ReactMarkdown>
        </div>

        {/* Assistant Metadata Footer */}
        {!isUser && message.metadata && (
          <div className="mt-4 pt-4 border-t border-white/[0.05] flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="accent" className="text-[10px]">
                <ArrowRight className="w-3 h-3 mr-1" />
                {message.metadata.metadata.route.toUpperCase()}
              </Badge>
              
              {message.metadata.cache_hit && (
                <Badge variant="green" className="text-[10px]">
                  <Zap className="w-3 h-3 mr-1" />
                  CACHE HIT ({message.metadata.cost_saved})
                </Badge>
              )}

              {message.metadata.confidence > 0 && (
                <Badge variant={message.metadata.confidence > 0.8 ? 'green' : 'yellow'} className="text-[10px]">
                  Confidence: {(message.metadata.confidence * 100).toFixed(0)}%
                </Badge>
              )}
            </div>

            {/* Pending SQL Block */}
            {message.metadata.pending_sql && (
              <div className="mt-2 bg-surface-900 border border-amber-500/30 rounded-xl p-4">
                <div className="flex items-center gap-2 text-amber-400 mb-2 font-medium text-sm">
                  <Database className="w-4 h-4" />
                  SQL Execution Approval Required
                </div>
                <p className="text-xs text-slate-400 mb-3">{message.metadata.pending_sql.explanation}</p>
                <div className="code-block bg-black/50 mb-4">
                  <code>{message.metadata.pending_sql.sql}</code>
                </div>
                <div className="flex gap-2">
                  <Button 
                    variant="primary" 
                    className="!py-1.5 !px-3"
                    onClick={() => onApproveSql?.(message.metadata!.pending_sql!.query_id, true)}
                  >
                    <Check className="w-3 h-3" /> Approve & Execute
                  </Button>
                  <Button 
                    variant="danger" 
                    className="!py-1.5 !px-3"
                    onClick={() => onApproveSql?.(message.metadata!.pending_sql!.query_id, false)}
                  >
                    <X className="w-3 h-3" /> Reject
                  </Button>
                </div>
              </div>
            )}

            {/* Sources */}
            {message.metadata.sources && message.metadata.sources.length > 0 && (
              <div className="mt-2 text-xs text-slate-400">
                <div className="font-medium text-slate-300 flex items-center gap-1 mb-1.5">
                  <Search className="w-3 h-3" /> Sources used:
                </div>
                <ul className="list-disc list-inside space-y-0.5 ml-1">
                  {message.metadata.sources.map((src, i) => (
                    <li key={i} className="truncate" title={src}>{src.split('#')[0]}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
