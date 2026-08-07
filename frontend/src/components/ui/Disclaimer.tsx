import { Info } from "lucide-react";

// 私有项目免责声明：仅供个人使用，数据来自公开接口；市场有风险，决策与盈亏自负。
export function Disclaimer({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <p className="text-[11px] leading-relaxed text-muted-foreground/70">
        私有项目 · 仅供个人使用 · 市场有风险，决策与盈亏自负。
      </p>
    );
  }
  return (
    <div className="mt-8 flex items-start gap-2 rounded-lg border border-border/60 bg-muted/20 p-3 text-xs leading-relaxed text-muted-foreground">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>
        Vibe-Research 现在是你的<b className="text-foreground">私有投研与看盘工具</b>，数据来自公开接口，仅供个人使用。
        市场有风险，所有决策与盈亏由你自己负责。
      </span>
    </div>
  );
}
