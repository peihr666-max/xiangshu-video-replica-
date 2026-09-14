import { useCallback, useEffect, useRef, useState } from "react";
import {
  adminActivationErrorMessage,
  type CollectedViralVideo,
  curateViralVideo,
  listCollectedViralVideos,
  previewCollectedViralVideo,
} from "../api.admin";
import { ConfirmDialog } from "./ui/ConfirmDialog";
import { PageBanner } from "./ui/PageBanner";
import { Pagination } from "./ui/Pagination";

type Action = "feature" | "unfeature" | "delete";

export function ViralVideosPage({ readOnly = false }: { readOnly?: boolean }) {
  const [items, setItems] = useState<CollectedViralVideo[]>([]);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState({
    platform: "",
    query: "",
    offset: 0,
  });
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [preview, setPreview] = useState<{ title: string; url: string } | null>(
    null,
  );
  const [pending, setPending] = useState<{
    video: CollectedViralVideo;
    action: Action;
    key: string;
  } | null>(null);
  const generation = useRef(0);
  const previewGeneration = useRef(0);
  const load = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const result = await listCollectedViralVideos(filters);
      if (current !== generation.current) return;
      setItems(result.items);
      setTotal(result.total);
    } catch (cause) {
      if (current === generation.current)
        setError(adminActivationErrorMessage(cause, "读取视频库失败"));
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }, [filters]);
  useEffect(() => {
    void load();
    return () => {
      generation.current += 1;
      previewGeneration.current += 1;
    };
  }, [load]);

  async function showPreview(video: CollectedViralVideo) {
    const current = ++previewGeneration.current;
    setError("");
    try {
      const result = await previewCollectedViralVideo(video);
      if (current === previewGeneration.current)
        setPreview({ title: video.title, url: result.url });
    } catch (cause) {
      if (current === previewGeneration.current)
        setError(adminActivationErrorMessage(cause, "读取预览失败"));
    }
  }
  async function confirm(reason: string) {
    if (!pending) return;
    setSaving(true);
    setError("");
    try {
      await curateViralVideo(
        pending.video,
        pending.action,
        reason,
        pending.key,
      );
      setNotice(
        pending.action === "delete"
          ? "视频已删除，前台不再展示。"
          : "首页展示设置已更新。",
      );
      setPending(null);
      setPreview(null);
      previewGeneration.current += 1;
      await load();
    } catch (cause) {
      setError(adminActivationErrorMessage(cause, "更新视频失败"));
    } finally {
      setSaving(false);
    }
  }
  function choose(video: CollectedViralVideo, action: Action) {
    setPending({ video, action, key: crypto.randomUUID() });
  }

  return (
    <section className="admin-panel" aria-label="爆款视频库">
      <h2>采集记录</h2>
      <p className="admin-hint">
        新采集视频默认保存在视频库。归档完成后，可选择展示到首页；取消首页展示后仍可在爆款列表查看。删除后前台不可用，已导入项目的素材保留。
      </p>
      {error && <PageBanner tone="error">{error}</PageBanner>}
      {notice && <PageBanner tone="notice">{notice}</PageBanner>}
      <form
        className="admin-toolbar"
        onSubmit={(event) => {
          event.preventDefault();
          setFilters({ ...filters, query: search.trim(), offset: 0 });
        }}
      >
        <label>
          平台筛选
          <select
            disabled={saving}
            value={filters.platform}
            onChange={(event) =>
              setFilters({
                ...filters,
                platform: event.target.value,
                offset: 0,
              })
            }
          >
            <option value="">全部平台</option>
            <option value="douyin">抖音</option>
            <option value="wechat_channels">视频号</option>
          </select>
        </label>
        <label>
          搜索视频
          <input
            disabled={saving}
            value={search}
            maxLength={100}
            placeholder="标题、作者或视频 ID"
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <button type="submit" disabled={saving}>
          搜索
        </button>
        <button
          type="button"
          disabled={loading || saving}
          onClick={() => void load()}
        >
          刷新数据
        </button>
      </form>
      {preview && (
        <section aria-label="云端视频预览">
          <h3>{preview.title}</h3>
          <video
            controls
            muted
            src={preview.url}
            style={{ width: "100%", maxHeight: 480 }}
          />
          <button
            type="button"
            onClick={() => {
              setPreview(null);
              previewGeneration.current += 1;
            }}
          >
            关闭预览
          </button>
        </section>
      )}
      {loading ? (
        <p role="status">正在读取采集记录…</p>
      ) : items.length === 0 ? (
        <p>暂无符合条件的采集视频。</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="admin-table">
            <thead>
              <tr>
                <th>视频</th>
                <th>时长与互动</th>
                <th>采集与归档</th>
                <th>首页</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((video) => (
                <tr key={`${video.platform}:${video.video_id}`}>
                  <td>
                    <strong>{video.title || "未命名视频"}</strong>
                    <p>
                      {video.platform === "douyin" ? "抖音" : "视频号"} ·{" "}
                      {video.category} · {video.author || "未知作者"}
                    </p>
                    <small style={{ overflowWrap: "anywhere" }}>
                      {video.video_id}
                    </small>
                  </td>
                  <td>
                    {(video.duration_ms / 1000).toFixed(1)} 秒
                    <p>
                      点赞 {video.likes} · 评论 {video.comments ?? "—"}
                    </p>
                    <p>
                      分享 {video.shares ?? "—"} · 收藏 {video.collects ?? "—"}
                    </p>
                  </td>
                  <td>
                    {video.media_status === "SUCCEEDED" && video.storage_uri
                      ? video.cover_required && !video.cover_key
                        ? "视频已归档，封面待补齐"
                        : "视频与封面已就绪"
                      : video.media_status === "FAILED"
                        ? "转存失败"
                        : "待转存"}
                    <p>
                      采集：{new Date(video.created_at).toLocaleString("zh-CN")}
                    </p>
                    <p>
                      发布：
                      {video.published_at
                        ? new Date(video.published_at * 1000).toLocaleString(
                            "zh-CN",
                          )
                        : "未知"}
                    </p>
                    <details>
                      <summary>云存储地址</summary>
                      <small style={{ overflowWrap: "anywhere" }}>
                        {video.storage_uri ?? "尚未生成"}
                      </small>
                    </details>
                  </td>
                  <td>{video.homepage_featured ? "展示中" : "未展示"}</td>
                  <td>
                    <button
                      type="button"
                      disabled={
                        saving ||
                        video.media_status !== "SUCCEEDED" ||
                        !video.storage_uri
                      }
                      onClick={() => void showPreview(video)}
                    >
                      预览
                    </button>
                    {!readOnly && (
                      <>
                        <button
                          type="button"
                          disabled={
                            saving ||
                            (!video.homepage_featured &&
                              (video.media_status !== "SUCCEEDED" ||
                                !video.storage_uri))
                          }
                          onClick={() =>
                            choose(
                              video,
                              video.homepage_featured ? "unfeature" : "feature",
                            )
                          }
                        >
                          {video.homepage_featured
                            ? "取消首页展示"
                            : "展示到首页"}
                        </button>
                        <button
                          type="button"
                          disabled={saving}
                          onClick={() => choose(video, "delete")}
                        >
                          删除
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination
        offset={filters.offset}
        limit={25}
        total={total}
        disabled={loading || saving}
        onPageChange={(offset) => setFilters({ ...filters, offset })}
      />
      <ConfirmDialog
        open={pending !== null}
        busy={saving}
        level="reason"
        title={pending?.action === "delete" ? "删除爆款视频" : "更新首页展示"}
        description={
          pending?.action === "delete"
            ? "该视频会从前台移除，后续采集也不会重新展示。已导入项目的素材保留。"
            : "已归档视频会自动补齐封面后展示到首页。请填写操作原因。"
        }
        confirmLabel="确认操作"
        onClose={() => setPending(null)}
        onConfirm={(reason) => void confirm(reason)}
      />
    </section>
  );
}
