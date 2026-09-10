import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ToolBadge from "./ToolBadge.jsx";
import ChartViewer from "./ChartViewer.jsx";
import ToolTrace from "./ToolTrace.jsx";

const orario = (timestamp) =>
  new Date(timestamp).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });

export default function MessageBubble({ messaggio }) {
  const isUtente = messaggio.role === "user";

  return (
    <div className={`messaggio ${isUtente ? "messaggio--utente" : "messaggio--assistente"}`}>
      <div className={`avatar ${isUtente ? "avatar--utente" : "avatar--bot"}`} aria-hidden="true">
        {isUtente ? "TU" : "☕"}
      </div>

      <div className="messaggio__corpo">
        <div className={`bolla ${isUtente ? "bolla--utente" : "bolla--assistente"} ${messaggio.error ? "bolla--errore" : ""}`}>
          {isUtente ? (
            <p>{messaggio.content}</p>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{messaggio.content}</ReactMarkdown>
          )}
        </div>

        {!isUtente && !messaggio.error && (
          <>
            <ChartViewer charts={messaggio.charts} />
            <div className="messaggio__meta">
              <ToolBadge tool={messaggio.toolUsed} />
              {messaggio.elapsedMs != null && (
                <span className="meta__tempo">{(messaggio.elapsedMs / 1000).toFixed(1)}s</span>
              )}
            </div>
            <ToolTrace trace={messaggio.trace} sources={messaggio.sources} />
          </>
        )}

        <span className="messaggio__ora">{orario(messaggio.timestamp)}</span>
      </div>
    </div>
  );
}
