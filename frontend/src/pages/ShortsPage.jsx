import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../api";
import TagBadge from "../components/TagBadge";
import { formatBytes } from "../lib/format";

function shuffleItems(items) {
  const copy = [...items];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [copy[index], copy[swapIndex]] = [copy[swapIndex], copy[index]];
  }
  return copy;
}

export default function ShortsPage() {
  const navigate = useNavigate();
  const feedRef = useRef(null);
  const videoRefs = useRef(new Map());
  const [items, setItems] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [muted, setMuted] = useState(true);
  const [error, setError] = useState("");

  async function loadFeed(targetPage = 1, { replace = false, reshuffle = false } = {}) {
    setLoading(true);
    setError("");
    try {
      const response = await apiFetch(`/media?mediaType=video&perPage=8&page=${targetPage}`);
      const nextItems = reshuffle ? shuffleItems(response.items || []) : response.items || [];
      setItems((current) => (replace ? nextItems : [...current, ...nextItems]));
      setPage(targetPage);
      setPages(response.pages || 1);
    } catch (feedError) {
      setError(feedError.message || "Не удалось загрузить видео-ленту.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadFeed(1, { replace: true, reshuffle: true }).catch(() => undefined);
  }, []);

  useEffect(() => {
    const videos = [...videoRefs.current.values()];
    videos.forEach((video) => {
      if (!video) return;
      video.muted = muted;
    });
  }, [muted, items]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const video = entry.target;
          if (!(video instanceof HTMLVideoElement)) {
            return;
          }
          if (entry.isIntersecting && entry.intersectionRatio >= 0.7) {
            setActiveId(Number(video.dataset.mediaId));
            video.play().catch(() => undefined);
          } else {
            video.pause();
          }
        });
      },
      {
        root: feedRef.current,
        threshold: [0.35, 0.7, 1],
      }
    );

    const nodes = [...videoRefs.current.values()];
    nodes.forEach((node) => node && observer.observe(node));
    return () => observer.disconnect();
  }, [items]);

  const activeItem = useMemo(
    () => items.find((item) => item.id === activeId) || items[0] || null,
    [activeId, items]
  );

  function attachVideoRef(mediaId, node) {
    if (node) {
      videoRefs.current.set(mediaId, node);
    } else {
      videoRefs.current.delete(mediaId);
    }
  }

  function togglePlayback(mediaId) {
    const video = videoRefs.current.get(mediaId);
    if (!video) return;
    if (video.paused) {
      video.play().catch(() => undefined);
      setActiveId(mediaId);
      return;
    }
    video.pause();
  }

  async function loadMore() {
    if (loading || page >= pages) return;
    await loadFeed(page + 1);
  }

  function refreshFeed() {
    feedRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    loadFeed(1, { replace: true, reshuffle: true }).catch(() => undefined);
  }

  return (
    <div className="page-grid shorts-page">
      <section className="glass panel shorts-panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">for fun</p>
            <h1>Шортсы</h1>
            <p className="muted">Небольшая вертикальная лента по вашим видео. Просто полистать и позалипать.</p>
          </div>
          <div className="button-row shorts-toolbar">
            <button type="button" className="ghost-button" onClick={() => setMuted((current) => !current)}>
              {muted ? "Включить звук" : "Выключить звук"}
            </button>
            <button type="button" className="ghost-button" onClick={refreshFeed}>
              Освежить
            </button>
          </div>
        </div>

        {activeItem ? (
          <div className="shorts-meta-strip">
            <span className="status-pill">{muted ? "mute" : "sound on"}</span>
            <span className="status-pill">{formatBytes(activeItem.sizeBytes)}</span>
            <span className="status-pill">{activeItem.tags?.length || 0} тегов</span>
          </div>
        ) : null}

        {error ? <div className="error-box">{error}</div> : null}

        {items.length ? (
          <>
            <div ref={feedRef} className="shorts-feed">
              {items.map((item, index) => (
                <article key={item.id} className={`shorts-card ${activeId === item.id ? "shorts-card-active" : ""}`}>
                  <video
                    ref={(node) => attachVideoRef(item.id, node)}
                    className="shorts-video"
                    data-media-id={item.id}
                    src={item.fileUrl}
                    muted={muted}
                    loop
                    playsInline
                    preload={index === 0 ? "auto" : "metadata"}
                    poster={item.previewUrl || undefined}
                    onClick={() => togglePlayback(item.id)}
                  />
                  <div className="shorts-overlay">
                    <div className="shorts-copy">
                      <p className="eyebrow">video drop</p>
                      <h2>{item.originalFilename}</h2>
                      <p className="muted">
                        @{item.ownerName || "vault"} • {formatBytes(item.sizeBytes)}
                      </p>
                      <div className="tag-row">
                        {(item.tags || []).slice(0, 4).map((tag) => (
                          <TagBadge key={tag.id} tag={tag} />
                        ))}
                      </div>
                    </div>
                    <div className="shorts-rail">
                      <button type="button" className="ghost-button shorts-rail-button" onClick={() => togglePlayback(item.id)}>
                        {activeId === item.id ? "Пауза" : "Play"}
                      </button>
                      <button
                        type="button"
                        className="ghost-button shorts-rail-button"
                        onClick={() => navigate("/library")}
                      >
                        В библиотеку
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>

            <div className="button-row">
              <button type="button" className="ghost-button" disabled={loading || page >= pages} onClick={loadMore}>
                {loading ? "Гружу ещё…" : page >= pages ? "Видео закончились" : "Ещё видео"}
              </button>
            </div>
          </>
        ) : (
          <div className="success-box">Видео в библиотеке пока нет. Как только добавите ролики, здесь появится лента.</div>
        )}
      </section>
    </div>
  );
}
