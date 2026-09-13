const platforms = {
  douyin: { name: "抖音", file: "douyin" },
  wechat_channels: { name: "视频号", file: "wechat_channels" },
  xiaohongshu: { name: "小红书", file: "xiaohongshu" },
};

export type PublishPlatform = keyof typeof platforms;
export const publishPlatformNames = Object.fromEntries(
  Object.entries(platforms).map(([key, value]) => [key, value.name]),
) as Record<PublishPlatform, string>;

export function PlatformLogo({
  platform,
  size = 24,
}: {
  platform: string;
  size?: number;
}) {
  const item =
    platforms[platform as PublishPlatform] ??
    Object.values(platforms).find((value) => value.name === platform);
  if (!item) return null;
  return (
    <img
      src={`/platforms/${item.file}.ico`}
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      style={{ objectFit: "contain", verticalAlign: "middle", flexShrink: 0 }}
    />
  );
}
