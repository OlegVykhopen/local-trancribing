import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import { MotionConfig } from 'motion/react'
import { Layout } from './components/Layout'
import { TranscriptsView } from './views/TranscriptsView'
import { DownloadView } from './views/DownloadView'
import { TranscribeView } from './views/TranscribeView'
import { JobView } from './views/JobView'

function App() {
  return (
    <MotionConfig reducedMotion="user">
      <HashRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Navigate to="/files" replace />} />
            <Route path="/download" element={<DownloadView />} />
            <Route path="/files" element={<TranscribeView />} />
            <Route path="/transcripts" element={<TranscriptsView />} />
            {/* Old bookmark; a redirect drops router state, so in-app links go to /files directly. */}
            <Route path="/transcribe" element={<Navigate to="/files" replace />} />
            <Route path="/job/:id" element={<JobView />} />
            <Route path="*" element={<Navigate to="/files" replace />} />
          </Routes>
        </Layout>
      </HashRouter>
    </MotionConfig>
  )
}

export default App
