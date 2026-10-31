/**
 * Thin wrappers that keep the familiar layout shorthand props (alignItems, justifyContent, flexWrap, gap, display,
 * fontWeight) which MUI v9 only accepts through `sx`. Everything else passes through unchanged.
 */
import { Box as MBox, Stack as MStack, Typography as MTypography } from '@mui/material'
import type { BoxProps, StackProps, TypographyProps } from '@mui/material'
import type { ElementType } from 'react'

type Shorthand = {
  alignItems?: unknown
  justifyContent?: unknown
  flexWrap?: unknown
  gap?: unknown
  display?: unknown
  fontWeight?: unknown
  lineHeight?: unknown
}

type Sx = { sx?: unknown }

function fold<T extends Shorthand & Sx>(props: T) {
  const { alignItems, justifyContent, flexWrap, gap, display, fontWeight, lineHeight, sx, ...rest } = props
  const own = Object.fromEntries(
    Object.entries({ alignItems, justifyContent, flexWrap, gap, display, fontWeight, lineHeight }).filter(([, v]) => v !== undefined),
  )
  const merged = [own, ...(Array.isArray(sx) ? sx : sx ? [sx] : [])]
  return { rest, sx: merged as never }
}

export function Stack(props: StackProps & Shorthand) {
  const { rest, sx } = fold(props as Shorthand & Sx)
  return <MStack {...(rest as StackProps)} sx={sx} />
}

export function Box<C extends ElementType = 'div'>(props: Omit<BoxProps<C>, keyof Shorthand> & Shorthand & { component?: C }) {
  const { rest, sx } = fold(props as Shorthand & Sx)
  return <MBox {...(rest as BoxProps)} sx={sx} />
}

export function Typography<C extends ElementType = 'span'>(props: Omit<TypographyProps<C>, keyof Shorthand> & Shorthand & { component?: C }) {
  const { rest, sx } = fold(props as Shorthand & Sx)
  return <MTypography {...(rest as TypographyProps)} sx={sx} />
}
