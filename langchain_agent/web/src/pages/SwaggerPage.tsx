/**
 * Swagger UI page.
 * Embeds the backend's /swagger endpoint (FastAPI's auto-generated docs)
 * via iframe.
 */

import { useEffect, useState } from 'react'

export function SwaggerPage() {
  const [swaggerUrl, setSwaggerUrl] = useState<string>('')

  useEffect(() => {
    const determineSwaggerUrl = async () => {
      let apiUrl = ''

      try {
        const response = await fetch('/api/config')
        const config = await response.json()
        if (config.apiUrl) {
          apiUrl = config.apiUrl
        }
      } catch (err) {
        console.warn('Failed to fetch API config:', err)
      }

      if (!apiUrl) {
        const hostname = window.location.hostname
        if (hostname === 'localhost' || hostname === '127.0.0.1') {
          apiUrl = `http://localhost:8000`
        } else {
          apiUrl = window.location.origin
        }
      }

      setSwaggerUrl(`${apiUrl}/swagger`)
    }

    determineSwaggerUrl()
  }, [])

  if (!swaggerUrl) {
    return <div className="h-screen w-screen bg-white flex items-center justify-center">Loading...</div>
  }

  return (
    <div className="h-screen w-screen bg-white overflow-hidden">
      <iframe
        src={swaggerUrl}
        title="Swagger UI"
        className="w-full h-full border-0"
        sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
      />
    </div>
  )
}
