import { useMemo, useState } from "react";
import { useStudio } from "./context";
import { createDraft } from "./state";
import type { StudioAsset, StudioPerson, StudioVideo } from "./types";
import { Button, Empty, Icon, Media, Panel } from "./ui";
import "./analytics.css";

type Range = "7" | "30";
type Platform = "all" | StudioVideo["platform"];

type ReviewWork = {
  id: string;
  sourceId: string;
  taskId?: string;
  personId: string;
  title: string;
  platform: StudioVideo["platform"];
  plays: number;
  likes: number;
  favorites: number;
  daysAgo: number;
};

const reviewWorks: ReviewWork[] = [
  {
    id: "budget",
    sourceId: "抖音-1",
    taskId: "task-completed",
    personId: "zhang",
    title: "张工 · 建房预算",
    platform: "抖音",
    plays: 42_000,
    likes: 980,
    favorites: 320,
    daysAgo: 1,
  },
  {
    id: "courtyard",
    sourceId: "抖音-4",
    personId: "li",
    title: "新中式庭院的3个细节",
    platform: "抖音",
    plays: 35_000,
    likes: 820,
    favorites: 260,
    daysAgo: 3,
  },
  {
    id: "layout",
    sourceId: "视频号-3",
    personId: "wang",
    title: "农村自建房户型避坑",
    platform: "视频号",
    plays: 29_000,
    likes: 600,
    favorites: 280,
    daysAgo: 5,
  },
  {
    id: "three-generations",
    sourceId: "抖音-2",
    personId: "zhang",
    title: "三代同堂的家这样设计",
    platform: "抖音",
    plays: 31_000,
    likes: 710,
    favorites: 210,
    daysAgo: 14,
  },
];

const sevenDayTrend = {
  labels: ["08-30", "08-31", "09-01", "09-02", "09-03", "09-04", "09-05"],
  values: [1.2, 1.6, 1.8, 2.0, 1.9, 2.1, 2.2],
};

const thirtyDayTrend = {
  labels: ["08-07", "08-12", "08-17", "08-22", "08-27", "09-01", "09-05"],
  values: [4.8, 5.1, 5.6, 6.2, 6.7, 7.1, 7.8],
};

function formatInteger(value: number) {
  return Math.round(value).toLocaleString("zh-CN");
}

function formatWan(value: number) {
  return `${value.toFixed(1)} 万`;
}

function formatCompactWan(value: number) {
  return `${value.toFixed(1)}万`;
}

function personFactor(personId: string) {
  return personId === "zhang"
    ? 4.2 / 12.8
    : personId === "li"
      ? 3.5 / 12.8
      : personId === "wang"
        ? 2.9 / 12.8
        : 0.16;
}

function WorkThumb({ video, title }: { video: StudioVideo; title: string }) {
  const asset: StudioAsset = {
    id: video.id,
    name: title,
    kind: "image",
    url: video.poster,
    group: video.category,
    source: video.platform,
    saved: true,
  };
  return <Media asset={asset} alt={title} />;
}

function TrendChart({
  labels,
  values,
  rangeLabel,
}: {
  labels: string[];
  values: number[];
  rangeLabel: string;
}) {
  const width = 700;
  const height = 220;
  const left = 48;
  const right = 18;
  const top = 26;
  const bottom = 44;
  const maxValue = Math.max(3, Math.ceil(Math.max(...values)));
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const points = values.map((value, index) => ({
    x: left + (chartWidth * index) / Math.max(1, values.length - 1),
    y: top + chartHeight * (1 - value / maxValue),
    value,
  }));
  const pointList = points.map(({ x, y }) => `${x},${y}`).join(" ");
  const area = `M ${left} ${height - bottom} L ${pointList.replaceAll(" ", " L ")} L ${width - right} ${height - bottom} Z`;
  const ticks = [0, 1, 2, 3].map((value) => (value * maxValue) / 3);

  return (
    <svg
      className="analytics-trend-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${rangeLabel}播放趋势`}
    >
      <defs>
        <linearGradient id="analytics-trend-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#e8ad29" stopOpacity=".35" />
          <stop offset="1" stopColor="#e8ad29" stopOpacity=".04" />
        </linearGradient>
      </defs>
      {ticks.map((tick) => {
        const y = top + chartHeight * (1 - tick / maxValue);
        return (
          <g key={tick}>
            <line x1={left} x2={width - right} y1={y} y2={y} />
            <text x={left - 12} y={y + 5} textAnchor="end">
              {tick === 0 ? "0" : `${tick.toFixed(0)}万`}
            </text>
          </g>
        );
      })}
      <line x1={left} x2={left} y1={top} y2={height - bottom} />
      <path d={area} className="analytics-trend-area" />
      <polyline points={pointList} className="analytics-trend-line" />
      {points.map((point, index) => (
        <g key={labels[index]}>
          <circle cx={point.x} cy={point.y} r="5" />
          <text
            className="analytics-point-value"
            x={point.x}
            y={point.y - 14}
            textAnchor="middle"
          >
            {point.value.toFixed(1)}万
          </text>
          <text x={point.x} y={height - 16} textAnchor="middle">
            {labels[index]}
          </text>
        </g>
      ))}
    </svg>
  );
}

