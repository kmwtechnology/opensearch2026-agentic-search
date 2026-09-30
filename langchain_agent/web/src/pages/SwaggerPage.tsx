/**
 * Swagger UI page.
 * Embeds the backend's /swagger endpoint (FastAPI's auto-generated docs)
 * via iframe.
 */

export function SwaggerPage() {
  // Vite dev server (:5173) talks to the native backend on :8080; anywhere else
  // (the demo container) the API is same-origin.
  const apiUrl =
    window.location.port === '5173' ? 'http://localhost:8080' : window.location.origin
  const swaggerUrl = `${apiUrl}/swagger`

  return (
    <div className="h-screen w-screen bg-white overflow-hidden flex flex-col">
      <header className="flex flex-shrink-0 items-center gap-4 border-b border-gray-200 bg-white px-5 py-3">
        <img src="/kmw-logo.svg" alt="KMW Technology" className="h-16 w-auto flex-shrink-0" />
        <div className="h-16 w-px flex-shrink-0 bg-gray-200" aria-hidden="true" />
        <span className="text-lg font-semibold text-gray-700">API Reference</span>
      </header>
      <iframe
        src={swaggerUrl}
        title="Swagger UI"
        className="w-full flex-1 min-h-0 border-0"
        sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
      />
    </div>
  )
}
