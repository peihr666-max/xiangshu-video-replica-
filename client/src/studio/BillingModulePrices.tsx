import { useEffect, useState } from "react";
import { type CustomerPricing, getWorkspacePricing } from "../api";

const subjects: Record<string, string[]> = {
  workbench: ["link_resolution", "asr"],
  viral: ["viral_data", "link_resolution", "asr"],
  "viral-detail": ["viral_data", "asr"],
  copy: ["rewrite", "asr"],
  replica: ["analysis", "rewrite", "first_frame", "video_768p", "video_2k"],
  replacement: ["analysis", "character", "first_frame", "video_768p", "video_2k"],
  video: ["video_768p", "video_2k"],
  reference: ["video_768p", "video_2k"],
  oral: ["oral"],
  "oral-audio": ["oral"],
  people: ["character", "avatar_clone", "voice_clone"],
  "person-photos": ["character"],
  "person-avatars": ["avatar_clone"],
  "person-voices": ["voice_clone", "voice_demo"],
};

export function BillingModulePrices({ page }: { page: string }) {
  const [pricing, setPricing] = useState<CustomerPricing>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setError("");
    if (!subjects[page]) return;
    void getWorkspacePricing().then((value) => { if (active) setPricing(value); })
      .catch(() => { if (active) setError("功能价格暂时读取失败，请刷新后查看。"); });
    return () => { active = false; };
  }, [page]);
  if (!subjects[page]) return null;
  return <aside className="studio-billing-prices" aria-label="本模块计费说明">
    <p>{error || (pricing ? pricing.prices.filter((price) => subjects[page].includes(price.subject)).map((price) => `${price.name}：${price.unit_credits === 0 ? "免费" : `${price.unit_credits} 积分/${price.unit}`}`).join(" · ") : "正在读取功能价格…")}</p>
    <small>各功能逐项扣分，提交时预留预算，成功后按实际用量结算。失败项目退回积分，未配置售价的项目由平台承担。</small>
  </aside>;
}
