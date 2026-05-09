/** 数据为 UTC（或带 Z 的 ISO）；界面统一按 Asia/Shanghai 展示 */

const SZ = "Asia/Shanghai";

/** `YYYY-MM-DD HH:mm:ss`，不可解析则原样返回字符串 */
export function formatIsoToBeijing(iso: string | null | undefined): string {
  if (iso == null || iso === "") return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const dateStr = d.toLocaleDateString("sv-SE", { timeZone: SZ });
  const timeStr = d.toLocaleTimeString("sv-SE", {
    timeZone: SZ,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  return `${dateStr} ${timeStr}`;
}
