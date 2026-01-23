import { Sidebar } from '@/components/Sidebar'
import { Hero } from '@/components/Hero'
import { Content } from '@/components/Content'

export default function Home() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 ml-64">
        <Hero />
        <Content />
      </main>
    </div>
  )
}
