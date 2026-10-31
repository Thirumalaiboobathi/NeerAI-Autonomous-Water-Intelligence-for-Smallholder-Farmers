import { createTheme } from '@mui/material/styles'

export const palette = {
  green: '#2e7d32',
  greenDark: '#1b5e20',
  leaf: '#66a96a',
  earth: '#8d6e4a',
  sand: '#f6f1e7',
  water: '#1e88e5',
  amber: '#ef9a1a',
  red: '#c62828',
}

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: palette.green, dark: palette.greenDark, contrastText: '#fff' },
    secondary: { main: palette.earth },
    info: { main: palette.water },
    warning: { main: palette.amber },
    error: { main: palette.red },
    background: { default: '#f7f5ef', paper: '#ffffff' },
    text: { primary: '#1d2b20', secondary: '#4c5a4f' },
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: '"Inter", "Noto Sans Tamil", system-ui, -apple-system, "Segoe UI", sans-serif',
    h4: { fontWeight: 700, letterSpacing: '-0.01em' },
    h5: { fontWeight: 700 },
    h6: { fontWeight: 650 },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { minHeight: 44, borderRadius: 10 } } },
    MuiIconButton: { styleOverrides: { root: { minWidth: 44, minHeight: 44 } } },
    MuiCard: { defaultProps: { variant: 'outlined' }, styleOverrides: { root: { borderColor: '#e2dccb' } } },
    MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
    MuiTab: { styleOverrides: { root: { minHeight: 48 } } },
  },
})

export const ACTION_COLOR: Record<string, 'success' | 'warning' | 'info' | 'error' | 'default' | 'primary'> = {
  IRRIGATE_NOW: 'primary',
  PRIORITIZE_FIELD: 'success',
  PARTIAL_IRRIGATION: 'warning',
  DELAY_AND_MONITOR: 'info',
  INSUFFICIENT_DATA: 'default',
}

export const CHART_COLORS = { demand: '#ef9a1a', allocated: '#2e7d32', unmet: '#c62828', available: '#1e88e5', baseline: '#8d6e4a' }