export function AnalyticsPage() {
  const { data, review, navigate, patchDraft } = useStudio();
  const [range, setRange] = useState<Range>("7");
  const [platform, setPlatform] = useState<Platform>("all");
  const [personId, setPersonId] = useState("all");

  const works = useMemo(
    () =>
      reviewWorks
        .filter(
          (work) =>
            work.daysAgo <= Number(range) &&
            (platform === "all" || work.platform === platform) &&
            (personId === "all" || work.personId === personId),
        )
        .map((work) => ({
          ...work,
          video: data.videos.find((video) => video.id === work.sourceId),
          person: data.people.find((person) => person.id === work.personId),
          task: work.taskId
            ? data.tasks.find((task) => task.id === work.taskId)
            : undefined,
        }))
        .filter(
          (
            work,
          ): work is typeof work & {
            video: StudioVideo;
            person: StudioPerson;
          } => Boolean(work.video && work.person),
        ),
    [data.people, data.tasks, data.videos, personId, platform, range],
  );

  if (!review)
    return (
      <section className="analytics-page analytics-empty-page">
        <Empty
          title="数据接口尚未接通"
          description="正式数据接通后，将在这里呈现按时间、平台与人物筛选的真实表现。"
        />
      </section>
    );

  const baseTrend = range === "7" ? sevenDayTrend : thirtyDayTrend;
  const rangeLabel = range === "7" ? "近7天" : "近30天";
  const platformScale =
    platform === "抖音" ? 0.625 : platform === "视频号" ? 0.375 : 1;
  const scale =
    platformScale * (personId === "all" ? 1 : personFactor(personId));
  const trendValues = baseTrend.values.map((value) => value * scale);
  const playTotal = trendValues.reduce((sum, value) => sum + value, 0);
  const timeScale = range === "7" ? 1 : 4;
  const metrics = [
    {
      label: "已发布视频",
      value: `${Math.max(works.length, Math.round(21 * timeScale * scale))} 个`,
      icon: "video",
    },
    { label: "播放量", value: formatWan(playTotal), icon: "chart" },
    {
      label: "互动量",
      value: formatInteger(3_420 * timeScale * scale),
      icon: "heart",
    },
    {
      label: "收藏量",
      value: formatInteger(860 * timeScale * scale),
      icon: "star",
    },
  ];
  const visiblePlatformTotals = { 抖音: 0, 视频号: 0 };
  for (const work of works) {
    visiblePlatformTotals[work.platform] += work.plays;
  }
  const defaultShare = platform === "all" && personId === "all";
  const shareTotal = visiblePlatformTotals.抖音 + visiblePlatformTotals.视频号;
  const douyinShare =
    platform === "抖音"
      ? 100
      : platform === "视频号"
        ? 0
        : defaultShare
          ? 62.5
          : shareTotal
            ? (visiblePlatformTotals.抖音 / shareTotal) * 100
            : 0;
  const wechatShare = 100 - douyinShare;
  const douyinPlays = playTotal * (douyinShare / 100);
  const wechatPlays = playTotal - douyinPlays;

  function viewWork(work: (typeof works)[number]) {
    if (work.task) {
      navigate("task-detail", {
        selectedTaskId: work.task.id,
        returnTo: "analytics",
      });
      return;
    }
    navigate("viral-detail", {
      selectedVideoId: work.video.id,
      returnTo: "analytics",
    });
  }

  function recreate(work: (typeof works)[number]) {
    const fresh = createDraft();
    patchDraft({
      ipId: work.person.id,
      sourceId: work.video.id,
      projectId: undefined,
      selectedShotId: fresh.selectedShotId,
      originalImageId: undefined,
      imageId: undefined,
      firstFrameId: undefined,
      tailFrameId: undefined,
      avatarId: undefined,
      voiceId: undefined,
      audioId: undefined,
      script: fresh.script,
      prompt: fresh.prompt,
      referenceIds: [],
      resolution: fresh.resolution,
      ratio: fresh.ratio,
      duration: fresh.duration,
      count: fresh.count,
      frameConfirmed: false,
      style: fresh.style,
      subtitles: fresh.subtitles,
    });
    navigate("replica", {
      selectedVideoId: work.video.id,
      returnTo: "analytics",
    });
  }

  return (
    <section className="analytics-page">
      <header className="analytics-heading">
        <h1>数据看板</h1>
      </header>

      <fieldset className="analytics-filters">
        <legend>数据筛选</legend>
        <label>
          <Icon name="clock" size={18} />
          <select
            aria-label="时间筛选"
            value={range}
            onChange={(event) => setRange(event.target.value as Range)}
          >
            <option value="7">近7天</option>
            <option value="30">近30天</option>
          </select>
        </label>
        <label>
          <select
            aria-label="平台筛选"
            value={platform}
            onChange={(event) => setPlatform(event.target.value as Platform)}
          >
            <option value="all">全部平台</option>
            <option value="抖音">抖音</option>
            <option value="视频号">视频号</option>
          </select>
        </label>
        <label>
          <select
            aria-label="人物筛选"
            value={personId}
            onChange={(event) => setPersonId(event.target.value)}
          >
            <option value="all">全部人物</option>
            {data.people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.name}
              </option>
            ))}
          </select>
        </label>
        <span className="analytics-sample-mark">
          <i />
          示例数据
        </span>
      </fieldset>

      <div className="analytics-metrics">
        {metrics.map((metric) => (
          <Panel key={metric.label} className="analytics-metric">
            <span className="analytics-metric-icon">
              <Icon name={metric.icon} size={34} />
            </span>
            <div>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
              <small>{rangeLabel}</small>
            </div>
          </Panel>
        ))}
      </div>

      <div className="analytics-charts">
        <Panel className="analytics-trend">
          <h2>
            播放趋势 <small>{rangeLabel}</small>
          </h2>
          <TrendChart
            labels={baseTrend.labels}
            values={trendValues}
            rangeLabel={rangeLabel}
          />
          <p>合计播放：{formatWan(playTotal)}</p>
        </Panel>
        <Panel className="analytics-share">
          <h2>
            平台占比 <small>{rangeLabel}</small>
          </h2>
          <div className="analytics-share-body">
            <div
              className="analytics-donut"
              style={{
                background: `conic-gradient(#efb524 0 ${douyinShare}%, #916916 ${douyinShare}% 100%)`,
              }}
            >
              <strong>{douyinShare.toFixed(1)}%</strong>
            </div>
            <dl>
              <div>
                <dt>
                  <i className="is-douyin" />
                  抖音
                </dt>
                <dd>
                  {formatCompactWan(douyinPlays)}（{douyinShare.toFixed(1)}%）
                </dd>
              </div>
              <div>
                <dt>
                  <i className="is-wechat" />
                  视频号
                </dt>
                <dd>
                  {formatCompactWan(wechatPlays)}（{wechatShare.toFixed(1)}%）
                </dd>
              </div>
            </dl>
          </div>
          <p>合计播放：{formatWan(playTotal)}</p>
        </Panel>
      </div>

      <Panel className="analytics-performance">
        <h2>作品表现</h2>
        {works.length ? (
          <div className="analytics-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>作品</th>
                  <th>平台</th>
                  <th>人物</th>
                  <th>播放量</th>
                  <th>点赞量</th>
                  <th>收藏量</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {works.map((work) => (
                  <tr key={work.id}>
                    <td>
                      <div className="analytics-work">
                        <WorkThumb video={work.video} title={work.title} />
                        <strong>{work.title}</strong>
                      </div>
                    </td>
                    <td>
                      <span
                        className={`analytics-platform analytics-platform--${work.platform === "抖音" ? "douyin" : "wechat"}`}
                      >
                        <i />
                        {work.platform}
                      </span>
                    </td>
                    <td>
                      <span className="analytics-person">
                        {work.person.portrait ? (
                          <img src={work.person.portrait} alt="" />
                        ) : (
                          <Icon name="person" />
                        )}
                        {work.person.name}
                      </span>
                    </td>
                    <td>{formatCompactWan(work.plays / 10_000)}</td>
                    <td>{formatInteger(work.likes)}</td>
                    <td>{formatInteger(work.favorites)}</td>
                    <td>
                      <div className="analytics-actions">
                        <Button
                          variant="outline"
                          onClick={() => viewWork(work)}
                        >
                          查看视频
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => recreate(work)}
                        >
                          再次创作（从该视频）
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="当前筛选下暂无作品"
            description="请调整时间、平台或人物筛选。"
          />
        )}
      </Panel>
    </section>
  );
}
