import { Routes, Route, Navigate } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { LoginPage } from '@/pages/auth/LoginPage'
import { RegisterPage } from '@/pages/auth/RegisterPage'
import { ChatPage } from '@/pages/chat/ChatPage'
import { DocumentsPage } from '@/pages/documents/DocumentsPage'
import { AdminPage } from '@/pages/admin/AdminPage'
import { HistoryPage } from '@/pages/history/HistoryPage'
import { EvalPage } from '@/pages/eval/EvalPage'
import { SystemPage } from '@/pages/system/SystemPage'
import { useAuthStore } from '@/store/authStore'
import type { ReactNode } from 'react'

function AdminRoute({ children }: { children: ReactNode }) {
  const { isAdmin } = useAuthStore()
  if (!isAdmin) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      <Route element={<AppShell />}>
        <Route path="/" element={<ChatPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/eval" element={<EvalPage />} />
        <Route path="/system" element={<SystemPage />} />
        <Route
          path="/admin"
          element={
            <AdminRoute>
              <AdminPage />
            </AdminRoute>
          }
        />
      </Route>
    </Routes>
  )
}
