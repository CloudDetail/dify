/** @jest-environment node */
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { usePathname, useSearchParams } from 'next/navigation'
import HeaderWrapper from './header-wrapper'

jest.mock('next/navigation', () => ({
  usePathname: jest.fn(),
  useSearchParams: jest.fn(),
}))

function setLocation(pathname: string, query = '') {
  jest.mocked(usePathname).mockReturnValue(pathname)
  jest.mocked(useSearchParams).mockReturnValue(new URLSearchParams(query) as ReturnType<typeof useSearchParams>)
}

it.each(['/app/check/logs/run-1', '/app/analyze/run-once'])('hides the whole navigation without a placeholder on %s', (pathname) => {
  setLocation(pathname, 'embed=alert&tenantId=tenant-a')
  const html = renderToStaticMarkup(<HeaderWrapper><nav>Workspace navigation</nav></HeaderWrapper>)
  expect(html).toBe('')
})

it.each([
  ['/apps', ''],
  ['/app/check/workflow', ''],
  ['/app/check/logs/run-1', ''],
  ['/app/analyze/run-once', ''],
  ['/apps', 'embed=alert'],
  ['/app/check/workflow', 'embed=alert'],
  ['/app/check/logs', 'embed=alert'],
  ['/app/check/logs/run-1', 'embed=other'],
])('keeps navigation on %s?%s', (pathname, query) => {
  setLocation(pathname, query)
  const html = renderToStaticMarkup(<HeaderWrapper><nav>Workspace navigation</nav></HeaderWrapper>)
  expect(html).toContain('<nav>Workspace navigation</nav>')
})

it('does not carry hidden navigation into the administrator page', () => {
  setLocation('/app/check/logs/run-1', 'embed=alert')
  const alertHtml = renderToStaticMarkup(<HeaderWrapper><nav>Workspace navigation</nav></HeaderWrapper>)
  expect(alertHtml).toBe('')
  setLocation('/apps')
  const adminHtml = renderToStaticMarkup(<HeaderWrapper><nav>Workspace navigation</nav></HeaderWrapper>)
  expect(adminHtml).toContain('<nav>Workspace navigation</nav>')
})
