import {
  CircularProgress,
} from '@mui/material'
import { Box } from '../components/mui'
import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import Layout from '../components/Layout'
import Dashboard from '../pages/Dashboard'

// Heavier pages are code-split (Leaflet map, simulator charts).
const Farms = lazy(() => import('../pages/Farms'))
const Planner = lazy(() => import('../pages/Planner'))
const Scarcity = lazy(() => import('../pages/Scarcity'))
const Simulator = lazy(() => import('../pages/Simulator'))
const Ask = lazy(() => import('../pages/Ask'))
const Impact = lazy(() => import('../pages/Impact'))
const Settings = lazy(() => import('../pages/Settings'))

export default function App() {
  return (
    <Layout>
      <Suspense fallback={<Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/farms" element={<Farms />} />
          <Route path="/planner" element={<Planner />} />
          <Route path="/scarcity" element={<Scarcity />} />
          <Route path="/simulator" element={<Simulator />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/impact" element={<Impact />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </Suspense>
    </Layout>
  )
}
