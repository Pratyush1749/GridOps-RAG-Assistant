import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useDropzone } from 'react-dropzone'
import type { DocumentListItem } from '@/api/documents'
import { documentsApi } from '@/api/documents'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { UploadCloud, FileText, Trash2, AlertCircle } from 'lucide-react'
import toast from 'react-hot-toast'

export function DocumentsPage() {
  const queryClient = useQueryClient()
  const [uploadProgress, setUploadProgress] = useState(0)

  const { data, isLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: documentsApi.list,
  })

  const uploadMut = useMutation({
    mutationFn: (file: File) => documentsApi.upload(file, setUploadProgress),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      toast.success('Document uploaded and indexed successfully')
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Upload failed')
    },
    onSettled: () => setUploadProgress(0),
  })

  const deleteMut = useMutation({
    mutationFn: documentsApi.delete,
    onSuccess: (_, docId) => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      toast.success(`Deleted document ${docId}`)
    },
    onError: () => toast.error('Failed to delete document'),
  })

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      if (acceptedFiles.length === 0) return
      uploadMut.mutate(acceptedFiles[0])
    },
    [uploadMut]
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    maxFiles: 1,
    disabled: uploadMut.isPending,
  })

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-12 animate-fade-in">
      <div>
        <h1 className="text-4xl font-heading font-bold text-gradient mb-2 drop-shadow-lg">Knowledge Base</h1>
        <p className="text-slate-300 font-medium">Upload PDF documents to index them into the vector database.</p>
      </div>

      <Card className="border-dashed border-[3px] border-brand-500/30 bg-surface-800/10 backdrop-blur-3xl overflow-visible hover:border-brand-400/50 hover:shadow-glow-brand transition-all duration-300">
        <div
          {...getRootProps()}
          className={`p-16 text-center transition-colors rounded-xl cursor-pointer relative
            ${isDragActive ? 'bg-brand-500/20 shadow-inner' : 'hover:bg-white/[0.04]'}
            ${uploadMut.isPending ? 'opacity-50 cursor-not-allowed' : ''}
          `}
        >
          <div className="absolute inset-0 bg-glass-gradient opacity-30 rounded-xl pointer-events-none"></div>
          <input {...getInputProps()} />
          <UploadCloud className="w-16 h-16 mx-auto text-brand-400 mb-6 drop-shadow-[0_0_15px_rgba(34,211,238,0.6)] animate-float" />
          
          {uploadMut.isPending ? (
            <div className="space-y-4">
              <p className="text-lg font-medium text-slate-200">Processing Document...</p>
              <div className="w-64 mx-auto h-2 bg-surface-900 rounded-full overflow-hidden">
                <div 
                  className="h-full bg-brand-500 transition-all duration-300" 
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
              <p className="text-sm text-slate-400">First upload may take 1-3 minutes for model download.</p>
            </div>
          ) : (
            <>
              <p className="text-lg font-medium text-slate-200">Drag & drop a PDF here</p>
              <p className="text-sm text-slate-400 mt-2">or click to select a file</p>
            </>
          )}
        </div>
      </Card>

      <div className="space-y-4">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <FileText className="text-accent-400" />
          Indexed Documents
          {data && <Badge variant="brand">{data.total}</Badge>}
        </h2>

        {isLoading ? (
          <div className="py-12 flex justify-center"><Spinner size="lg" /></div>
        ) : !data || data.documents.length === 0 ? (
          <Card className="text-center py-12">
            <AlertCircle className="w-8 h-8 mx-auto text-slate-500 mb-3" />
            <p className="text-slate-400">No documents indexed yet.</p>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.documents.map((doc: DocumentListItem) => (
              <Card key={doc.doc_id} className="flex flex-col group card-hover border-white/[0.1] bg-surface-800/30 relative overflow-hidden">
                <div className="absolute inset-0 bg-gradient-to-br from-brand-500/10 to-accent-500/10 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"></div>
                <div className="flex items-start justify-between mb-4 relative z-10">
                  <div className="flex items-center gap-3 overflow-hidden">
                    <div className="p-3 bg-accent-500/20 rounded-xl border border-accent-500/30 shadow-glow-accent">
                      <FileText className="w-6 h-6 text-accent-300" />
                    </div>
                    <div className="truncate">
                      <h3 className="font-heading font-semibold text-lg text-slate-100 truncate drop-shadow-md" title={doc.source.split('#')[0]}>
                        {doc.source.split('#')[0]}
                      </h3>
                      <p className="text-xs text-brand-300/80 font-mono mt-1">{doc.doc_id.substring(0, 8)}</p>
                    </div>
                  </div>
                </div>
                
                <div className="mt-auto pt-4 border-t border-white/[0.05] flex items-center justify-between">
                  <Badge variant="slate">{doc.chunk_count} chunks</Badge>
                  <Button 
                    variant="ghost" 
                    className="!p-2 text-red-400 hover:bg-red-500/10 hover:text-red-300"
                    onClick={() => {
                      if (confirm(`Delete ${doc.source.split('#')[0]}?`)) {
                        deleteMut.mutate(doc.doc_id)
                      }
                    }}
                    loading={deleteMut.isPending && deleteMut.variables === doc.doc_id}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
