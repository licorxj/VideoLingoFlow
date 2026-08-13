import { useState } from "react";
import {
  LayoutDashboard,
  Server,
  GitBranch,
  MessageSquare,
  ScrollText,
  Settings,
} from "lucide-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "./i18n";
import { Toaster } from "@/components/ui/toaster";

import Dashboard from "./Dashboard";
import Providers from "./Providers";
import Strategies from "./Strategies";
import Chat from "./Chat";
import Logs from "./Logs";
import LLMSettings from "./Settings";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const subTabs = [
  { id: "dashboard", label: "仪表盘", icon: LayoutDashboard },
  { id: "providers", label: "平台管理", icon: Server },
  { id: "strategies", label: "路由策略", icon: GitBranch },
  { id: "chat", label: "AI 对话", icon: MessageSquare },
  { id: "logs", label: "请求日志", icon: ScrollText },
  { id: "settings", label: "系统设置", icon: Settings },
];

function LLMRouterContent() {
  const [activeTab, setActiveTab] = useState("dashboard");

  const renderContent = () => {
    switch (activeTab) {
      case "dashboard":
        return <Dashboard />;
      case "providers":
        return <Providers />;
      case "strategies":
        return <Strategies />;
      case "chat":
        return <Chat />;
      case "logs":
        return <Logs />;
      case "settings":
        return <LLMSettings />;
      default:
        return <Dashboard />;
    }
  };

  return (
    <div className="flex w-full gap-0" style={{ height: "calc(100vh - 7rem)" }}>
      {/* Vertical sidebar navigation */}
      <nav className="w-48 shrink-0 flex flex-col gap-1 py-2 pr-4 border-r border-border/40">
        <div className="px-3 py-2 mb-1">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">大模型路由器</h3>
        </div>
        {subTabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200 text-left ${
                activeTab === tab.id
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {tab.label}
            </button>
          );
        })}
      </nav>

      {/* Content area */}
      <div className="flex-1 min-w-0 overflow-auto pl-4 animate-fade-in-up">
        {renderContent()}
      </div>
      <Toaster />
    </div>
  );
}

export default function LLMRouter() {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <LLMRouterContent />
      </I18nProvider>
    </QueryClientProvider>
  );
}
