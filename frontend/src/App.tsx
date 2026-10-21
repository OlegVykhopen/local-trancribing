import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import { MotionConfig } from 'motion/react'
import { Layout } from './components/Layout'
import { FilesView } from './views/FilesView'
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
            <Route path="/files" element={<FilesView />} />
            <Route path="/download" element={<DownloadView />} />
            <Route path="/transcribe" element={<TranscribeView />} />
            <Route path="/job/:id" element={<JobView />} />
            <Route path="*" element={<Navigate to="/files" replace />} />
          </Routes>
        </Layout>
      </HashRouter>
    </MotionConfig>
  )
}

export default App
