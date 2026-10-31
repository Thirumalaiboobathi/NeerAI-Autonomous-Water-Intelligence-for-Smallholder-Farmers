import {
  AppBar,
  BottomNavigation,
  BottomNavigationAction,
  Chip,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  ToggleButton,
  ToggleButtonGroup,
  Toolbar,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import { Box, Stack, Typography } from './mui'
import AgricultureIcon from '@mui/icons-material/Agriculture'
import BarChartIcon from '@mui/icons-material/BarChart'
import ChatIcon from '@mui/icons-material/Chat'
import DashboardIcon from '@mui/icons-material/Dashboard'
import MenuIcon from '@mui/icons-material/Menu'
import OpacityIcon from '@mui/icons-material/Opacity'
import ScienceIcon from '@mui/icons-material/Science'
import SettingsIcon from '@mui/icons-material/Settings'
import TuneIcon from '@mui/icons-material/Tune'
import WaterDropIcon from '@mui/icons-material/WaterDrop'
import { useState, type ReactNode } from 'react'
import { Link as RouterLink, useLocation } from 'react-router-dom'
import { useAppState } from '../app/AppState'
import { useCurrentFarm, useHealth } from '../hooks/useApi'
import { useT } from '../i18n'

const NAV = [
  { to: '/', key: 'nav.dashboard', icon: <DashboardIcon /> },
  { to: '/farms', key: 'nav.farms', icon: <AgricultureIcon /> },
  { to: '/planner', key: 'nav.planner', icon: <TuneIcon /> },
  { to: '/scarcity', key: 'nav.scarcity', icon: <OpacityIcon /> },
  { to: '/simulator', key: 'nav.simulator', icon: <ScienceIcon /> },
  { to: '/ask', key: 'nav.ask', icon: <ChatIcon /> },
  { to: '/impact', key: 'nav.impact', icon: <BarChartIcon /> },
  { to: '/settings', key: 'nav.settings', icon: <SettingsIcon /> },
]
const BOTTOM = ['/', '/planner', '/ask', '/impact']
const WIDTH = 248

export default function Layout({ children }: { children: ReactNode }) {
  const { t, lang } = useT()
  const { setLang, setFarmId } = useAppState()
  const theme = useTheme()
  const desktop = useMediaQuery(theme.breakpoints.up('md'))
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  const health = useHealth()
  const { farm, farms } = useCurrentFarm()

  const nav = (
    <Box role="navigation" aria-label={t('nav.main')} sx={{ width: WIDTH }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ p: 2 }}>
        <WaterDropIcon color="primary" />
        <Box>
          <Typography fontWeight={800} lineHeight={1.1}>NeerAI</Typography>
          <Typography variant="caption" color="text.secondary">{t('tagline')}</Typography>
        </Box>
      </Stack>
      <Divider />
      <List>
        {NAV.map((n) => (
          <ListItemButton key={n.to} component={RouterLink} to={n.to} selected={loc.pathname === n.to} onClick={() => setOpen(false)} sx={{ minHeight: 48 }}>
            <ListItemIcon sx={{ minWidth: 38 }}>{n.icon}</ListItemIcon>
            <ListItemText primary={t(n.key)} />
          </ListItemButton>
        ))}
      </List>
    </Box>
  )

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      {desktop ? (
        <Drawer variant="permanent" sx={{ width: WIDTH, flexShrink: 0, '& .MuiDrawer-paper': { width: WIDTH, boxSizing: 'border-box' } }}>{nav}</Drawer>
      ) : (
        <Drawer open={open} onClose={() => setOpen(false)}>{nav}</Drawer>
      )}
      <Box sx={{ flexGrow: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <AppBar position="sticky" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Toolbar sx={{ gap: { xs: 0.5, sm: 1 }, px: { xs: 1, sm: 2 } }}>
            {!desktop && <IconButton edge="start" aria-label={t('nav.menu')} onClick={() => setOpen(true)}><MenuIcon /></IconButton>}
            {!desktop && <Typography fontWeight={800} color="primary">NeerAI</Typography>}
            <Box sx={{ flexGrow: 1 }} />
            {farms.length > 0 && (
              <Select size="small" value={farm?.id ?? ''} onChange={(e) => setFarmId(e.target.value)} inputProps={{ 'aria-label': t('farm.select') }}
                sx={{ maxWidth: { xs: 108, sm: 280 }, minWidth: 0, minHeight: 44 }}>
                {farms.map((f) => <MenuItem key={f.id} value={f.id}>{f.farm_name}</MenuItem>)}
              </Select>
            )}
            <ToggleButtonGroup exclusive size="small" value={lang} onChange={(_, v) => v && setLang(v)} aria-label={t('lang.toggle')}>
              <ToggleButton value="ta" sx={{ minWidth: { xs: 44, sm: 52 }, px: { xs: 1, sm: 1.5 } }}>தமிழ்</ToggleButton>
              <ToggleButton value="en" sx={{ minWidth: { xs: 40, sm: 52 }, px: { xs: 1, sm: 1.5 } }}>EN</ToggleButton>
            </ToggleButtonGroup>
            {desktop && health.data && <Chip size="small" variant="outlined" color={health.data.agent_mode === 'bedrock' ? 'success' : 'warning'}
              label={health.data.agent_mode === 'bedrock' ? 'Bedrock' : t('timeline.demo')} />}
          </Toolbar>
        </AppBar>
        <Box component="main" sx={{ p: { xs: 2, sm: 3 }, pb: { xs: 10, md: 4 }, maxWidth: 1280, width: '100%', mx: 'auto', flexGrow: 1 }}>{children}</Box>
        {!desktop && (
          <Paper elevation={3} sx={{ position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 1100 }}>
            <BottomNavigation showLabels value={BOTTOM.includes(loc.pathname) ? loc.pathname : false}>
              {NAV.filter((n) => BOTTOM.includes(n.to)).map((n) => (
                <BottomNavigationAction key={n.to} component={RouterLink} to={n.to} value={n.to} label={t(n.key)} icon={n.icon} sx={{ minWidth: 60 }} />
              ))}
            </BottomNavigation>
          </Paper>
        )}
      </Box>
    </Box>
  )
}
