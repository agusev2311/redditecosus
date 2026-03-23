import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "../api";
import MediaCard from "../components/MediaCard";
import MetricBar from "../components/MetricBar";
import { useAuth } from "../contexts/AuthContext";
import { formatBytes, formatRate } from "../lib/format";

export default function DashboardPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [metrics, setMetrics] = useState(null);
  const [recentMedia, setRecentMedia] = useState([]);
  const [uploads, setUploads] = useState([]);
  const [heroIndex, setHeroIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [mediaResponse, uploadResponse, metricsResponse] = await Promise.all([
          apiFetch("/media?perPage=6"),
          apiFetch("/uploads"),
          isAdmin ? apiFetch("/admin/metrics") : Promise.resolve(null),
        ]);
        if (!cancelled) {
          setRecentMedia(mediaResponse.items || []);
          setUploads(uploadResponse.items || []);
          setMetrics(metricsResponse);
        }
      } catch {
        if (!cancelled) {
          setMetrics(null);
        }
      }
    }
    load();
    const timer = window.setInterval(load, isAdmin ? 5000 : 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [isAdmin]);

  useEffect(() => {
    if (recentMedia.length < 2) return undefined;
    const timer = window.setInterval(() => {
      setHeroIndex((current) => (current + 1) % recentMedia.length);
    }, 9000);
    return () => window.clearInterval(timer);
  }, [recentMedia]);

  const heroMedia = useMemo(() => {
    const images = recentMedia.filter((item) => item.mediaType === "image");
    if (images.length) {
      return images[heroIndex % images.length];
    }
    return recentMedia[0];
  }, [heroIndex, recentMedia]);

  return (
    <div className="page-grid">
      <section
        className="glass hero-panel"
        style={
          heroMedia
            ? {
                backgroundImage: `var(--hero-overlay), url(${heroMedia.previewUrl})`,
              }
            : undefined
        }
      >
        <div>
          <p className="eyebrow">личный архив</p>
          <h1>Быстрый поиск мемов, видосов и всего остального</h1>
          <p className="muted">
            Теги, дубликаты, разметка, временный шаринг, экспорт, импорт и мониторинг сервера в одном месте.
          </p>
        </div>
        <div className="hero-stats">
          <div className="stat-chip">
            <strong>{recentMedia.length}</strong>
            <span>последние файлы</span>
          </div>
          <div className="stat-chip">
            <strong>{uploads.length}</strong>
            <span>последние загрузки</span>
          </div>
          <div className="stat-chip">
            <strong>{isAdmin ? "admin" : "member"}</strong>
            <span>роль</span>
          </div>
        </div>
      </section>

      {isAdmin && metrics ? (
        <section className="glass panel">
          <div className="section-head">
            <div>
              <p className="eyebrow">server live</p>
              <h2>Нагрузка и диск</h2>
            </div>
            {metrics.alerts?.disk?.active ? <div className="warning-pill">{metrics.alerts.disk.message}</div> : null}
          </div>
          <div className="stats-grid">
            <MetricBar label="CPU" percent={metrics.cpu.percent} />
            <MetricBar label="RAM" percent={metrics.memory.percent} />
            <MetricBar label="Disk" percent={metrics.disk.percent} />
          </div>
          <div className="split-grid">
            <div className="panel-block">
              <h3>Сеть</h3>
              <p>Входящий поток: {formatRate(metrics.network.recvRate)}</p>
              <p>Исходящий поток: {formatRate(metrics.network.sendRate)}</p>
              <p>Свободно на диске: {formatBytes(metrics.disk.freeBytes)}</p>
            </div>
            <div className="panel-block">
              <h3>Что занимает место</h3>
              {metrics.disk.categories.map((category) => (
                <MetricBar
                  key={category.label}
                  label={category.label}
                  percent={(category.sizeBytes / Math.max(metrics.disk.totalBytes, 1)) * 100}
                  bytes={category.sizeBytes}
                />
              ))}
            </div>
          </div>
        </section>
      ) : null}

      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">recent media</p>
            <h2>Последние добавления</h2>
          </div>
        </div>
        <div className="media-grid compact-grid">
          {recentMedia.map((item) => (
            <MediaCard key={item.id} item={item} compact />
          ))}
        </div>
      </section>

      <section className="glass panel">
        <div className="section-head">
          <div>
            <p className="eyebrow">uploads</p>
            <h2>Очередь и последние батчи</h2>
          </div>
        </div>
        <div className="list-stack">
          {uploads.map((batch) => (
            <div key={batch.id} className="list-row">
              <div>
                <strong>{batch.id.slice(0, 8)}</strong>
                <p className="muted">
                  {batch.status} • {batch.uploadedFiles}/{batch.clientTotalFiles || batch.uploadedFiles} файлов
                </p>
              </div>
              <div className="mono">
                {batch.processedItems}/{batch.totalItems || "?"}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
