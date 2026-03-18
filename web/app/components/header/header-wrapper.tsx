'use client'
import { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import s from './index.module.css'
import classNames from '@/utils/classnames'

type HeaderWrapperProps = {
  children: React.ReactNode
}

const HeaderWrapper = ({
  children,
}: HeaderWrapperProps) => {
  const pathname = usePathname()
  const isBordered = ['/apps', '/datasets', '/datasets/create', '/tools'].includes(pathname)

  const [hideHeader, setHideHeader] = useState(false)

  useEffect(() => {
    if (typeof window !== 'undefined') {
      if (localStorage.getItem('hideHeader') === 'true')
        setHideHeader(true)
    }
  }, [])

  if (hideHeader)
    return null

  return (
    <div className={classNames(
      'sticky top-0 left-0 right-0 z-30 flex flex-col grow-0 shrink-0 basis-auto min-h-[56px]',
      s.header,
      isBordered ? 'border-b border-divider-regular' : '',
    )}
    >
      {children}
    </div>
  )
}
export default HeaderWrapper
