import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Header } from '@/components/layout/Header'
import { MobileNav } from '@/components/layout/MobileNav'
import TimelinePage from '@/pages/TimelinePage'
import NotePage from '@/pages/NotePage'
import DashboardPage from '@/pages/DashboardPage'
import CalendarPage from '@/pages/CalendarPage'

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-background">
        <Header />
        <main className="mx-auto max-w-4xl px-4 pb-20 md:pb-6">
          <Routes>
            <Route path="/" element={<TimelinePage />} />
            <Route path="/note/:id" element={<NotePage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/calendar" element={<CalendarPage />} />
          </Routes>
        </main>
        <MobileNav />
      </div>
    </BrowserRouter>
  )
}
