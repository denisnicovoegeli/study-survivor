# Dashboard (web/)

Vite + React 19. Früher ein Hermes-Plugin, jetzt eine eigenständige App, die FastAPI (`uv run study serve`) unter `/dashboard-plugins/studium/dist/` ausliefert. Die API liegt weiterhin unter `/api/plugins/studium/`.

```bash
npm install
npm run build   # nach web/dist, danach http://localhost:8765
npm run dev     # Entwicklung mit Proxy auf localhost:8765
```

Chat: [src/chat/ChatPanel.jsx](src/chat/ChatPanel.jsx) mit SSE-Client [src/chat/sse.js](src/chat/sse.js), Freigabe-Karten für den `interrupt()` des Graphen `verarbeiten`.
