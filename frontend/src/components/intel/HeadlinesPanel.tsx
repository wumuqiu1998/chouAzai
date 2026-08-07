import { useState, useEffect } from "react";
import { RefreshCw, Loader2, AlertCircle, Star, Newspaper, MessageSquare } from "lucide-react";
import { api, ApiError, type HeadlinesData } from "@/lib/api";
import { cn } from "@/lib/utils";

// 全球科技头条面板：海外一手大新闻收口，两个子模块 ——
//   📰 新闻 = 编辑精选科技头版（Techmeme，零依赖）；🐦 X = 高信号一手账号（选装，本机 x-cli）。
// 头条本身已是编辑/账号两层提炼过的要点，面板不再叠加 AI 摘要。
// 只聚合公开资讯；rel/⭐ 为关键词机械匹配，不代表推荐、不预测涨跌。

const shortT = (iso: string) => (iso || "").slice(5, 16).replace("T", " ");
const cleanZh = (zh?: string) => (zh || "").replace(/^⭐/, "");

export function HeadlinesPanel() {
  const [data, setData] = useState<HeadlinesData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [onlyRelevant, setOnlyRelevant] = useState(false);

  useEffect(() => {
    api.headlines().then(setData).catch((e) => setErr(e instanceof ApiError ? e.message : "加载失败"));
  }, []);

  const refresh = async () => {
    setRefreshing(true); setErr(null);
    try { setData(await api.headlinesRefresh()); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "刷新失败"); }
    finally { setRefreshing(false); }
  };

  const hasData = !!data?.generated_at;
  const news = (data?.news || []).filter((it) => !onlyRelevant || it.rel);
  const xposts = (data?.x || []).filter((it) => !onlyRelevant || it.rel);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          {hasData
            ? `${data!.news_provider} 头版 + X ${data!.x_accounts} 个高信号账号 · 近 ${data!.window_hours} 小时 · 更新于 ${data!.generated_at}（北京时间）`
            : `${data?.news_provider ?? "Techmeme"} 头版 + X 高信号账号 · 每天先看世界发生了什么`}
        </span>
        <div className="flex items-center gap-2">
          {hasData && (
            <button onClick={() => setOnlyRelevant((v) => !v)}
              className={cn("inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition-colors",
                onlyRelevant ? "border-primary bg-primary/15 font-medium text-primary" : "border-border text-muted-foreground hover:text-foreground")}>
              <Star className="h-4 w-4" /> 只看相关
            </button>
          )}
          <button onClick={refresh} disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {refreshing ? "抓取中…" : "刷新"}
          </button>
        </div>
      </div>

      {err && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> {err}
        </div>
      )}

      {!hasData && !err ? (
        <div className="rounded-lg border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/70">
          还没有抓取头条，点上方<b className="text-foreground">「刷新」</b>拉取（新闻约 10 秒；接了 X 模块约 1-2 分钟）。
        </div>
      ) : hasData ? (
        <>
          {/* 📰 新闻模块：编辑精选科技头版（时间倒序，最新在最上） */}
          <div className="mb-2 flex items-baseline gap-2">
            <span className="flex items-center gap-1.5 text-sm font-semibold"><Newspaper className="h-4 w-4 text-primary" /> 新闻 · {data!.news_provider} 头版</span>
            <span className="text-xs text-muted-foreground/70">编辑精选 · {news.length} 条</span>
          </div>
          <div className="mb-5 space-y-2">
            {news.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground/60">{onlyRelevant ? "暂无命中关键词的条目" : "暂无头条"}</p>
            ) : (
              news.map((it, i) => (
                <a key={i} href={it.url} target="_blank" rel="noreferrer"
                  className={cn("group flex items-baseline gap-3 border-b border-border/30 pb-2 text-sm last:border-0", it.rel && "bg-primary/5")}>
                  <span className="w-24 shrink-0 font-mono text-xs text-muted-foreground/70">{shortT(it.time)}</span>
                  <span className="flex-1 group-hover:text-primary">
                    {it.rel && <Star className="mr-1 inline h-3 w-3 text-primary/80" />}
                    {cleanZh(it.zh) || it.title}
                    {it.src && <span className="ml-2 whitespace-nowrap text-[11px] text-muted-foreground/70">· {it.src}</span>}
                  </span>
                </a>
              ))
            )}
          </div>

          {/* 🐦 X 模块：高信号一手账号（选装） */}
          <div className="mb-2 flex items-baseline gap-2">
            <span className="flex items-center gap-1.5 text-sm font-semibold"><MessageSquare className="h-4 w-4 text-primary" /> X · 高信号一手账号</span>
            <span className="text-xs text-muted-foreground/70">{data!.x_accounts} 个账号 · 近 {data!.window_hours} 小时 · {xposts.length} 条</span>
          </div>
          {!data!.x_available ? (
            <div className="rounded-lg border border-dashed border-border/70 p-5 text-center text-xs text-muted-foreground/70">
              X 模块未接入（选装）：本机安装并登录 x-cli 后自动启用，不影响新闻模块。
            </div>
          ) : (
            <div className="space-y-2">
              {xposts.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground/60">{onlyRelevant ? "暂无命中关键词的条目" : `近 ${data!.window_hours} 小时暂无发帖`}</p>
              ) : (
                xposts.map((it, i) => (
                  <a key={i} href={it.url} target="_blank" rel="noreferrer"
                    className={cn("group flex items-baseline gap-3 border-b border-border/30 pb-2 text-sm last:border-0", it.rel && "bg-primary/5")}>
                    <span className="w-24 shrink-0 font-mono text-xs text-muted-foreground/70">{shortT(it.time)}</span>
                    <span className="w-28 shrink-0 truncate text-xs font-semibold" title={`${it.handle} · ${it.role}`}>
                      {it.hub && <Star className="mr-0.5 inline h-3 w-3 text-primary" />}{it.name.split(" · ")[0]}
                    </span>
                    <span className="flex-1 group-hover:text-primary">{cleanZh(it.zh) || it.text}</span>
                  </a>
                ))
              )}
            </div>
          )}

          <p className="mt-4 text-[11px] text-muted-foreground/60">
            只聚合公开资讯；⭐/相关标记为产业关键词机械匹配，不代表推荐、不预测涨跌。时间均为北京时间。
          </p>
        </>
      ) : null}
    </div>
  );
}
