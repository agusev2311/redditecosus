import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { apiFetch } from "../api";

export default function ShareViewPage() {
  const { token } = useParams();
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch(`/shares/public/${token}`, { token: "" })
      .then((response) => setPayload(response.item))
      .catch((fetchError) => setError(fetchError.message));
  }, [token]);

  if (error) {
    return (
      <div className="fullscreen-center">
        <div className="glass auth-card">
          <h1>Ссылка недоступна</h1>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  if (!payload) {
    return (
      <div className="fullscreen-center">
        <div className="glass auth-card">
          <h1>Открываю файл…</h1>
        </div>
      </div>
    );
  }

  return (
    <div className="fullscreen-center">
      <div className="glass share-card">
        <p className="eyebrow">temporary share</p>
        <h1>{payload.media.originalFilename}</h1>
        <div className="detail-preview">
          {payload.media.mediaType === "video" ? (
            <video src={payload.publicFileUrl} controls autoPlay playsInline />
          ) : (
            <img src={payload.publicFileUrl} alt={payload.media.originalFilename} />
          )}
        </div>
      </div>
    </div>
  );
}
