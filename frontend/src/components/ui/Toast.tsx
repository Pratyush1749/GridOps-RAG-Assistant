import { Toaster } from 'react-hot-toast'

export function ToastProvider() {
  return (
    <Toaster
      position="top-right"
      toastOptions={{
        className: 'bg-surface-800 text-slate-100 border border-white/[0.08]',
        style: {
          background: '#0f172a',
          color: '#f1f5f9',
          border: '1px solid rgba(255, 255, 255, 0.08)',
        },
        success: {
          iconTheme: {
            primary: '#059669',
            secondary: '#ecfdf5',
          },
        },
        error: {
          iconTheme: {
            primary: '#dc2626',
            secondary: '#fef2f2',
          },
        },
      }}
    />
  )
}
