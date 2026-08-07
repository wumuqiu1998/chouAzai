import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { DailyReview } from "@/pages/DailyReview";
import { AgentReview } from "@/pages/short-term/AgentReview";
import { ShortTermMarket } from "@/pages/short-term/ShortTermMarket";
import { FirstBoard } from "@/pages/short-term/FirstBoard";
import { AgentWeekly } from "@/pages/short-term/AgentWeekly";
import { Intel } from "@/pages/Intel";
import { Sectors } from "@/pages/Sectors";
import { SectorDetail } from "@/pages/SectorDetail";
import { Debate } from "@/pages/Debate";
import { Portfolio } from "@/pages/Portfolio";
import { StockData } from "@/pages/StockData";
import { Watchlist } from "@/pages/Watchlist";
import { MyReports } from "@/pages/MyReports";
import { Notes } from "@/pages/Notes";
import { Settings } from "@/pages/Settings";
import { QuantResearch } from "@/pages/QuantResearch";
import { LiveTrading } from "@/pages/LiveTrading";

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Navigate to="/daily-review" replace /> },
      { path: "/daily-review", element: <DailyReview /> },
      { path: "/short-term/review", element: <AgentReview /> },
      { path: "/short-term/market", element: <ShortTermMarket /> },
      { path: "/short-term/first-board", element: <FirstBoard /> },
      { path: "/short-term/heat", element: <AgentWeekly /> },
      { path: "/intel", element: <Intel /> },
      { path: "/sectors", element: <Sectors /> },
      { path: "/sectors/:key", element: <SectorDetail /> },
      { path: "/portfolio", element: <Portfolio /> },
      { path: "/stock-data", element: <StockData /> },
      { path: "/debate", element: <Debate /> },
      { path: "/quant-research", element: <QuantResearch /> },
      { path: "/live-trading", element: <LiveTrading /> },
      { path: "/watchlist", element: <Watchlist /> },
      { path: "/my-reports", element: <MyReports /> },
      { path: "/notes", element: <Notes /> },
      { path: "/settings", element: <Settings /> },
    ],
  },
]);
